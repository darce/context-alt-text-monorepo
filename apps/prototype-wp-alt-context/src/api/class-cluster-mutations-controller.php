<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function add_action;
use function array_filter;
use function array_map;
use function array_unique;
use function array_values;
use function do_action;
use function get_current_user_id;
use function in_array;
use function is_array;
use function rest_sanitize_boolean;
use function sanitize_text_field;
use function sprintf;
use function time;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class ClusterMutationsController extends AbstractRecognitionProxyController {
	private const XMP_REFRESH_CLUSTER_HOOK = 'acx_refresh_xmp_for_clusters';
	private const XMP_REFRESH_DELAY_SECONDS = 1;

	public function __construct() {
		add_action( self::XMP_REFRESH_CLUSTER_HOOK, array( $this, 'refresh_xmp_for_cluster_ids_async' ), 10, 2 );
	}

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
				'methods'             => 'PATCH',
				'callback'            => array( $this, 'update_cluster_label' ),
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

		$response = $this->proxy_request( 'POST', '/recognition/clusters/reassign', $payload );
		$this->maybe_trigger_xmp_refresh_for_response( $response, array(), 'cluster-reassign' );
		return $response;
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

		$response = $this->proxy_request( 'PATCH', sprintf( '/recognition/clusters/%s', $cluster_id ), $payload );
		$this->maybe_trigger_xmp_refresh_for_response( $response, array( $cluster_id ), 'cluster-label-update' );
		return $response;
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

		$response = $this->proxy_request( 'POST', sprintf( '/recognition/clusters/%s/merge', $source_id ), $payload );
		$this->maybe_trigger_xmp_refresh_for_response( $response, array( $source_id, $target_cluster_id ), 'cluster-merge' );
		return $response;
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

		$response = $this->proxy_request( 'POST', sprintf( '/recognition/clusters/%s/split', $cluster_id ), $payload );
		$this->maybe_trigger_xmp_refresh_for_response( $response, array( $cluster_id ), 'cluster-split' );
		return $response;
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

		$response = $this->proxy_request( 'POST', '/recognition/clusters/create-for-identity', $payload );
		$this->maybe_trigger_xmp_refresh_for_response( $response, array(), 'cluster-create-for-identity' );
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

		$response = $this->proxy_request( 'POST', '/recognition/clusters/revert-merge', $payload );
		$this->maybe_trigger_xmp_refresh_for_response( $response, array( $target_cluster_id ), 'cluster-revert-merge' );
		return $response;
	}

	/**
	 * @param string[] $default_cluster_ids
	 */
	private function maybe_trigger_xmp_refresh_for_response( WP_REST_Response|WP_Error $response, array $default_cluster_ids, string $context ): void {
		if ( ! ( $response instanceof WP_REST_Response ) || $response->get_status() >= 400 ) {
			return;
		}

		$cluster_ids = $this->extract_cluster_ids_from_response_data( $response->get_data(), $default_cluster_ids );
		$this->trigger_xmp_refresh_for_cluster_ids( $cluster_ids, $context );
	}

	/**
	 * @param mixed $data
	 * @param string[] $default_cluster_ids
	 * @return string[]
	 */
	private function extract_cluster_ids_from_response_data( $data, array $default_cluster_ids = array() ): array {
		$cluster_ids = $default_cluster_ids;

		if ( ! is_array( $data ) ) {
			return $this->sanitize_cluster_ids( $cluster_ids );
		}

		foreach ( array( 'cluster_id', 'source_cluster_id', 'target_cluster_id', 'new_cluster_id' ) as $key ) {
			$value = sanitize_text_field( (string) ( $data[ $key ] ?? '' ) );
			if ( '' !== $value ) {
				$cluster_ids[] = $value;
			}
		}

		if ( is_array( $data['new_cluster_ids'] ?? null ) ) {
			foreach ( $data['new_cluster_ids'] as $new_cluster_id ) {
				$value = sanitize_text_field( (string) $new_cluster_id );
				if ( '' !== $value ) {
					$cluster_ids[] = $value;
				}
			}
		}

		if ( is_array( $data['clusters'] ?? null ) ) {
			foreach ( $data['clusters'] as $cluster ) {
				if ( ! is_array( $cluster ) ) {
					continue;
				}

				$value = sanitize_text_field( (string) ( $cluster['id'] ?? $cluster['cluster_id'] ?? '' ) );
				if ( '' !== $value ) {
					$cluster_ids[] = $value;
				}
			}
		}

		return $this->sanitize_cluster_ids( $cluster_ids );
	}

	/**
	 * @param string[] $cluster_ids
	 */
	private function trigger_xmp_refresh_for_cluster_ids( array $cluster_ids, string $context ): void {
		$normalized_cluster_ids = $this->sanitize_cluster_ids( $cluster_ids );
		if ( empty( $normalized_cluster_ids ) ) {
			return;
		}

		$args = array( $normalized_cluster_ids, $context );
		if ( false === wp_next_scheduled( self::XMP_REFRESH_CLUSTER_HOOK, $args ) ) {
			wp_schedule_single_event( time() + self::XMP_REFRESH_DELAY_SECONDS, self::XMP_REFRESH_CLUSTER_HOOK, $args );
		}
	}

	/**
	 * @param string[] $cluster_ids
	 */
	public function refresh_xmp_for_cluster_ids_async( array $cluster_ids, string $context ): void {
		$normalized_cluster_ids = $this->sanitize_cluster_ids( $cluster_ids );
		if ( empty( $normalized_cluster_ids ) ) {
			return;
		}

		$media_ids = array();
		foreach ( $normalized_cluster_ids as $cluster_id ) {
			$members_response = $this->proxy_request(
				'GET',
				sprintf( '/recognition/clusters/%s/members', $cluster_id ),
				array(),
				array( 'tenant_id' => $this->get_tenant_id() )
			);

			if ( ! ( $members_response instanceof WP_REST_Response ) || 200 !== $members_response->get_status() ) {
				continue;
			}

			$members_data = $members_response->get_data();
			// Compatibility: legacy service returns a flat list, newer shape wraps members in {members:[...]}.
			if ( is_array( $members_data ) && is_array( $members_data['members'] ?? null ) ) {
				$members_data = $members_data['members'];
			}

			if ( ! is_array( $members_data ) ) {
				continue;
			}

			foreach ( $members_data as $member ) {
				if ( ! is_array( $member ) ) {
					continue;
				}

				$media_id = absint( $member['media_id'] ?? 0 );
				if ( $media_id > 0 ) {
					$media_ids[] = $media_id;
				}
			}
		}

		foreach ( array_values( array_unique( $media_ids ) ) as $media_id ) {
			do_action( 'acx_recognition_complete', $media_id, $context );
		}
	}

	/**
	 * @param string[] $cluster_ids
	 * @return string[]
	 */
	private function sanitize_cluster_ids( array $cluster_ids ): array {
		$normalized = array_map(
			static function ( string $cluster_id ): string {
				return sanitize_text_field( $cluster_id );
			},
			$cluster_ids
		);

		return array_values( array_unique( array_filter( $normalized ) ) );
	}
}
