<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function add_query_arg;
use function current_user_can;
use function esc_url_raw;
use function get_current_user_id;
use function get_option;
use function get_site_url;
use function is_array;
use function is_wp_error;
use function sanitize_text_field;
use function wp_json_encode;
use function wp_remote_request;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_response_code;

class RecognitionController {
	private string $recognition_base_url;
	private string $api_key;

	public function __construct() {
		$this->recognition_base_url = (string) get_option( 'alt_context_recognition_url', 'http://localhost:8000' );
		$this->api_key             = (string) get_option( 'alt_context_recognition_api_key', '' );
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/analyze',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'analyze_media' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/jobs/(?P<job_id>[a-f0-9-]+)',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_job_status' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/cluster',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'cluster_media' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'list_clusters' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/reassign',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'reassign_cluster_identity' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/media-identities',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_media_identities' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
				'args'                => [
				 'media_ids' => [
					 'type'        => 'array',
					 'required'    => true,
					 'items'       => [ 'type' => 'integer' ],
					 'description' => 'Attachment IDs to fetch detected identities for (max 100).',
				 ],
				],
			]
		);
	}

	public function can_manage_recognition(): bool {
		return current_user_can( 'manage_options' );
	}

	public function analyze_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_items = $request->get_param( 'media_items' );

		if ( ! is_array( $media_items ) || count( $media_items ) === 0 ) {
			return new WP_Error( 'no_media_items', 'At least one media item is required', [ 'status' => 400 ] );
		}

		$payload = [
			'tenant_id'   => $this->get_tenant_id(),
			'media_items' => array_map( [ $this, 'sanitize_media_item' ], $media_items ),
			'user_id'     => get_current_user_id(),
		];

		return $this->proxy_request( 'POST', '/recognition/analyze', $payload );
	}

	public function get_job_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/jobs/%s', $request->get_param( 'job_id' ) ),
			[],
			[
				'tenant_id' => $this->get_tenant_id(),
			]
		);
	}

	public function cluster_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$payload = [
			'tenant_id'            => $this->get_tenant_id(),
			'similarity_threshold' => (float) $request->get_param( 'similarity_threshold' ) ?: 0.6,
		];

		return $this->proxy_request( 'POST', '/recognition/cluster', $payload );
	}

	public function list_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = [
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => absint( $request->get_param( 'limit' ) ?: 50 ),
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		];

		return $this->proxy_request( 'GET', '/recognition/clusters', [], $query );
	}

	public function reassign_cluster_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', [ 'status' => 400 ] );
		}

		$target = $request->get_param( 'target_cluster_id' );
		$payload = [
			'tenant_id'         => $this->get_tenant_id(),
			'identity_id'       => $identity_id,
			'target_cluster_id' => $target ? sanitize_text_field( (string) $target ) : null,
			'user_id'           => get_current_user_id(),
		];

		return $this->proxy_request( 'POST', '/recognition/clusters/reassign', $payload );
	}

	public function get_media_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_ids = $request->get_param( 'media_ids' );
		if ( ! is_array( $media_ids ) || empty( $media_ids ) ) {
			return new WP_Error( 'missing_media_ids', 'Provide one or more media_ids to fetch identities.', [ 'status' => 400 ] );
		}

		$ids = array();
		foreach ( $media_ids as $media_id ) {
			$abs = absint( $media_id );
			if ( $abs > 0 ) {
				$ids[] = $abs;
			}
		}

		if ( empty( $ids ) || count( $ids ) > 100 ) {
			return new WP_Error( 'invalid_media_ids', 'Provide between 1 and 100 valid attachment IDs.', [ 'status' => 400 ] );
		}

		$query = [
			'tenant_id' => $this->get_tenant_id(),
			'media_ids' => $ids,
		];

		return $this->proxy_request( 'GET', '/recognition/media/identities', [], $query );
	}

	private function proxy_request( string $method, string $path, array $body = [], array $query = [] ): WP_REST_Response|WP_Error {
		if ( '' === $this->recognition_base_url || '' === $this->api_key ) {
			return new WP_Error( 'recognition_not_configured', 'Recognition service credentials are missing', [ 'status' => 500 ] );
		}

		$url = esc_url_raw( $this->recognition_base_url . $path );

		if ( ! empty( $query ) ) {
			$url = esc_url_raw( add_query_arg( $query, $url ) );
		}

		$options = [
			'headers' => [
				'Content-Type' => 'application/json',
				'X-API-Key'    => $this->api_key,
			],
			'timeout' => 60,
			'body'    => ! empty( $body ) ? wp_json_encode( $body ) : null,
		];

		$response = wp_remote_request( $url, array_merge( $options, [ 'method' => $method ] ) );

		if ( is_wp_error( $response ) ) {
			return $response;
		}

		$status = wp_remote_retrieve_response_code( $response );
		$body   = wp_remote_retrieve_body( $response );

		return new WP_REST_Response( json_decode( $body, true ), $status );
	}

	private function sanitize_media_item( array $media_item ): array {
		return [
			'media_id'  => absint( $media_item['media_id'] ?? 0 ),
			'media_url' => esc_url_raw( (string) ( $media_item['media_url'] ?? '' ) ),
		];
	}

	private function get_tenant_id(): string {
		return md5( (string) get_site_url() );
	}
}
