<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function is_array;
use function min;
use function sanitize_text_field;
use function sprintf;
use function wp_get_attachment_url;

class ClustersController extends AbstractRecognitionProxyController {
	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/clusters',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_clusters' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/top-unlabeled',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_top_unlabeled_clusters' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/labels',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_cluster_labels' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_cluster_detail' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/members',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_cluster_members' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function list_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$limit  = absint( $request->get_param( 'limit' ) ?? 50 );
		$limit  = min( $limit, 500 );
		$search = sanitize_text_field( (string) $request->get_param( 'search' ) );

		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => $limit,
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		);

		if ( 'true' === $request->get_param( 'labeled_only' ) ) {
			$query['labeled_only'] = 'true';
		}

		if ( '' !== $search ) {
			$query['search'] = $search;
		}

		return $this->proxy_request( 'GET', '/recognition/clusters', array(), $query );
	}

	public function list_top_unlabeled_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => absint( $request->get_param( 'limit' ) ?? 10 ),
		);

		$response = $this->proxy_request( 'GET', '/recognition/clusters/top-unlabeled', array(), $query );
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( 200 !== $response->get_status() ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		foreach ( $data as $cluster_index => $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}
			if ( ! isset( $cluster['representatives'] ) || ! is_array( $cluster['representatives'] ) ) {
				continue;
			}

			foreach ( $cluster['representatives'] as $rep_index => $rep ) {
				if ( ! is_array( $rep ) ) {
					continue;
				}

				$thumb_url = $rep['thumb_url'] ?? null;
				if ( ( ! is_string( $thumb_url ) || '' === $thumb_url ) && isset( $rep['thumbnail_url'] ) ) {
					$legacy_thumb = $rep['thumbnail_url'];
					if ( is_string( $legacy_thumb ) && '' !== $legacy_thumb ) {
						$thumb_url = $legacy_thumb;
					}
				}

				if ( ( ! is_string( $thumb_url ) || '' === $thumb_url ) && isset( $rep['media_id'] ) ) {
					$media_id = absint( $rep['media_id'] );
					if ( $media_id > 0 ) {
						$fallback_url = wp_get_attachment_url( $media_id );
						if ( is_string( $fallback_url ) && '' !== $fallback_url ) {
							$thumb_url = $fallback_url;
						}
					}
				}

				$cluster['representatives'][ $rep_index ]['thumb_url'] = is_string( $thumb_url ) && '' !== $thumb_url ? $thumb_url : null;
			}

			$data[ $cluster_index ] = $cluster;
		}

		$response->set_data( $data );
		return $response;
	}

	public function list_cluster_labels( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = array(
			'tenant_id' => $this->get_tenant_id(),
		);

		return $this->proxy_request( 'GET', '/recognition/clusters/labels', array(), $query );
	}

	public function get_cluster_detail( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s', $cluster_id ),
			array(),
			array( 'tenant_id' => $this->get_tenant_id() )
		);
	}

	public function get_cluster_members( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s/members', $cluster_id ),
			array(),
			array( 'tenant_id' => $this->get_tenant_id() )
		);
	}
}
