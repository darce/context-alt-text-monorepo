<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-recognition-route-controller.php';
require_once __DIR__ . '/class-recognition-circuit-keys.php';
require_once __DIR__ . '/class-recognition-endpoint-resolver.php';
require_once __DIR__ . '/class-recognition-proxy-policy.php';
require_once __DIR__ . '/class-tenant-identity.php';
require_once __DIR__ . '/class-blob-url-rewriter.php';
require_once __DIR__ . '/../support/class-recognition-transport.php';

use AltContext\Support\RecognitionTransport;
use Traversable;
use WP_Error;
use WP_REST_Response;

use function apply_filters;
use function add_query_arg;
use function current_user_can;
use function delete_transient;
use function esc_url_raw;
use function get_transient;
use function get_option;
use function in_array;
use function is_wp_error;
use function md5;
use function set_transient;
use function strtotime;
use function strtolower;
use function time;
use function untrailingslashit;
use function wp_json_encode;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_headers;
use function wp_remote_retrieve_response_code;
use function trim;

abstract class AbstractRecognitionProxyController implements RecognitionRouteControllerInterface {
	/**
	 * Proxy path refused a 3xx from the recognition service (redirection=0).
	 * Classified by is_proxy_redirect_refused() as reachable-but-bad.
	 */
	public const ERROR_CODE_REDIRECT_REFUSED = 'recognition_unexpected_redirect';

	/**
	 * Blob path refused a 3xx. Same classification as ERROR_CODE_REDIRECT_REFUSED
	 * (reachable-but-bad / not UNAVAILABLE), but keeps the blob-specific wire code
	 * and status so blob response behaviour stays identical (R6L-BR-04 / [sr-007]).
	 */
	public const ERROR_CODE_BLOB_REDIRECT_REFUSED = 'recognition_blob_redirect_refused';

	private ?RecognitionProxyPolicy $proxy_policy = null;
	private ?RecognitionEndpointResolver $endpoint_resolver = null;

	public function can_manage_recognition(): bool {
		return current_user_can( 'manage_options' );
	}

