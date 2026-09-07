<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function array_key_exists;
use function in_array;
use function is_array;
use function is_int;
use function is_object;
use function is_string;
use function is_wp_error;
use function register_rest_route;
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
		if ( ! is_wp_error( $response ) ) {
			return $response;
		}

		return new WP_Error(
			self::ERROR_CODE_UNAVAILABLE,
			$response->get_error_message(),
			array( 'status' => 502 )
		);
	}
}
