<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-probe-outcome.php';
require_once __DIR__ . '/class-tenant-identity.php';

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;
use function apply_filters;
use function current_user_can;
use function defined;
use function get_option;
use function intval;
use function is_array;
use function is_string;
use function is_wp_error;
use function json_decode;
use function register_rest_route;
use function rtrim;
use function stripos;
use function substr;
use function trim;
use function update_option;
use function wp_remote_get;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_headers;
use function wp_remote_retrieve_response_code;

/**
 * REST controller for recognition API configuration.
 *
 * GET  /acx/v1/settings          — read current config with source detection
 * POST /acx/v1/settings          — save URL and/or API key to WP options
 * POST /acx/v1/settings/test     — probe the authenticated recognition pool
 *                                  endpoint and classify the response into one
 *                                  of ten canonical {@see ProbeOutcome} codes
 */
class SettingsController {

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/settings',
			array(
				array(
					'methods'             => 'GET',
					'callback'            => array( $this, 'get_settings' ),
					'permission_callback' => array( $this, 'can_manage_settings' ),
				),
				array(
					'methods'             => 'POST',
					'callback'            => array( $this, 'save_settings' ),
					'permission_callback' => array( $this, 'can_manage_settings' ),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/settings/test',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'test_connection' ),
				'permission_callback' => array( $this, 'can_manage_settings' ),
			)
		);
	}

	public function can_manage_settings(): bool {
		return current_user_can( 'manage_options' );
	}

	public function get_settings( WP_REST_Request $request ): WP_REST_Response {
		$url_resolution = $this->resolve_url_source();
		$key_resolution = $this->resolve_key_source();
		$source_resolution = $this->resolve_recognition_source( $url_resolution );

		return new WP_REST_Response(
			array(
				'url'                       => $url_resolution['value'],
				'url_source'                => $url_resolution['source'],
				'recognition_source'        => $source_resolution['value'],
				'recognition_source_source' => $source_resolution['source'],
				'api_key_set'               => '' !== $key_resolution['value'],
				'api_key_last4'             => $this->mask_key( $key_resolution['value'] ),
				'key_source'                => $key_resolution['source'],
			),
			200
		);
	}

	public function save_settings( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$body = $request->get_json_params();
		$saved = array();

		if ( isset( $body['url'] ) && is_string( $body['url'] ) ) {
			$url = trim( $body['url'] );
			if ( '' !== $url && ! $this->is_valid_url( $url ) ) {
				return new WP_Error(
					'invalid_url',
					'The recognition API URL must be a valid HTTP or HTTPS URL.',
					array( 'status' => 400 )
				);
			}
			update_option( 'acx_recognition_url', $url );
			$saved[] = 'url';
		}

		if ( isset( $body['recognition_source'] ) && is_string( $body['recognition_source'] ) ) {
			$recognition_source = trim( $body['recognition_source'] );
			if ( ! $this->is_valid_recognition_source( $recognition_source ) ) {
				return new WP_Error(
					'invalid_recognition_source',
					'Recognition source must be either service or local.',
					array( 'status' => 400 )
				);
			}
			update_option( 'acx_recognition_source', $recognition_source );
			$saved[] = 'recognition_source';
		}

		if ( isset( $body['api_key'] ) && is_string( $body['api_key'] ) ) {
			$key = trim( $body['api_key'] );
			update_option( 'acx_recognition_api_key', $key );
			$saved[] = 'api_key';
		}

		return new WP_REST_Response(
			array(
				'saved'  => $saved,
				'result' => 'ok',
			),
			200
		);
	}

	public function test_connection( WP_REST_Request $request ): WP_REST_Response {
		$url_resolution = $this->resolve_url_source();
		$url            = $url_resolution['value'];

		if ( '' === $url ) {
			return new WP_REST_Response(
				array( 'outcome' => ProbeOutcome::NOT_CONFIGURED ),
				200
			);
		}

		$key_resolution = $this->resolve_key_source();
		$headers        = array(
			'X-Tenant-ID' => TenantIdentity::derive_from_site_url(),
		);
		if ( '' !== $key_resolution['value'] ) {
			$headers['X-API-Key'] = $key_resolution['value'];
		}

		$health_url = rtrim( $url, '/' ) . '/health/detailed';
		$response   = wp_remote_get(
			$health_url,
			array(
				'headers' => $headers,
				'timeout' => 10,
			)
		);

		return new WP_REST_Response( $this->build_probe_payload( $response ), 200 );
	}

	/**
	 * Build the full /settings/test response payload from the raw wp_remote_get
	 * result. The wire contract is `{outcome, status_code?, retry_after_seconds?,
	 * detail?, body?}`. Consumers derive a boolean "connected" from
	 * `outcome === 'connected'`; the controller never emits that field itself.
	 *
	 * @param WP_Error|array<string, mixed> $response
	 * @return array<string, mixed>
	 */
	private function build_probe_payload( WP_Error|array $response ): array {
		if ( is_wp_error( $response ) ) {
			$message = (string) $response->get_error_message();
			$outcome = $this->is_tls_failure( $message )
				? ProbeOutcome::TLS_ERROR
				: ProbeOutcome::NETWORK_ERROR;
			$payload = array( 'outcome' => $outcome );
			if ( '' !== $message ) {
				$payload['detail'] = $message;
			}
			return $payload;
		}

		$status_code = (int) wp_remote_retrieve_response_code( $response );
		$body        = wp_remote_retrieve_body( $response );
		$decoded     = json_decode( $body, true );
		$detail      = is_array( $decoded ) && isset( $decoded['detail'] ) && is_string( $decoded['detail'] )
			? $decoded['detail']
			: null;

		$outcome = $this->classify_http_status( $status_code, $detail );
		$payload = array(
			'outcome'     => $outcome,
			'status_code' => $status_code,
			'body'        => null !== $decoded ? $decoded : $body,
		);
		if ( null !== $detail ) {
			$payload['detail'] = $detail;
		}
		if ( ProbeOutcome::RATE_LIMITED === $outcome ) {
			$retry_after = $this->parse_retry_after( $this->retrieve_retry_after_header( $response ) );
			if ( null !== $retry_after ) {
				$payload['retry_after_seconds'] = $retry_after;
			}
		}
		return $payload;
	}

	/**
	 * @param array<string, mixed> $response
	 */
	private function retrieve_retry_after_header( array $response ): mixed {
		$headers = wp_remote_retrieve_headers( $response );
		if ( is_array( $headers ) ) {
			return $headers['Retry-After']
				?? $headers['retry-after']
				?? null;
		}
		if ( $headers instanceof \ArrayAccess ) {
			if ( isset( $headers['Retry-After'] ) ) {
				return $headers['Retry-After'];
			}
			if ( isset( $headers['retry-after'] ) ) {
				return $headers['retry-after'];
			}
		}
		return null;
	}

	private function classify_http_status( int $status_code, ?string $detail ): string {
		if ( $status_code >= 200 && $status_code < 300 ) {
			return ProbeOutcome::CONNECTED;
		}
		if ( 401 === $status_code ) {
			if ( 'api key expired' === $detail ) {
				return ProbeOutcome::EXPIRED;
			}
			if ( 'api key revoked' === $detail ) {
				return ProbeOutcome::REVOKED;
			}
			return ProbeOutcome::INVALID_KEY;
		}
		if ( 403 === $status_code ) {
			if ( 'tenant mismatch' === $detail ) {
				return ProbeOutcome::TENANT_MISMATCH;
			}
			return ProbeOutcome::INVALID_KEY;
		}
		if ( 429 === $status_code ) {
			return ProbeOutcome::RATE_LIMITED;
		}
		if ( $status_code >= 500 ) {
			return ProbeOutcome::SERVER_ERROR;
		}
		return ProbeOutcome::SERVER_ERROR;
	}

	private function is_tls_failure( string $message ): bool {
		if ( '' === $message ) {
			return false;
		}
		foreach ( array( 'certificate', 'SSL', 'TLS' ) as $keyword ) {
			if ( false !== stripos( $message, $keyword ) ) {
				return true;
			}
		}
		return false;
	}

	/**
	 * Parse a Retry-After header value, treating it as integer delta-seconds
	 * per RFC 7231 §7.1.3 — the form emitted by the recognition service's
	 * enforce_rate_limit dependency (E15-1 Slice 1). HTTP-date form is not
	 * supported; a non-numeric value falls back to null and the UI renders a
	 * generic "wait a few seconds" hint.
	 */
	private function parse_retry_after( mixed $raw ): ?int {
		if ( is_array( $raw ) ) {
			$raw = $raw[0] ?? null;
		}
		if ( ! is_string( $raw ) ) {
			return null;
		}
		$trimmed = trim( $raw );
		if ( '' === $trimmed ) {
			return null;
		}
		$parsed = intval( $trimmed );
		if ( $parsed <= 0 ) {
			return null;
		}
		return $parsed;
	}

	/**
	 * Resolve the recognition URL and its source using the same priority chain
	 * as class-abstract-recognition-proxy-controller.php.
	 *
	 * @return array{value: string, source: string}
	 */
	private function resolve_url_source(): array {
		// E15-12-BR-07: code-managed sources (constant, filter) MUST win over
		// operator-saved options. The pre-fix order resolved option before
		// filter, which let a stale saved URL keep routing recognition traffic
		// even after an operator wired a filter to point at a new environment,
		// and surfaced the selector as option-owned/editable instead of
		// code-managed/read-only. Precedence is now: constant -> filter ->
		// option -> default, matching the proxy runtime resolver.
		$constant = $this->get_constant_value( 'ACX_RECOGNITION_URL' );
		if ( '' !== $constant ) {
			return array( 'value' => $constant, 'source' => 'constant' );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_base_url', '' ) );
		if ( '' !== $filter && $this->is_valid_url( $filter ) ) {
			return array( 'value' => $filter, 'source' => 'filter' );
		}

		$option = trim( (string) get_option( 'acx_recognition_url', '' ) );
		if ( '' !== $option && $this->is_valid_url( $option ) ) {
			return array( 'value' => $option, 'source' => 'option' );
		}

		return array( 'value' => '', 'source' => 'default' );
	}

	/**
	 * Resolve the recognition API key and its source.
	 *
	 * @return array{value: string, source: string}
	 */
	private function resolve_key_source(): array {
		$constant = $this->get_constant_value( 'ACX_RECOGNITION_API_KEY' );
		if ( '' !== $constant ) {
			return array( 'value' => $constant, 'source' => 'constant' );
		}

		$option = trim( (string) get_option( 'acx_recognition_api_key', '' ) );
		if ( '' !== $option ) {
			return array( 'value' => $option, 'source' => 'option' );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_api_key', '' ) );
		if ( '' !== $filter ) {
			return array( 'value' => $filter, 'source' => 'filter' );
		}

		return array( 'value' => '', 'source' => 'default' );
	}

	/**
	 * @param array{value: string, source: string} $url_resolution
	 * @return array{value: string, source: string}
	 */
	private function resolve_recognition_source( array $url_resolution ): array {
		$constant = trim( $this->get_constant_value( 'ACX_RECOGNITION_SOURCE' ) );
		if ( $this->is_valid_recognition_source( $constant ) ) {
			return array( 'value' => $constant, 'source' => 'constant' );
		}

		if ( '' !== $url_resolution['value'] && in_array( $url_resolution['source'], array( 'constant', 'filter' ), true ) ) {
			return array( 'value' => 'service', 'source' => $url_resolution['source'] );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_source', '' ) );
		if ( $this->is_valid_recognition_source( $filter ) ) {
			return array( 'value' => $filter, 'source' => 'filter' );
		}

		$option = trim( (string) get_option( 'acx_recognition_source', '' ) );
		if ( $this->is_valid_recognition_source( $option ) ) {
			return array( 'value' => $option, 'source' => 'option' );
		}

		if ( '' !== $url_resolution['value'] ) {
			return array( 'value' => 'service', 'source' => 'option' === $url_resolution['source'] ? 'option' : 'default' );
		}

		return array( 'value' => 'local', 'source' => 'default' );
	}

	private function get_constant_value( string $name ): string {
		if ( defined( $name ) && is_string( constant( $name ) ) ) {
			return trim( constant( $name ) );
		}
		return '';
	}

	private function mask_key( string $key ): string {
		if ( strlen( $key ) <= 4 ) {
			return '' === $key ? '' : '****';
		}
		return '****' . substr( $key, -4 );
	}

	private function is_valid_url( string $url ): bool {
		$parts = parse_url( $url );
		if ( false === $parts || ! is_array( $parts ) ) {
			return false;
		}
		return isset( $parts['scheme'], $parts['host'] ) && in_array( $parts['scheme'], array( 'http', 'https' ), true );
	}

	private function is_valid_recognition_source( string $source ): bool {
		return in_array( $source, array( 'service', 'local' ), true );
	}
}