	protected function proxy_request(
		string $method,
		string $path,
		array $body = array(),
		array $query = array(),
		string $request_class = 'auto',
		string $body_kind = 'json',
		?int $max_body_bytes = null
	): WP_REST_Response|WP_Error {
		// E15-11 Slice 2: 'json' (default) JSON-encodes the body and declares
		// Content-Type: application/json. 'multipart' passes the body array
		// verbatim to wp_remote_request so WordPress builds the
		// multipart/form-data body and sets the boundary Content-Type itself.
		if ( 'json' !== $body_kind && 'multipart' !== $body_kind ) {
			return new WP_Error(
				'recognition_invalid_body_kind',
				sprintf( "Unsupported body_kind '%s'; expected 'json' or 'multipart'.", $body_kind ),
				array( 'status' => 500 )
			);
		}

		$recognition_base_url = $this->get_recognition_base_url();
		if ( '' === $recognition_base_url ) {
			return new WP_Error( 'recognition_not_configured', 'Recognition service URL is missing.', array( 'status' => 500 ) );
		}

		$base_url = untrailingslashit( $recognition_base_url );
		$url      = esc_url_raw( $base_url . $path );

		if ( ! empty( $query ) ) {
			$url = esc_url_raw( add_query_arg( $query, $url ) );
		}

		$headers = array(
			'X-Tenant-ID' => $this->get_tenant_id(),
		);
		if ( 'json' === $body_kind ) {
			$headers['Content-Type'] = 'application/json';
		}
		// For 'multipart' the Content-Type with boundary is set below
		// alongside the serialized body — wp_remote_request does NOT
		// auto-build multipart/form-data from a plain array (BR-09).

		$api_key = $this->get_recognition_api_key();
		if ( '' === $api_key ) {
			return new WP_Error(
				'recognition_api_key_missing',
				'Recognition API key is not configured. Set it in Settings > Alt Context, or define the ACX_RECOGNITION_API_KEY constant.',
				array( 'status' => 500 )
			);
		}
		$headers['X-API-Key'] = $api_key;

		$policy = $this->get_proxy_policy()->resolve( $method, $request_class );
		$circuit_key = $this->build_circuit_breaker_key( $base_url );
		$failure_key = RecognitionCircuitKeys::failure_key_for_base_url( $base_url );

		if ( $policy['circuit_enabled'] && false !== get_transient( $circuit_key ) ) {
			return new WP_Error(
				'recognition_circuit_open',
				'Recognition service temporarily unavailable; try again shortly.',
				array( 'status' => 503 )
			);
		}

		if ( 'multipart' === $body_kind ) {
			if ( empty( $body ) || 'GET' === $method ) {
				$encoded_body = null;
			} else {
				$boundary     = $this->generate_multipart_boundary();
				$encoded_body = $this->build_multipart_body( $body, $boundary );
				// E15-11 BR-12: enforce the cap against the actual serialized
				// outgoing body size — multipart framing + per-part headers +
				// the JSON request envelope add bytes that the controller's
				// raw-bytes preflight cannot see, and the recognition
				// service's UploadSizeLimitMiddleware rejects on
				// Content-Length. Without this check a payload right under
				// the raw cap would still 413 server-side.
				$serialized_size = strlen( $encoded_body );
				if ( null !== $max_body_bytes && $serialized_size > $max_body_bytes ) {
					return new WP_Error(
						'multipart_payload_too_large',
						sprintf(
							'multipart upload serialized to %d bytes, exceeding the %d-byte cap (raw image bytes plus framing).',
							$serialized_size,
							$max_body_bytes
						),
						array( 'status' => 413 )
					);
				}
				$headers['Content-Type']   = 'multipart/form-data; boundary=' . $boundary;
				$headers['Content-Length'] = (string) $serialized_size;
			}
		} else {
			$encoded_body = ! empty( $body ) && 'GET' !== $method ? wp_json_encode( $body ) : null;
		}

		// BR-137: never-follow-redirects is enforced inside RecognitionTransport
		// (redirection => 0 is forced there). A 3xx would re-send X-API-Key to
		// whatever Location a compromised service advertises.
		$options = array(
			'headers' => $headers,
			'timeout' => $policy['timeout_seconds'],
			'body'    => $encoded_body,
		);

		$max_retries   = $policy['max_retries'];
		$base_delay_ms = $policy['base_delay_ms'];
		$last_error    = null;

		for ( $attempt = 0; $attempt < $max_retries; $attempt++ ) {
			$response = RecognitionTransport::request( $url, array_merge( $options, array( 'method' => $method ) ) );

			if ( is_wp_error( $response ) ) {
				$last_error = $response;
				$this->record_proxy_failure( $policy, $failure_key, $circuit_key );
				if ( $attempt < $max_retries - 1 ) {
					$delay_ms = $base_delay_ms * ( 2 ** $attempt ); // 500ms, 1000ms, 2000ms
					usleep( $delay_ms * 1000 );
					continue;
				}
				return $response;
			}

			$status = (int) wp_remote_retrieve_response_code( $response );
			// BR-137: with redirection=0 a 3xx is the raw response. Surface it
			// as an error so callers never treat an empty redirect body as OK.
			// Count toward the circuit breaker — a persistently-redirecting
			// (compromised) service must not stay invisible to backoff.
			if ( $status >= 300 && $status < 400 ) {
				$this->record_proxy_failure( $policy, $failure_key, $circuit_key );
				return new WP_Error(
					self::ERROR_CODE_REDIRECT_REFUSED,
					sprintf( 'Recognition service returned unexpected redirect (%d).', $status ),
					array( 'status' => 502 )
				);
			}

			if ( $status >= 500 ) {
				$this->record_proxy_failure( $policy, $failure_key, $circuit_key );
			}

			$response_headers = wp_remote_retrieve_headers( $response );
			if ( $status >= 500 && ! $this->is_backend_retry_after( $status, $response_headers ) && $attempt < $max_retries - 1 ) {
				$delay_ms = $base_delay_ms * ( 2 ** $attempt );
				usleep( $delay_ms * 1000 );
				continue;
			}

			if ( $status < 500 ) {
				$this->record_proxy_success( $policy, $failure_key, $circuit_key );
			}

			$response_body    = wp_remote_retrieve_body( $response );
			$decoded          = json_decode( $response_body, true );
			$rewritten_body   = BlobUrlRewriter::rewrite( $decoded );
			return new WP_REST_Response( $rewritten_body, $status, $this->normalize_response_headers( $response_headers ) );
		}

		return $last_error ?? new WP_Error( 'proxy_failed', 'Request failed after retries.', array( 'status' => 502 ) );
	}

