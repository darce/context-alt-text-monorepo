<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function array_key_exists;
use function gmdate;
use function in_array;
use function is_array;
use function is_int;
use function is_object;
use function is_string;
use function is_wp_error;
use function register_rest_route;
use function str_contains;
use function strtolower;
use function wp_get_current_user;

/**
 * REST proxy for operator GPU lifecycle control.
 */
class GpuControlController extends AbstractRecognitionProxyController {
	public const ERROR_CODE_UNAVAILABLE = 'gpu_status_unavailable';

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/gpu/status',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_status' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/gpu/intent',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'post_intent' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function get_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$response = $this->proxy_request(
			'GET',
			'/scene/gpu/status',
			array(),
			array(),
			'post_scan_read'
		);

		return $this->map_transport_failure( $response );
	}

	public function post_intent( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$body = $request->get_json_params();
		if ( ! is_array( $body ) ) {
			$body = $request->get_body_params();
		}

		if (
			! array_key_exists( 'action', $body )
			|| ! is_string( $body['action'] )
			|| ! in_array( $body['action'], array( 'start', 'stop', 'auto' ), true )
		) {
			return new WP_Error(
				'gpu_invalid_action',
				"action must be one of 'start', 'stop', or 'auto'.",
				array( 'status' => 400 )
			);
		}

		if ( array_key_exists( 'ttl_seconds', $body ) && ! is_int( $body['ttl_seconds'] ) ) {
			return new WP_Error(
				'gpu_invalid_ttl_seconds',
				'ttl_seconds must be an integer.',
				array( 'status' => 400 )
			);
		}

		$current_user = wp_get_current_user();
		$body['requested_by'] = is_object( $current_user ) && isset( $current_user->user_login )
			? (string) $current_user->user_login
			: '';

		$response = $this->proxy_request(
			'POST',
			'/scene/gpu/intent',
			$body,
			array(),
			'post_scan_read'
		);

		return $this->map_transport_failure( $response );
	}

	private function map_transport_failure( WP_REST_Response|WP_Error $response ): WP_REST_Response|WP_Error {
		if ( $response instanceof WP_REST_Response ) {
			if ( $response->get_status() < 500 ) {
				return $response;
			}

			$data = $response->get_data();
			if ( ! is_array( $data ) ) {
				return $response;
			}

			$data['unavailable'] = $this->build_unavailable_envelope( $response, 'scene' );

			return new WP_REST_Response( $data, $response->get_status(), $response->get_headers() );
		}

		$proxy_status = $this->proxy_http_status( $response );

		return new WP_Error(
			self::ERROR_CODE_UNAVAILABLE,
			'GPU control is unavailable.',
			array(
				'status'      => $proxy_status ?? 502,
				'unavailable' => $this->build_unavailable_envelope( $response, 'scene' ),
			)
		);
	}

	/**
	 * @return array{
	 *   reason: string,
	 *   service: string,
	 *   http_status: int|null,
	 *   retry_after_seconds: int|null,
	 *   checked_at: string
	 * }
	 */
	private function build_unavailable_envelope( WP_REST_Response|WP_Error $response, string $service, bool $contract_mismatch = false ): array {
		return array(
			'reason'               => $this->map_unavailable_reason( $response, $contract_mismatch ),
			'service'              => $service,
			'http_status'          => $this->proxy_http_status( $response ),
			'retry_after_seconds'  => $this->unavailable_retry_after_seconds( $response ),
			'checked_at'           => gmdate( 'Y-m-d\TH:i:s\Z' ),
		);
	}

	private function map_unavailable_reason( WP_REST_Response|WP_Error $response, bool $contract_mismatch ): string {
		if ( $contract_mismatch ) {
			return 'contract_mismatch';
		}

		if ( is_wp_error( $response ) ) {
			$code = $response->get_error_code();
			if ( 'recognition_not_configured' === $code ) {
				return 'not_configured';
			}
			if ( 'recognition_api_key_missing' === $code ) {
				return 'api_key_missing';
			}
			if ( 'recognition_circuit_open' === $code ) {
				return 'circuit_open';
			}
			if ( $this->is_timeout_proxy_error( $response ) ) {
				return 'timeout';
			}
		}

		$status = $this->proxy_http_status( $response );
		if ( null !== $status && $status >= 400 && $status < 500 ) {
			return 'upstream_4xx';
		}

		return 'upstream_5xx';
	}

	private function proxy_http_status( WP_REST_Response|WP_Error $response ): ?int {
		if ( $response instanceof WP_REST_Response ) {
			$status = $response->get_status();

			return $status > 0 ? $status : null;
		}

		$data = $response->get_error_data();
		if ( ! is_array( $data ) ) {
			return null;
		}

		$status = $data['status'] ?? $data['http_status'] ?? null;
		if ( is_int( $status ) && $status > 0 ) {
			return $status;
		}

		return null;
	}

	private function unavailable_retry_after_seconds( WP_REST_Response|WP_Error $response ): ?int {
		if ( $response instanceof WP_REST_Response ) {
			return $this->get_retry_after_seconds( $response );
		}

		$data = $response->get_error_data();
		if ( ! is_array( $data ) ) {
			return null;
		}

		$raw = $data['retry_after_seconds'] ?? $data['retry_after'] ?? null;
		if ( is_int( $raw ) && $raw > 0 ) {
			return $raw;
		}

		return null;
	}

	private function is_timeout_proxy_error( WP_Error $response ): bool {
		$code = strtolower( $response->get_error_code() );
		if ( str_contains( $code, 'timeout' ) || str_contains( $code, 'timed_out' ) ) {
			return true;
		}

		$message = strtolower( $response->get_error_message() );

		return str_contains( $message, 'timed out' ) || str_contains( $message, 'timeout' );
	}
}
