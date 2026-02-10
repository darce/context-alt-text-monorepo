<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Response;

use function add_query_arg;
use function current_user_can;
use function esc_url_raw;
use function get_option;
use function get_site_url;
use function in_array;
use function is_wp_error;
use function untrailingslashit;
use function wp_json_encode;
use function wp_remote_request;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_response_code;

abstract class AbstractRecognitionProxyController implements RecognitionRouteControllerInterface {
	private string $recognitionBaseUrl;
	private string $apiKey;

	public function __construct() {
		$this->recognitionBaseUrl = (string) get_option( 'alt_context_recognition_url', 'http://localhost:8000' );
		$this->apiKey             = (string) get_option( 'alt_context_recognition_api_key', '' );
	}

	public function can_manage_recognition(): bool {
		return current_user_can( 'manage_options' );
	}

	protected function proxy_request( string $method, string $path, array $body = array(), array $query = array() ): WP_REST_Response|WP_Error {
		if ( '' === $this->recognitionBaseUrl ) {
			return new WP_Error( 'recognition_not_configured', 'Recognition service URL is missing.', array( 'status' => 500 ) );
		}

		$base_url = untrailingslashit( $this->recognitionBaseUrl );
		$url      = esc_url_raw( $base_url . $path );

		if ( ! empty( $query ) ) {
			$url = esc_url_raw( add_query_arg( $query, $url ) );
		}

		$headers = array(
			'Content-Type' => 'application/json',
			'X-Tenant-ID'  => $this->get_tenant_id(),
		);

		if ( '' !== $this->apiKey ) {
			$headers['X-API-Key'] = $this->apiKey;
		}

		$options = array(
			'headers' => $headers,
			'timeout' => in_array( $method, array( 'POST', 'PUT', 'PATCH' ), true ) ? 60 : 30,
			'body'    => ! empty( $body ) && 'GET' !== $method ? wp_json_encode( $body ) : null,
		);

		$max_retries   = 3;
		$base_delay_ms = 500;
		$last_error    = null;

		for ( $attempt = 0; $attempt < $max_retries; $attempt++ ) {
			$response = wp_remote_request( $url, array_merge( $options, array( 'method' => $method ) ) );

			if ( is_wp_error( $response ) ) {
				$last_error = $response;
				if ( $attempt < $max_retries - 1 ) {
					$delay_ms = $base_delay_ms * ( 2 ** $attempt ); // 500ms, 1000ms, 2000ms
					usleep( $delay_ms * 1000 );
					continue;
				}
				return $response;
			}

			$status = wp_remote_retrieve_response_code( $response );
			if ( $status >= 500 && $attempt < $max_retries - 1 ) {
				$delay_ms = $base_delay_ms * ( 2 ** $attempt );
				usleep( $delay_ms * 1000 );
				continue;
			}

			$response_body = wp_remote_retrieve_body( $response );
			return new WP_REST_Response( json_decode( $response_body, true ), $status );
		}

		return $last_error ?? new WP_Error( 'proxy_failed', 'Request failed after retries.', array( 'status' => 502 ) );
	}

	protected function get_tenant_id(): string {
		return md5( (string) get_site_url() );
	}
}