	protected function get_tenant_id(): string {
		return TenantIdentity::resolve()['value'];
	}

	protected function get_recognition_base_url(): string {
		return $this->get_endpoint_resolver()->get_effective_base_url();
	}

	protected function get_recognition_source(): string {
		return $this->get_endpoint_resolver()->get_recognition_source();
	}

	protected function get_endpoint_resolver(): RecognitionEndpointResolver {
		if ( null === $this->endpoint_resolver ) {
			$this->endpoint_resolver = new RecognitionEndpointResolver();
		}

		return $this->endpoint_resolver;
	}

	protected function inject_endpoint_resolver( RecognitionEndpointResolver $endpoint_resolver ): void {
		$this->endpoint_resolver = $endpoint_resolver;
	}

	protected function get_recognition_api_key(): string {
		$constant_api_key = $this->get_recognition_api_key_from_constant();
		if ( '' !== $constant_api_key ) {
			return $constant_api_key;
		}

		$filter_api_key = trim( (string) apply_filters( 'acx_recognition_api_key', '' ) );
		if ( '' !== $filter_api_key ) {
			return $filter_api_key;
		}

		return trim( (string) get_option( 'acx_recognition_api_key', '' ) );
	}

	private function get_recognition_api_key_from_constant(): string {
		if ( defined( 'ACX_RECOGNITION_API_KEY' ) && is_string( ACX_RECOGNITION_API_KEY ) ) {
			return trim( ACX_RECOGNITION_API_KEY );
		}

		return '';
	}

	/**
	 * Determine if local projection should be used based on sync state.
	 *
	 * @param \AltContext\Sovereign\Repositories\SyncStateRepositoryInterface $sync_state_repository
	 * @param string $tenant_id
	 * @return bool
	 */
	protected function should_use_local_projection_gate( $sync_state_repository, string $tenant_id ): bool {
		$normalized = trim( $tenant_id );
		if ( '' === $normalized ) {
			return false;
		}

		$version = $sync_state_repository->get_snapshot_version( $normalized );
		$updated_at = $sync_state_repository->get_last_updated( $normalized );
		if ( $version > 0 || ( is_string( $updated_at ) && '' !== trim( $updated_at ) ) ) {
			return true;
		}

		return false;
	}

	protected function is_proxy_unavailable( WP_REST_Response|WP_Error $response ): bool {
		if ( is_wp_error( $response ) ) {
			return true;
		}

		return $response->get_status() >= 500;
	}

	/**
	 * Transport-unreachable: the backend could not be reached at all (DNS,
	 * connection, timeout). Honest provenance is UNAVAILABLE. Distinct from a
	 * reachable-but-erroring backend, which is_proxy_endpoint_error() classifies,
	 * and from a redirect refusal (backend answered 3xx; see
	 * is_proxy_redirect_refused()).
	 */
	protected function is_proxy_transport_unreachable( WP_REST_Response|WP_Error $response ): bool {
		return is_wp_error( $response ) && ! $this->is_proxy_redirect_refused( $response );
	}

