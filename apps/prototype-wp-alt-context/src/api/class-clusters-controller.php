<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function get_current_user_id;
use function in_array;
use function is_array;
use function min;
use function rest_sanitize_boolean;
use function sanitize_text_field;
use function sprintf;
use function wp_get_attachment_url;

class ClustersController extends AbstractRecognitionProxyController {
	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/cluster',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'cluster_media' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

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
			'/recognition/clusters/reassign',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'reassign_cluster_identity' ),
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
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)',
			array(
				'methods'             => 'PATCH',
				'callback'            => array( $this, 'update_cluster_label' ),
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

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/dismiss',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'dismiss_cluster' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/dismiss',
			array(
				'methods'             => 'DELETE',
				'callback'            => array( $this, 'undismiss_cluster' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<source_id>[a-f0-9-]+)/merge',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'merge_cluster' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/split',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'split_cluster' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/create-for-identity',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'create_cluster_for_identity' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/media-identities',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_media_identities' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_ids'     => array(
						'type'        => 'array',
						'required'    => true,
						'items'       => array( 'type' => 'integer' ),
						'description' => 'Attachment IDs to fetch detected identities for (max 100).',
					),
					'include_debug' => array(
						'type'        => 'string',
						'required'    => false,
						'description' => 'Include debug metrics in response.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/revert-merge',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'revert_merge_cluster' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function cluster_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$mode = sanitize_text_field( (string) ( $request->get_param( 'mode' ) ?? 'async' ) );
		if ( ! in_array( $mode, array( 'sync', 'async' ), true ) ) {
			return new WP_Error( 'invalid_mode', 'Mode must be sync or async.', array( 'status' => 400 ) );
		}

		$body = array(
			'tenant_id' => $this->get_tenant_id(),
			'mode'      => $mode,
		);

		return $this->proxy_request( 'POST', '/recognition/clustering/jobs', $body );
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

	public function reassign_cluster_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		$target  = $request->get_param( 'target_cluster_id' );
		$payload = array(
			'tenant_id'         => $this->get_tenant_id(),
			'identity_id'       => $identity_id,
			'target_cluster_id' => $target ? sanitize_text_field( (string) $target ) : null,
			'user_id'           => get_current_user_id(),
		);
		$block_from_cluster = $request->get_param( 'block_from_cluster' );
		if ( null !== $block_from_cluster ) {
			$payload['block_from_cluster'] = rest_sanitize_boolean( $block_from_cluster );
		}

		return $this->proxy_request( 'POST', '/recognition/clusters/reassign', $payload );
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

	public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		$label      = sanitize_text_field( (string) $request->get_param( 'label' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $label ) {
			return new WP_Error( 'missing_label', 'Label cannot be empty.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id' => $this->get_tenant_id(),
			'label'     => $label,
		);

		return $this->proxy_request( 'PATCH', sprintf( '/recognition/clusters/%s', $cluster_id ), $payload );
	}

	public function dismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/clusters/%s/dismiss', $cluster_id ),
			array(),
			array( 'tenant_id' => $this->get_tenant_id() )
		);
	}

	public function undismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		return $this->proxy_request(
			'DELETE',
			sprintf( '/recognition/clusters/%s/dismiss', $cluster_id ),
			array(),
			array( 'tenant_id' => $this->get_tenant_id() )
		);
	}

	public function merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$source_id         = sanitize_text_field( (string) $request->get_param( 'source_id' ) );
		$target_cluster_id = sanitize_text_field( (string) $request->get_param( 'target_cluster_id' ) );
		$target_label      = sanitize_text_field( (string) $request->get_param( 'target_label' ) );

		if ( '' === $source_id ) {
			return new WP_Error( 'missing_source_id', 'Source cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $target_cluster_id ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id'         => $this->get_tenant_id(),
			'target_cluster_id' => $target_cluster_id,
		);

		if ( '' !== $target_label ) {
			$payload['target_label'] = $target_label;
		}

		return $this->proxy_request( 'POST', sprintf( '/recognition/clusters/%s/merge', $source_id ), $payload );
	}

	public function split_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$n_clusters = absint( $request->get_param( 'n_clusters' ) ?? 0 );

		$payload = array(
			'tenant_id'  => $this->get_tenant_id(),
			'n_clusters' => $n_clusters,
		);
		$anchor_identity_id = sanitize_text_field( (string) $request->get_param( 'anchor_identity_id' ) );
		if ( '' !== $anchor_identity_id ) {
			$payload['anchor_identity_id'] = $anchor_identity_id;
		}
		$split_mode = sanitize_text_field( (string) $request->get_param( 'split_mode' ) );
		if ( '' !== $split_mode ) {
			$payload['split_mode'] = $split_mode;
		}

		return $this->proxy_request( 'POST', sprintf( '/recognition/clusters/%s/split', $cluster_id ), $payload );
	}

	public function create_cluster_for_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		$label       = sanitize_text_field( (string) $request->get_param( 'label' ) );

		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $label ) {
			return new WP_Error( 'missing_label', 'Label is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id'   => $this->get_tenant_id(),
			'identity_id' => $identity_id,
			'label'       => $label,
			'user_id'     => get_current_user_id(),
		);

		return $this->proxy_request( 'POST', '/recognition/clusters/create-for-identity', $payload );
	}

	public function get_media_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_ids = $request->get_param( 'media_ids' );
		if ( ! is_array( $media_ids ) || empty( $media_ids ) ) {
			return new WP_Error( 'missing_media_ids', 'Provide one or more media_ids to fetch identities.', array( 'status' => 400 ) );
		}

		$ids = array();
		foreach ( $media_ids as $media_id ) {
			$abs = absint( $media_id );
			if ( $abs > 0 ) {
				$ids[] = $abs;
			}
		}

		if ( empty( $ids ) || count( $ids ) > 100 ) {
			return new WP_Error( 'invalid_media_ids', 'Provide between 1 and 100 valid attachment IDs.', array( 'status' => 400 ) );
		}

		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'media_ids' => $ids,
		);

		$include_debug = $request->get_param( 'include_debug' );
		if ( null !== $include_debug && true === rest_sanitize_boolean( $include_debug ) ) {
			$query['include_debug'] = 'true';
		}

		$response = $this->proxy_request( 'GET', '/recognition/media/identities', array(), $query );

		if ( $response instanceof WP_REST_Response && 200 === $response->get_status() ) {
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$grouped = array();
				foreach ( $data as $identity ) {
					if ( isset( $identity['media_id'] ) ) {
						$media_key = (string) $identity['media_id'];
						if ( ! isset( $grouped[ $media_key ] ) ) {
							$grouped[ $media_key ] = array();
						}
						$grouped[ $media_key ][] = $identity;
					}
				}
				return new WP_REST_Response( array( 'identities_by_media' => $grouped ), 200 );
			}
		}

		return $response;
	}

	public function revert_merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$target_cluster_id  = sanitize_text_field( (string) $request->get_param( 'target_cluster_id' ) );
		$moved_identity_ids = $request->get_param( 'moved_identity_ids' );
		$source_label       = $request->get_param( 'source_label' );

		if ( '' === $target_cluster_id ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( ! is_array( $moved_identity_ids ) || empty( $moved_identity_ids ) ) {
			return new WP_Error( 'missing_moved_identity_ids', 'Provide one or more identity IDs to revert.', array( 'status' => 400 ) );
		}

		$sanitized_ids = array_map(
			static function ( $value ): string {
				return sanitize_text_field( (string) $value );
			},
			$moved_identity_ids
		);

		$payload = array(
			'tenant_id'          => $this->get_tenant_id(),
			'target_cluster_id'  => $target_cluster_id,
			'moved_identity_ids' => $sanitized_ids,
			'source_label'       => $source_label ? sanitize_text_field( (string) $source_label ) : null,
			'user_id'            => get_current_user_id(),
		);

		return $this->proxy_request( 'POST', '/recognition/clusters/revert-merge', $payload );
	}
}
