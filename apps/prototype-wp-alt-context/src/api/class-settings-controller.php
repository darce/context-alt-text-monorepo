<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;
use function current_user_can;
use function defined;
use function get_option;
use function is_string;
use function register_rest_route;
use function substr;
use function trim;
use function update_option;
use function wp_remote_get;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_response_code;

/**
 * REST controller for recognition API configuration.
 *
 * GET  /acx/v1/settings          — read current config with source detection
 * POST /acx/v1/settings          — save URL and/or API key to WP options
 * POST /acx/v1/settings/test     — test connection to the recognition health endpoint
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

		return new WP_REST_Response(
			array(
				'url'          => $url_resolution['value'],
				'url_source'   => $url_resolution['source'],
				'api_key_set'  => '' !== $key_resolution['value'],
				'api_key_last4' => $this->mask_key( $key_resolution['value'] ),
				'key_source'   => $key_resolution['source'],
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
		$key_resolution = $this->resolve_key_source();

		$url = $url_resolution['value'];
		if ( '' === $url ) {
			return new WP_REST_Response(
				array(
					'connected' => false,
					'error'     => 'Recognition API URL is not configured.',
				),
				200
			);
		}

		$health_url = rtrim( $url, '/' ) . '/recognition/health';
		$headers    = array();
		if ( '' !== $key_resolution['value'] ) {
			$headers['X-API-Key'] = $key_resolution['value'];
		}

		$response = wp_remote_get(
			$health_url,
			array(
				'headers' => $headers,
				'timeout' => 10,
			)
		);

		if ( is_wp_error( $response ) ) {
			return new WP_REST_Response(
				array(
					'connected' => false,
					'error'     => $response->get_error_message(),
				),
				200
			);
		}

		$status_code = (int) wp_remote_retrieve_response_code( $response );
		$body        = wp_remote_retrieve_body( $response );

		return new WP_REST_Response(
			array(
				'connected'   => $status_code >= 200 && $status_code < 300,
				'status_code' => $status_code,
				'body'        => json_decode( $body, true ) ?: $body,
			),
			200
		);
	}

	/**
	 * Resolve the recognition URL and its source using the same priority chain
	 * as class-abstract-recognition-proxy-controller.php.
	 *
	 * @return array{value: string, source: string}
	 */
	private function resolve_url_source(): array {
		$constant = $this->get_constant_value( 'ACX_RECOGNITION_URL' );
		if ( '' !== $constant ) {
			return array( 'value' => $constant, 'source' => 'constant' );
		}

		$option = trim( (string) get_option( 'acx_recognition_url', '' ) );
		if ( '' !== $option && $this->is_valid_url( $option ) ) {
			return array( 'value' => $option, 'source' => 'option' );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_base_url', '' ) );
		if ( '' !== $filter && $this->is_valid_url( $filter ) ) {
			return array( 'value' => $filter, 'source' => 'filter' );
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
}