	/**
	 * Redirect refused: the backend is reachable and answered with a 3xx that
	 * RecognitionTransport refused to follow. Not UNAVAILABLE — the endpoint is
	 * up; treat as endpoint error provenance for degraded UI paths.
	 *
	 * Recognises both the shared proxy code and the blob-specific refusal code
	 * so BlobsController (which extends this class) is not invisible to the
	 * shared degradation predicates (R6L-BR-04 / [sr-007]).
	 */
	protected function is_proxy_redirect_refused( WP_REST_Response|WP_Error $response ): bool {
		if ( ! is_wp_error( $response ) ) {
			return false;
		}

		$code = $response->get_error_code();

		return self::ERROR_CODE_REDIRECT_REFUSED === $code
			|| self::ERROR_CODE_BLOB_REDIRECT_REFUSED === $code;
	}

	/**
	 * Reachable-but-erroring: the backend answered with a 5xx (excluding the 503
	 * overload signal handled by is_backend_overloaded). Honest provenance is
	 * ENDPOINT_ERROR, not UNAVAILABLE — the endpoint is up but failing.
	 *
	 * Roster-candidates passes $min_status=400 so an upstream validate_top_k
	 * 400 is classified as an endpoint error instead of a mappable payload.
	 * Other routes keep the 5xx default and do not widen.
	 */
	protected function is_proxy_endpoint_error( WP_REST_Response|WP_Error $response, int $min_status = 500 ): bool {
		return ! is_wp_error( $response ) && $response->get_status() >= $min_status;
	}

	protected function is_backend_overloaded( WP_REST_Response|WP_Error $response ): bool {
		return ! is_wp_error( $response ) && 503 === $response->get_status();
	}

	protected function get_retry_after_seconds( WP_REST_Response|WP_Error $response ): ?int {
		if ( ! $response instanceof WP_REST_Response ) {
			return null;
		}

		$headers = $response->get_headers();
		$retry_after = $headers['Retry-After'] ?? $headers['retry-after'] ?? null;
		if ( is_string( $retry_after ) && '' !== trim( $retry_after ) && is_numeric( $retry_after ) ) {
			return max( 1, (int) $retry_after );
		}

		if ( is_int( $retry_after ) ) {
			return max( 1, $retry_after );
		}

		return null;
	}

	protected function backend_overloaded_response( WP_REST_Response|WP_Error $response ): WP_REST_Response {
		$retry_after = $this->get_retry_after_seconds( $response );
		$headers = array();
		if ( null !== $retry_after ) {
			$headers['Retry-After'] = (string) $retry_after;
		}

		$payload = array( 'error' => 'backend_overloaded' );
		if ( null !== $retry_after ) {
			$payload['retry_after'] = $retry_after;
		}

		return new WP_REST_Response( $payload, 503, $headers );
	}

	protected function is_projection_stale( ?string $updated_at ): bool {
		if ( ! is_string( $updated_at ) || '' === trim( $updated_at ) ) {
			return true;
		}

		$timestamp = strtotime( $updated_at );
		if ( false === $timestamp ) {
			return true;
		}

		$threshold = (int) apply_filters( 'acx_sync_stale_threshold_seconds', 3600 );
		$threshold = max( 60, $threshold );

		$age = max( 0, time() - $timestamp );

		return $age > $threshold;
	}

	/**
	 * E15-3a-BR-21 Slice 5: 503 + Retry-After is an explicit backend signal to
	 * back off. Short-circuit the retry loop instead of burning additional
	 * attempts against an already-overloaded backend. Other 5xx codes (502,
	 * 504) still retry, and 503 without Retry-After still retries.
	 *
	 * @param mixed $response_headers Case-insensitive header dictionary (array
	 *                                or Traversable) returned by wp_remote_retrieve_headers.
	 */
	private function is_backend_retry_after( int $status, mixed $response_headers ): bool {
		if ( 503 !== $status ) {
			return false;
		}

		$headers = array();
		if ( is_array( $response_headers ) ) {
			$headers = $response_headers;
		} elseif ( $response_headers instanceof Traversable ) {
			foreach ( $response_headers as $key => $value ) {
				$headers[ (string) $key ] = $value;
			}
		}

		foreach ( $headers as $key => $value ) {
			if ( 'retry-after' !== strtolower( trim( (string) $key ) ) ) {
				continue;
			}
			if ( is_int( $value ) ) {
				return true;
			}
			if ( is_string( $value ) && '' !== trim( $value ) ) {
				return true;
			}
		}

		return false;
	}

