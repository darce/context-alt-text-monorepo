<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\OutboxWriter;
use AltContext\Sovereign\Sync\OutboxWriterInterface;
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
use function is_object;
use function is_wp_error;
use function max;
use function method_exists;
use function rest_sanitize_boolean;
use function sanitize_text_field;
use function sprintf;
use function time;
use function trim;
use function wp_generate_uuid4;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class ClusterMutationsController extends AbstractRecognitionProxyController {
	private const XMP_REFRESH_CLUSTER_HOOK = 'acx_refresh_xmp_for_clusters';
	private const XMP_REFRESH_DELAY_SECONDS = 1;
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private OutboxWriterInterface $outbox_writer;

	public function __construct(
		?ClustersRepositoryInterface $clusters_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?OutboxWriterInterface $outbox_writer = null
	) {
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->outbox_writer = $outbox_writer ?? new OutboxWriter();
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
		global $wpdb;

		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		$target = sanitize_text_field( (string) ( $request->get_param( 'target_cluster_id' ) ?? '' ) );
		if ( '' === $target ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$payload = array(
			'tenant_id'         => $this->get_tenant_id(),
			'identity_id'       => $identity_id,
			'target_cluster_id' => $target,
			'user_id'           => get_current_user_id(),
		);
		$block_from_cluster = $request->get_param( 'block_from_cluster' );
		if ( null !== $block_from_cluster ) {
			$payload['block_from_cluster'] = rest_sanitize_boolean( $block_from_cluster );
		}

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		$affected_rows = $this->members_repository->reassign_to_cluster( $identity_id, $target );
		if ( $affected_rows > 0 && ! $this->enqueue_curation_operation( 'identity_reassigned', $identity_id, array(), $payload, 'member' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue reassign replay operation.', array( 'status' => 500 ) );
		}

		if ( $affected_rows > 0 ) {
			$this->sync_state_repository->touch_local_curation_marker( $this->get_tenant_id() );
		}

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		if ( $affected_rows > 0 ) {
			$this->trigger_xmp_refresh_for_cluster_ids( array( $target ), 'cluster-reassign' );
		}

		return new WP_REST_Response(
			array(
				'identity_id' => $identity_id,
				'target_cluster_id' => $target,
				'synced' => false,
				'status' => $affected_rows > 0 ? 'pending' : 'acknowledged',
			),
			200
		);
	}

	public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		$label      = sanitize_text_field( (string) $request->get_param( 'label' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $label ) {
			return new WP_Error( 'missing_label', 'Label cannot be empty.', array( 'status' => 400 ) );
		}

		$cluster = $this->clusters_repository->find_by_uuid( $cluster_id );
		if ( ! is_array( $cluster ) ) {
			return new WP_Error( 'cluster_not_found', 'Cluster not found.', array( 'status' => 404 ) );
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		$affected_rows = $this->clusters_repository->update_label( $cluster_id, $label );
		if ( $affected_rows > 0 && ! $this->enqueue_curation_operation(
			'cluster_label_updated',
			$cluster_id,
			$cluster,
			array(
				'cluster_uuid' => $cluster_id,
				'label' => $label,
			)
		) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue label replay operation.', array( 'status' => 500 ) );
		}

		if ( $affected_rows > 0 ) {
			$this->sync_state_repository->touch_local_curation_marker( $this->get_tenant_id() );
		}

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		if ( $affected_rows > 0 ) {
			$this->trigger_xmp_refresh_for_cluster_ids( array( $cluster_id ), 'cluster-label-update' );
		}

		return new WP_REST_Response(
			array(
				'cluster_id' => $cluster_id,
				'label' => $label,
				'synced' => false,
				'status' => $affected_rows > 0 ? 'pending' : 'acknowledged',
			),
			200
		);
	}

	public function dismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$cluster = $this->clusters_repository->find_by_uuid( $cluster_id );
		if ( ! is_array( $cluster ) ) {
			return new WP_Error( 'cluster_not_found', 'Cluster not found.', array( 'status' => 404 ) );
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		$affected_rows = $this->clusters_repository->dismiss( $cluster_id );

		if ( $affected_rows > 0 && ! $this->enqueue_curation_operation( 'cluster_dismissed', $cluster_id, $cluster ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue dismiss replay operation.', array( 'status' => 500 ) );
		}

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		return new WP_REST_Response(
			array(
				'dismissed' => true,
				'synced' => false,
				'status' => $affected_rows > 0 ? 'pending' : 'acknowledged',
			),
			200
		);
	}

	public function undismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$cluster = $this->clusters_repository->find_by_uuid( $cluster_id );
		if ( ! is_array( $cluster ) ) {
			return new WP_Error( 'cluster_not_found', 'Cluster not found.', array( 'status' => 404 ) );
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		$affected_rows = $this->clusters_repository->undismiss( $cluster_id );

		if ( $affected_rows > 0 && ! $this->enqueue_curation_operation( 'cluster_undismissed', $cluster_id, $cluster ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue undismiss replay operation.', array( 'status' => 500 ) );
		}

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		return new WP_REST_Response(
			array(
				'dismissed' => false,
				'synced' => false,
				'status' => $affected_rows > 0 ? 'pending' : 'acknowledged',
			),
			200
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
	 * @param array<string,mixed> $context_row
	 * @param array<string,mixed> $payload
	 */
	private function enqueue_curation_operation( string $operation_type, string $entity_key, array $context_row, array $payload = array(), string $entity_type = 'cluster' ): bool {
		$tenant_id = trim( $this->get_tenant_id() );
		if ( '' === $tenant_id ) {
			return false;
		}

		$resolved_payload = ! empty( $payload ) ? $payload : array(
			'cluster_uuid' => $entity_key,
		);
		$result = $this->outbox_writer->enqueue(
			$tenant_id,
			$operation_type,
			$entity_type,
			$entity_key,
			max( 0, (int) ( $context_row['snapshot_version'] ?? $this->sync_state_repository->get_snapshot_version( $tenant_id ) ) ),
			max( 1, (int) ( $context_row['local_revision'] ?? 0 ) + 1 ),
			$resolved_payload,
			wp_generate_uuid4()
		);

		return false !== $result;
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
