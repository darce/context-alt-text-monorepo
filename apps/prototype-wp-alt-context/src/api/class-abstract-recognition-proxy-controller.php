<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-recognition-proxy-policy.php';
require_once __DIR__ . '/class-tenant-identity.php';
require_once __DIR__ . '/class-blob-url-rewriter.php';

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
use function parse_url;
use function set_transient;
use function strtotime;
use function strtolower;
use function time;
use function untrailingslashit;
use function wp_json_encode;
use function wp_remote_request;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_headers;
use function wp_remote_retrieve_response_code;
use function trim;

abstract class AbstractRecognitionProxyController implements RecognitionRouteControllerInterface {
	private ?RecognitionProxyPolicy $proxy_policy = null;

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
		$failure_key = $circuit_key . '_failures';

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

		$options = array(
			'headers' => $headers,
			'timeout' => $policy['timeout_seconds'],
			'body'    => $encoded_body,
		);

		$max_retries   = $policy['max_retries'];
		$base_delay_ms = $policy['base_delay_ms'];
		$last_error    = null;

		for ( $attempt = 0; $attempt < $max_retries; $attempt++ ) {
			$response = wp_remote_request( $url, array_merge( $options, array( 'method' => $method ) ) );

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

			$status = wp_remote_retrieve_response_code( $response );
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
		return TenantIdentity::derive_from_site_url();
	}

	protected function get_recognition_base_url(): string {
		if ( 'local' === $this->get_recognition_source() ) {
			return 'http://localhost:8000';
		}

		$candidates = array(
			$this->get_recognition_base_url_from_constant(),
			trim( (string) get_option( 'acx_recognition_url', '' ) ),
			trim( (string) apply_filters( 'acx_recognition_base_url', '' ) ),
		);

		foreach ( $candidates as $candidate ) {
			if ( $this->is_valid_recognition_base_url( $candidate ) ) {
				return $candidate;
			}
		}

		return 'http://localhost:8000';
	}

	protected function get_recognition_source(): string {
		$constant_source = $this->get_recognition_source_from_constant();
		if ( '' !== $constant_source ) {
			return $constant_source;
		}

		$constant_url = $this->get_recognition_base_url_from_constant();
		if ( $this->is_valid_recognition_base_url( $constant_url ) ) {
			return 'service';
		}

		$filter_url = trim( (string) apply_filters( 'acx_recognition_base_url', '' ) );
		if ( $this->is_valid_recognition_base_url( $filter_url ) ) {
			return 'service';
		}

		$filter_source = trim( (string) apply_filters( 'acx_recognition_source', '' ) );
		if ( $this->is_valid_recognition_source( $filter_source ) ) {
			return $filter_source;
		}

		$option_source = trim( (string) get_option( 'acx_recognition_source', '' ) );
		if ( $this->is_valid_recognition_source( $option_source ) ) {
			return $option_source;
		}

		$option_url = trim( (string) get_option( 'acx_recognition_url', '' ) );
		if ( $this->is_valid_recognition_base_url( $option_url ) ) {
			return 'service';
		}

		return 'local';
	}

	protected function get_recognition_api_key(): string {
		$constant_api_key = $this->get_recognition_api_key_from_constant();
		if ( '' !== $constant_api_key ) {
			return $constant_api_key;
		}

		$option_api_key = trim( (string) get_option( 'acx_recognition_api_key', '' ) );
		if ( '' !== $option_api_key ) {
			return $option_api_key;
		}

		return trim( (string) apply_filters( 'acx_recognition_api_key', '' ) );
	}

	private function get_recognition_base_url_from_constant(): string {
		if ( defined( 'ACX_RECOGNITION_URL' ) && is_string( ACX_RECOGNITION_URL ) ) {
			return trim( ACX_RECOGNITION_URL );
		}

		return '';
	}

	private function get_recognition_api_key_from_constant(): string {
		if ( defined( 'ACX_RECOGNITION_API_KEY' ) && is_string( ACX_RECOGNITION_API_KEY ) ) {
			return trim( ACX_RECOGNITION_API_KEY );
		}

		return '';
	}

	private function get_recognition_source_from_constant(): string {
		if ( defined( 'ACX_RECOGNITION_SOURCE' ) && is_string( ACX_RECOGNITION_SOURCE ) ) {
			$source = trim( ACX_RECOGNITION_SOURCE );
			if ( $this->is_valid_recognition_source( $source ) ) {
				return $source;
			}
		}

		return '';
	}

	private function is_valid_recognition_base_url( string $candidate ): bool {
		if ( '' === $candidate ) {
			return false;
		}

		$parts = parse_url( $candidate );
		if ( false === $parts || ! is_array( $parts ) ) {
			return false;
		}

		$scheme = strtolower( (string) ( $parts['scheme'] ?? '' ) );
		$host   = (string) ( $parts['host'] ?? '' );

		return in_array( $scheme, array( 'http', 'https' ), true ) && '' !== $host;
	}

	private function is_valid_recognition_source( string $source ): bool {
		return in_array( $source, array( 'service', 'local' ), true );
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
		return 'acx_recognition_circuit_' . md5( strtolower( trim( $base_url ) ) );
	}

	/**
	 * @param array{timeout_seconds:int,max_retries:int,base_delay_ms:int,circuit_enabled:bool} $policy
	 */
	private function record_proxy_failure( array $policy, string $failure_key, string $circuit_key ): void {
		if ( ! $policy['circuit_enabled'] ) {
			return;
		}

		$failures = (int) get_transient( $failure_key );
		$failures++;
		set_transient( $failure_key, $failures, 300 );

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