	protected function get_proxy_policy(): RecognitionProxyPolicy {
		if ( null === $this->proxy_policy ) {
			$this->proxy_policy = new RecognitionProxyPolicy();
		}

		return $this->proxy_policy;
	}

	/**
	 * @return array<string,string>
	 */
	private function normalize_response_headers( mixed $response_headers ): array {
		$allowed_headers = array(
			'retry-after' => 'Retry-After',
		);

		if ( is_array( $response_headers ) ) {
			return $this->filter_forwarded_response_headers( $response_headers, $allowed_headers );
		}

		if ( $response_headers instanceof Traversable ) {
			$normalized = array();
			foreach ( $response_headers as $key => $value ) {
				$normalized[ (string) $key ] = $value;
			}

			return $this->filter_forwarded_response_headers( $normalized, $allowed_headers );
		}

		return array();
	}

	/**
	 * @param array<string,mixed> $response_headers
	 * @param array<string,string> $allowed_headers
	 * @return array<string,string>
	 */
	private function filter_forwarded_response_headers( array $response_headers, array $allowed_headers ): array {
		$normalized = array();
		foreach ( $response_headers as $key => $value ) {
			$lookup = strtolower( trim( (string) $key ) );
			if ( '' === $lookup || ! isset( $allowed_headers[ $lookup ] ) ) {
				continue;
			}

			$normalized[ $allowed_headers[ $lookup ] ] = (string) $value;
		}

		return $normalized;
	}

	private function build_circuit_breaker_key( string $base_url ): string {
		return RecognitionCircuitKeys::for_base_url( $base_url );
	}

	/**
	 * @param array{timeout_seconds:int,max_retries:int,base_delay_ms:int,circuit_enabled:bool} $policy
	 */
	private function record_proxy_failure( array $policy, string $failure_key, string $circuit_key ): void {
		if ( ! $policy['circuit_enabled'] ) {
			return;
		}

		$failures = $this->increment_failure_counter( $failure_key );

		$threshold = (int) apply_filters( 'acx_proxy_circuit_failure_threshold', 2 );
		$threshold = max( 1, $threshold );
		if ( $failures < $threshold ) {
			return;
		}

		$open_seconds = (int) apply_filters( 'acx_proxy_circuit_open_seconds', 60 );
		$open_seconds = max( 10, $open_seconds );
		set_transient( $circuit_key, 1, $open_seconds );
	}

	/**
	 * Atomically increment the per-backend failure counter and return the new
	 * total (CON-5).
	 *
	 * The previous get_transient/++/set_transient was a non-atomic
	 * read-modify-write: two requests failing in the same window both read N
	 * and both write N+1, losing one increment and delaying the breaker trip by
	 * a cycle. Serializing the RMW under a short-lived MySQL named lock makes
	 * concurrent failures accumulate so the breaker trips deterministically at
	 * the threshold. GET_LOCK is connection-scoped and works regardless of
	 * whether transients live in a persistent object cache or the options
	 * table, so it is the deployment-agnostic choice over wp_cache_incr (which
	 * only counts per-request without a persistent object cache).
	 *
	 * The lock is best-effort: if it cannot be acquired (timeout) or $wpdb is
	 * unavailable, the increment still runs unguarded so behaviour never
	 * degrades below the pre-CON-5 baseline. Two cases keep the guarantee a
	 * ceiling rather than an absolute: a GET_LOCK timeout falls through to the
	 * unguarded RMW, and on DB-split deployments (HyperDB/LudicrousDB) the
	 * GET_LOCK SELECT may route to a replica while the transient write lands on
	 * the master, so the lock can guard a different connection than the
	 * mutation. Both are tolerable here — the critical section is two
	 * sub-millisecond transient ops against a 1s lock timeout, so the realistic
	 * contended path acquires the lock rather than timing out.
	 */
	private function increment_failure_counter( string $failure_key ): int {
		$lock_name = 'acx_cb_' . md5( $failure_key );
		$locked    = $this->acquire_named_lock( $lock_name );

		try {
			$failures = (int) get_transient( $failure_key );
			++$failures;
			set_transient( $failure_key, $failures, 300 );

			return $failures;
		} finally {
			if ( $locked ) {
				$this->release_named_lock( $lock_name );
			}
		}
	}

