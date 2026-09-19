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
use function is_bool;
use function is_float;
use function is_int;
use function is_object;
use function is_string;
use function is_wp_error;
use function register_rest_route;
use function str_contains;
use function strlen;
use function strtolower;
use function substr;
use function wp_get_current_user;

/**
 * REST proxy for operator GPU lifecycle control.
 */
class GpuControlController extends AbstractRecognitionProxyController {
	public const ERROR_CODE_UNAVAILABLE = 'gpu_status_unavailable';

	/**
	 * Documented GPU intent/status client errors the SPA already handles.
	 * 401 = require_auth / require_write_access; 403 = gpu_control_forbidden;
	 * 422 = request validation. 404/409 are not GPU-intent contract statuses.
	 *
	 * @var array<int, int>
	 */
	private const GPU_INTENT_CONTRACT_PASSTHROUGH_STATUSES = array( 401, 403, 422 );

	private const UPSTREAM_MESSAGE_MAX_LENGTH = 300;

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

		// GpuIntentRequest forbids extra keys; the service derives requested_by from the API key.
		$intent = array( 'action' => $body['action'] );
		if ( array_key_exists( 'ttl_seconds', $body ) ) {
			$intent['ttl_seconds'] = $body['ttl_seconds'];
		}

		$response = $this->proxy_request(
			'POST',
			'/scene/gpu/intent',
			$intent,
			array(),
			'post_scan_read'
		);

		return $this->map_transport_failure( $response );
	}

	private function map_transport_failure( WP_REST_Response|WP_Error $response ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
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

		$status = $response->get_status();
		if ( $status < 400 || $this->is_gpu_intent_contract_passthrough( $status ) ) {
			return $response;
		}

		$data              = $response->get_data();
		$contract_mismatch = false;
		$payload           = array();

		if ( is_array( $data ) ) {
			$payload = $this->allowlisted_upstream_error_fields( $data );
		} elseif ( 500 <= $status && ! $this->is_decoded_json_scalar( $data ) ) {
			$contract_mismatch = true;
		}

		$payload['unavailable'] = $this->build_unavailable_envelope( $response, 'scene', $contract_mismatch );

		return new WP_REST_Response( $payload, $status, $response->get_headers() );
	}

	/**
	 * Typed unavailable object for GPU control failures.
	 *
	 * `checked_at` is the time the plugin observed the failure (gmdate UTC).
	 * proxy_request and its WP_Error data do not carry a failed-attempt timestamp.
	 *
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

	private function is_gpu_intent_contract_passthrough( int $status ): bool {
		return in_array( $status, self::GPU_INTENT_CONTRACT_PASSTHROUGH_STATUSES, true );
	}

	/**
	 * @param array<string, mixed> $data
	 * @return array<string, string>
	 */
	private function allowlisted_upstream_error_fields( array $data ): array {
		$allowed = array();

		if ( isset( $data['code'] ) && is_string( $data['code'] ) ) {
			$allowed['code'] = $data['code'];
		}

		if ( isset( $data['message'] ) && is_string( $data['message'] ) ) {
			$message = $data['message'];
			if ( self::UPSTREAM_MESSAGE_MAX_LENGTH < strlen( $message ) ) {
				$message = substr( $message, 0, self::UPSTREAM_MESSAGE_MAX_LENGTH );
			}
			$allowed['message'] = $message;
		}

		return $allowed;
	}

	private function is_decoded_json_scalar( mixed $data ): bool {
		return is_string( $data ) || is_int( $data ) || is_float( $data ) || is_bool( $data );
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
