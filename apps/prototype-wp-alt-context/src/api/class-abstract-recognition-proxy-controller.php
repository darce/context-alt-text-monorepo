<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Response;

use function apply_filters;
use function add_query_arg;
use function current_user_can;
use function delete_transient;
use function esc_url_raw;
use function get_transient;
use function get_option;
use function get_site_url;
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
use function wp_remote_retrieve_response_code;
use function trim;

abstract class AbstractRecognitionProxyController implements RecognitionRouteControllerInterface {
	public function can_manage_recognition(): bool {
		return current_user_can( 'manage_options' );
	}

	protected function proxy_request(
		string $method,
		string $path,
		array $body = array(),
		array $query = array(),
		string $request_class = 'auto'
	): WP_REST_Response|WP_Error {
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
			'Content-Type' => 'application/json',
			'X-Tenant-ID'  => $this->get_tenant_id(),
		);

		$api_key = $this->get_recognition_api_key();
		if ( '' !== $api_key ) {
			$headers['X-API-Key'] = $api_key;
		}

		$policy = $this->resolve_request_policy( $method, $request_class );
		$circuit_key = $this->build_circuit_breaker_key( $base_url );
		$failure_key = $circuit_key . '_failures';

		if ( $policy['circuit_enabled'] && false !== get_transient( $circuit_key ) ) {
			return new WP_Error(
				'recognition_circuit_open',
				'Recognition service temporarily unavailable; try again shortly.',
				array( 'status' => 503 )
			);
		}

		$options = array(
			'headers' => $headers,
			'timeout' => $policy['timeout_seconds'],
			'body'    => ! empty( $body ) && 'GET' !== $method ? wp_json_encode( $body ) : null,
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

			if ( $status >= 500 && $attempt < $max_retries - 1 ) {
				$delay_ms = $base_delay_ms * ( 2 ** $attempt );
				usleep( $delay_ms * 1000 );
				continue;
			}

			if ( $status < 500 ) {
				$this->record_proxy_success( $policy, $failure_key, $circuit_key );
			}

			$response_body = wp_remote_retrieve_body( $response );
			return new WP_REST_Response( json_decode( $response_body, true ), $status );
		}

		return $last_error ?? new WP_Error( 'proxy_failed', 'Request failed after retries.', array( 'status' => 502 ) );
	}

	protected function get_tenant_id(): string {
		return md5( (string) get_site_url() );
	}

	protected function get_recognition_base_url(): string {
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
	 * @return array{timeout_seconds:int,max_retries:int,base_delay_ms:int,circuit_enabled:bool}
	 */
	private function resolve_request_policy( string $method, string $request_class ): array {
		$normalized_class = trim( strtolower( $request_class ) );
		if ( 'auto' === $normalized_class ) {
			$normalized_class = 'GET' === strtoupper( $method ) ? 'ui_read' : 'mutation';
		}

		if ( 'background_sync' === $normalized_class ) {
			return array(
				'timeout_seconds' => (int) apply_filters( 'acx_proxy_timeout_background_sync_seconds', 30 ),
				'max_retries' => (int) apply_filters( 'acx_proxy_max_retries_background_sync', 3 ),
				'base_delay_ms' => (int) apply_filters( 'acx_proxy_backoff_base_ms_background_sync', 500 ),
				'circuit_enabled' => false,
			);
		}

		if ( 'ui_read' === $normalized_class ) {
			return array(
				'timeout_seconds' => (int) apply_filters( 'acx_proxy_timeout_ui_read_seconds', 2 ),
				'max_retries' => (int) apply_filters( 'acx_proxy_max_retries_ui_read', 1 ),
				'base_delay_ms' => (int) apply_filters( 'acx_proxy_backoff_base_ms_ui_read', 0 ),
				'circuit_enabled' => true,
			);
		}

		if ( 'post_scan_read' === $normalized_class ) {
			return array(
				'timeout_seconds' => (int) apply_filters( 'acx_proxy_timeout_post_scan_read_seconds', 10 ),
				'max_retries' => (int) apply_filters( 'acx_proxy_max_retries_post_scan_read', 1 ),
				'base_delay_ms' => (int) apply_filters( 'acx_proxy_backoff_base_ms_post_scan_read', 0 ),
				'circuit_enabled' => false,
			);
		}

		return array(
			'timeout_seconds' => (int) apply_filters( 'acx_proxy_timeout_mutation_seconds', 60 ),
			'max_retries' => (int) apply_filters( 'acx_proxy_max_retries_mutation', 3 ),
			'base_delay_ms' => (int) apply_filters( 'acx_proxy_backoff_base_ms_mutation', 500 ),
			'circuit_enabled' => false,
		);
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
}