	private function acquire_named_lock( string $lock_name ): bool {
		global $wpdb;
		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return false;
		}

		$timeout = (int) apply_filters( 'acx_proxy_circuit_lock_timeout_seconds', 1 );
		$timeout = max( 0, $timeout );

		$acquired = $wpdb->get_var( $wpdb->prepare( 'SELECT GET_LOCK(%s, %d)', $lock_name, $timeout ) );

		return '1' === (string) $acquired;
	}

	private function release_named_lock( string $lock_name ): void {
		global $wpdb;
		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return;
		}

		$wpdb->get_var( $wpdb->prepare( 'SELECT RELEASE_LOCK(%s)', $lock_name ) );
	}

	/**
	 * @param array{timeout_seconds:int,max_retries:int,base_delay_ms:int,circuit_enabled:bool} $policy
	 */
	private function record_proxy_success( array $policy, string $failure_key, string $circuit_key ): void {
		if ( ! $policy['circuit_enabled'] ) {
			return;
		}

		delete_transient( $failure_key );
		delete_transient( $circuit_key );
	}

	/**
	 * Generate a unique boundary string for a multipart/form-data body
	 * (E15-11 BR-09).
	 *
	 * Boundaries are restricted to RFC 2046 token characters; we use a
	 * fixed prefix plus a random hex tail so the boundary is highly
	 * unlikely to collide with body bytes.
	 */
	private function generate_multipart_boundary(): string {
		// 32 hex chars (16 random bytes) is plenty of entropy.
		try {
			$random = bin2hex( random_bytes( 16 ) );
		} catch ( \Exception $e ) {
			// random_bytes can throw on extremely broken environments; fall
			// back to a time + uniqid mix so we never block a request on
			// crypto entropy issues.
			$random = bin2hex( pack( 'NN', time(), random_int( 0, PHP_INT_MAX ) ) );
		}
		return 'AcxBoundary' . $random;
	}

	/**
	 * Serialize an associative array of form fields and file uploads into a
	 * multipart/form-data body string with the given boundary
	 * (E15-11 BR-09).
	 *
	 * Each entry in $body may be:
	 *   - a scalar (string|int|float|bool) -> emitted as a plain form field
	 *   - an array with keys {filename, content, content_type} -> emitted
	 *     as a file upload part with the given filename and Content-Type
	 *
	 * Other shapes (nested arrays without the file keys, objects) are
	 * rejected by string-cast to avoid silently dropping caller data.
	 *
	 * @param array<string, mixed> $body     Form fields keyed by name.
	 * @param string               $boundary Boundary token (no leading dashes).
	 */
	private function build_multipart_body( array $body, string $boundary ): string {
		$crlf  = "\r\n";
		$parts = '';
		foreach ( $body as $name => $value ) {
			$name_str = (string) $name;
			$parts   .= '--' . $boundary . $crlf;

			if ( is_array( $value ) && isset( $value['content'] ) ) {
				$filename     = isset( $value['filename'] ) ? (string) $value['filename'] : $name_str;
				$content_type = isset( $value['content_type'] ) ? (string) $value['content_type'] : 'application/octet-stream';
				$content      = (string) $value['content'];
				$parts       .= 'Content-Disposition: form-data; name="' . $name_str . '"; filename="' . $filename . '"' . $crlf;
				$parts       .= 'Content-Type: ' . $content_type . $crlf;
				$parts       .= $crlf;
				$parts       .= $content . $crlf;
				continue;
			}

			$parts .= 'Content-Disposition: form-data; name="' . $name_str . '"' . $crlf;
			$parts .= $crlf;
			$parts .= (string) $value . $crlf;
		}
		$parts .= '--' . $boundary . '--' . $crlf;
		return $parts;
	}
}
