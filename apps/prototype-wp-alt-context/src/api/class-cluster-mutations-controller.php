<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/../sovereign/sync/interface-outbox-writer.php';
require_once __DIR__ . '/../sovereign/sync/class-outbox-writer.php';
require_once __DIR__ . '/../sovereign/sync/interface-topology-command-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-topology-command-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-split-topology-command-drain.php';

use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\OutboxWriter;
use AltContext\Sovereign\Sync\OutboxWriterInterface;
use AltContext\Sovereign\Sync\SplitTopologyCommandDrain;
use AltContext\Sovereign\Sync\TopologyCommandRepository;
use AltContext\Sovereign\Sync\TopologyCommandRepositoryInterface;
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
use function md5;
use function max;
use function method_exists;
use function rest_sanitize_boolean;
use function sanitize_text_field;
use function sprintf;
use function substr;
use function time;
use function trim;
use function wp_generate_uuid4;
use function wp_next_scheduled;
use function wp_json_encode;
use function wp_schedule_single_event;

class ClusterMutationsController extends AbstractRecognitionProxyController {
	private const XMP_REFRESH_CLUSTER_HOOK = 'acx_refresh_xmp_for_clusters';
	private const XMP_REFRESH_DELAY_SECONDS = 1;
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private OutboxWriterInterface $outbox_writer;
	private TopologyCommandRepositoryInterface $topology_command_repository;

	public function __construct(
		?ClustersRepositoryInterface $clusters_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?OutboxWriterInterface $outbox_writer = null,
		?TopologyCommandRepositoryInterface $topology_command_repository = null
	) {
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->outbox_writer = $outbox_writer ?? new OutboxWriter();
		$this->topology_command_repository = $topology_command_repository ?? new TopologyCommandRepository();
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

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/assign',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'assign_outlier_to_cluster' ),
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
		global $wpdb;

		$source_id         = sanitize_text_field( (string) $request->get_param( 'source_id' ) );
		$target_cluster_id = sanitize_text_field( (string) $request->get_param( 'target_cluster_id' ) );
		$target_label      = sanitize_text_field( (string) $request->get_param( 'target_label' ) );

		if ( '' === $source_id ) {
			return new WP_Error( 'missing_source_id', 'Source cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $target_cluster_id ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $source_id === $target_cluster_id ) {
			return new WP_Error( 'invalid_target_cluster_id', 'Source and target cluster IDs must differ.', array( 'status' => 400 ) );
		}

		$source_cluster = $this->clusters_repository->find_by_uuid( $source_id );
		if ( ! is_array( $source_cluster ) ) {
			return new WP_Error( 'source_cluster_not_found', 'Source cluster not found.', array( 'status' => 404 ) );
		}

		$target_cluster = $this->clusters_repository->find_by_uuid( $target_cluster_id );
		if ( ! is_array( $target_cluster ) ) {
			return new WP_Error( 'target_cluster_not_found', 'Target cluster not found.', array( 'status' => 404 ) );
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$source_member_count = $this->members_repository->count_for_cluster( $source_id );
		$target_member_count = $this->members_repository->count_for_cluster( $target_cluster_id );

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		$moved_rows = $this->members_repository->reassign_cluster_members( $source_id, $target_cluster_id );
		$this->clusters_repository->update_identity_count( $source_id, 0 );
		$this->clusters_repository->update_identity_count( $target_cluster_id, $target_member_count + $source_member_count );

		if ( '' !== $target_label ) {
			$this->clusters_repository->update_label( $target_cluster_id, $target_label );
		}

		$this->clusters_repository->dismiss( $source_id );

		$payload = array(
			'tenant_id'         => $this->get_tenant_id(),
			'target_cluster_id' => $target_cluster_id,
		);

		if ( '' !== $target_label ) {
			$payload['target_label'] = $target_label;
		}

		if ( ! $this->enqueue_curation_operation( 'cluster_merged', $source_id, $source_cluster, $payload ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue merge replay operation.', array( 'status' => 500 ) );
		}

		$this->sync_state_repository->touch_local_curation_marker( $this->get_tenant_id() );

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		$this->trigger_xmp_refresh_for_cluster_ids( array( $source_id, $target_cluster_id ), 'cluster-merge' );

		return new WP_REST_Response(
			array(
				'source_cluster_id' => $source_id,
				'target_cluster_id' => $target_cluster_id,
				'moved_identity_count' => $moved_rows,
				'synced' => false,
				'status' => 'pending',
			),
			200
		);
	}

	public function split_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$cluster = $this->clusters_repository->find_by_uuid( $cluster_id );
		if ( ! is_array( $cluster ) ) {
			return new WP_Error( 'cluster_not_found', 'Cluster not found.', array( 'status' => 404 ) );
		}

			$n_clusters = absint( $request->get_param( 'n_clusters' ) ?? 0 );

			$payload = array(
			'tenant_id'  => $this->get_tenant_id(),
			'cluster_id' => $cluster_id,
			'n_clusters' => $n_clusters,
			'user_id'    => get_current_user_id(),
			);
			$anchor_identity_id = sanitize_text_field( (string) $request->get_param( 'anchor_identity_id' ) );
			if ( '' !== $anchor_identity_id ) {
				$payload['anchor_identity_id'] = $anchor_identity_id;
			}
			$split_mode = sanitize_text_field( (string) $request->get_param( 'split_mode' ) );
			if ( '' !== $split_mode ) {
				$payload['split_mode'] = $split_mode;
			}

			$desired_cluster_ids = $request->get_param( 'desired_cluster_ids' );
			if ( is_array( $desired_cluster_ids ) && ! empty( $desired_cluster_ids ) ) {
				$payload['desired_cluster_ids'] = array_values(
				array_filter(
					array_map(
						static function ( $value ): string {
							return sanitize_text_field( (string) $value );
						},
						$desired_cluster_ids
					),
					static function ( string $value ): bool {
						return '' !== $value;
					}
				)
				);
			}

			$idempotency_key = $this->resolve_split_idempotency_key(
			$request,
			$cluster_id,
			max( 0, (int) ( $cluster['snapshot_version'] ?? $this->sync_state_repository->get_snapshot_version( $this->get_tenant_id() ) ) ),
			$payload
		);

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		$command_id = $this->topology_command_repository->enqueue(
			$this->get_tenant_id(),
			'cluster_split',
			$cluster_id,
			max( 0, (int) ( $cluster['snapshot_version'] ?? $this->sync_state_repository->get_snapshot_version( $this->get_tenant_id() ) ) ),
			$payload,
			$idempotency_key
		);

		if ( false === $command_id ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue split topology command.', array( 'status' => 500 ) );
		}

		$this->sync_state_repository->touch_local_curation_marker( $this->get_tenant_id() );
		$this->sync_state_repository->refresh_curation_metrics( $this->get_tenant_id() );

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		SplitTopologyCommandDrain::maybe_schedule_drain();

		return new WP_REST_Response(
			array(
				'command_id' => $command_id,
				'synced' => false,
				'status' => 'pending',
				'command_state' => 'queued',
				'projection_state' => 'awaiting_backend_partition',
				'cluster_id' => $cluster_id,
				'idempotency_key' => $idempotency_key,
			),
			200
		);
	}

	public function create_cluster_for_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		$label       = sanitize_text_field( (string) $request->get_param( 'label' ) );

		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $label ) {
			return new WP_Error( 'missing_label', 'Label is required.', array( 'status' => 400 ) );
		}

		$existing_member = $this->members_repository->find_by_identity_uuid( $identity_id );
		if ( ! is_array( $existing_member ) ) {
			return new WP_Error( 'identity_not_found', 'Identity is not present in the local projection.', array( 'status' => 404 ) );
		}

		$tenant_id = $this->get_tenant_id();
		$new_cluster_id = wp_generate_uuid4();
		$source_cluster_id = sanitize_text_field( (string) ( $existing_member['cluster_uuid'] ?? '' ) );
		$source_member_count = '' !== $source_cluster_id ? $this->members_repository->count_for_cluster( $source_cluster_id ) : 0;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		if ( $this->clusters_repository->create_local_cluster( $tenant_id, $new_cluster_id, $label, 1 ) <= 0 ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not create local cluster projection.', array( 'status' => 500 ) );
		}

		$this->members_repository->reassign_to_cluster( $identity_id, $new_cluster_id );
		if ( '' !== $source_cluster_id ) {
			$this->clusters_repository->update_identity_count( $source_cluster_id, max( 0, $source_member_count - 1 ) );
		}

		$payload = array(
			'tenant_id'   => $tenant_id,
			'identity_id' => $identity_id,
			'label'       => $label,
			'user_id'     => get_current_user_id(),
			'desired_cluster_id' => $new_cluster_id,
		);

		if ( ! $this->enqueue_curation_operation( 'cluster_created_for_identity', $new_cluster_id, array(
			'cluster_uuid' => $new_cluster_id,
			'snapshot_version' => 0,
			'local_revision' => 1,
		), $payload ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue create-cluster replay operation.', array( 'status' => 500 ) );
		}

		$this->sync_state_repository->touch_local_curation_marker( $tenant_id );

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		$this->trigger_xmp_refresh_for_cluster_ids( array_values( array_filter( array( $source_cluster_id, $new_cluster_id ) ) ), 'cluster-create-for-identity' );

		return new WP_REST_Response(
			array(
				'cluster_id' => $new_cluster_id,
				'identity_id' => $identity_id,
				'label' => $label,
				'synced' => false,
				'status' => 'pending',
			),
			200
		);
	}

	public function revert_merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$target_cluster_id  = sanitize_text_field( (string) $request->get_param( 'target_cluster_id' ) );
		$moved_identity_ids = $request->get_param( 'moved_identity_ids' );
		$source_label       = $request->get_param( 'source_label' );
		$requested_source_cluster_id = sanitize_text_field( (string) ( $request->get_param( 'source_cluster_id' ) ?? '' ) );

		if ( '' === $target_cluster_id ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( ! is_array( $moved_identity_ids ) || empty( $moved_identity_ids ) ) {
			return new WP_Error( 'missing_moved_identity_ids', 'Provide one or more identity IDs to revert.', array( 'status' => 400 ) );
		}

		$sanitized_ids = array_values(
			array_unique(
				array_filter(
					array_map(
						static function ( $value ): string {
							return sanitize_text_field( (string) $value );
						},
						$moved_identity_ids
					),
					static function ( string $value ): bool {
						return '' !== $value;
					}
				)
			)
		);
		if ( empty( $sanitized_ids ) ) {
			return new WP_Error( 'missing_moved_identity_ids', 'Provide one or more valid identity IDs to revert.', array( 'status' => 400 ) );
		}

		$target_cluster = $this->clusters_repository->find_by_uuid( $target_cluster_id );
		if ( ! is_array( $target_cluster ) ) {
			return new WP_Error( 'target_cluster_not_found', 'Target cluster not found.', array( 'status' => 404 ) );
		}

		foreach ( $sanitized_ids as $identity_id ) {
			$member = $this->members_repository->find_by_identity_uuid( $identity_id );
			if ( ! is_array( $member ) ) {
				return new WP_Error( 'identity_not_found', 'One or more identities are not present in the local projection.', array( 'status' => 404 ) );
			}

			$current_cluster_id = sanitize_text_field( (string) ( $member['cluster_uuid'] ?? '' ) );
			if ( $target_cluster_id !== $current_cluster_id ) {
				return new WP_Error( 'identity_not_in_target_cluster', 'One or more identities are no longer assigned to the target cluster.', array( 'status' => 409 ) );
			}
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$tenant_id = $this->get_tenant_id();
		$source_cluster_id = '' !== $requested_source_cluster_id ? $requested_source_cluster_id : wp_generate_uuid4();
		$restored_label = $source_label ? sanitize_text_field( (string) $source_label ) : '';
		$target_member_count = $this->members_repository->count_for_cluster( $target_cluster_id );

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		if ( $this->clusters_repository->create_local_cluster( $tenant_id, $source_cluster_id, $restored_label, count( $sanitized_ids ) ) <= 0 ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not create restored local cluster projection.', array( 'status' => 500 ) );
		}

		$moved_rows = 0;
		foreach ( $sanitized_ids as $identity_id ) {
			$moved_rows += $this->members_repository->reassign_to_cluster( $identity_id, $source_cluster_id );
		}

		$this->clusters_repository->update_identity_count( $target_cluster_id, max( 0, $target_member_count - $moved_rows ) );

		$payload = array(
			'tenant_id' => $tenant_id,
			'target_cluster_id' => $target_cluster_id,
			'moved_identity_ids' => $sanitized_ids,
			'user_id' => get_current_user_id(),
			'desired_source_cluster_id' => $source_cluster_id,
		);
		if ( '' !== $restored_label ) {
			$payload['source_label'] = $restored_label;
		}

		if ( ! $this->enqueue_curation_operation( 'revert_merge_cluster', $target_cluster_id, $target_cluster, $payload ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue revert-merge replay operation.', array( 'status' => 500 ) );
		}

		$this->sync_state_repository->touch_local_curation_marker( $tenant_id );

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		$this->trigger_xmp_refresh_for_cluster_ids( array( $target_cluster_id, $source_cluster_id ), 'cluster-revert-merge' );

		return new WP_REST_Response(
			array(
				'restored_cluster_id' => $source_cluster_id,
				'restored_label' => '' !== $restored_label ? $restored_label : null,
				'restored_identity_count' => $moved_rows,
				'target_cluster_id' => $target_cluster_id,
				'target_identity_count' => max( 0, $target_member_count - $moved_rows ),
				'synced' => false,
				'status' => 'pending',
			),
			200
		);
	}

	public function assign_outlier_to_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		$similarity = (float) $request->get_param( 'similarity' );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		$target_cluster = $this->clusters_repository->find_by_uuid( $cluster_id );
		if ( ! is_array( $target_cluster ) ) {
			return new WP_Error( 'target_cluster_not_found', 'Target cluster not found.', array( 'status' => 404 ) );
		}

		$existing_member = $this->members_repository->find_by_identity_uuid( $identity_id );
		if ( ! is_array( $existing_member ) ) {
			return new WP_Error( 'identity_not_found', 'Identity is not present in the local projection.', array( 'status' => 404 ) );
		}

		$source_cluster_id = sanitize_text_field( (string) ( $existing_member['cluster_uuid'] ?? '' ) );
		if ( '' === $source_cluster_id ) {
			return new WP_Error( 'missing_source_cluster_id', 'Identity is not currently assigned to a projected cluster.', array( 'status' => 409 ) );
		}

		if ( $cluster_id === $source_cluster_id ) {
			return new WP_REST_Response(
				array(
					'identity_id' => $identity_id,
					'source_cluster_id' => $source_cluster_id,
					'target_cluster_id' => $cluster_id,
					'synced' => true,
					'status' => 'acknowledged',
				),
				200
			);
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$tenant_id = $this->get_tenant_id();
		$source_member_count = $this->members_repository->count_for_cluster( $source_cluster_id );
		$target_member_count = $this->members_repository->count_for_cluster( $cluster_id );

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not start local transaction.', array( 'status' => 500 ) );
		}

		$affected_rows = $this->members_repository->reassign_to_cluster( $identity_id, $cluster_id );
		if ( $affected_rows > 0 ) {
			$this->clusters_repository->update_identity_count( $source_cluster_id, max( 0, $source_member_count - 1 ) );
			$this->clusters_repository->update_identity_count( $cluster_id, $target_member_count + 1 );
		}

		$payload = array(
			'tenant_id' => $tenant_id,
			'identity_id' => $identity_id,
			'similarity' => $similarity,
			'user_id' => get_current_user_id(),
		);

		if ( $affected_rows > 0 && ! $this->enqueue_curation_operation( 'assign_outlier_to_cluster', $cluster_id, $target_cluster, $payload ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not queue assign-outlier replay operation.', array( 'status' => 500 ) );
		}

		if ( $affected_rows > 0 ) {
			$this->sync_state_repository->touch_local_curation_marker( $tenant_id );
		}

		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', 'Could not commit local transaction.', array( 'status' => 500 ) );
		}

		if ( $affected_rows > 0 ) {
			$this->trigger_xmp_refresh_for_cluster_ids( array( $source_cluster_id, $cluster_id ), 'cluster-assign-outlier' );
		}

		return new WP_REST_Response(
			array(
				'identity_id' => $identity_id,
				'source_cluster_id' => $source_cluster_id,
				'target_cluster_id' => $cluster_id,
				'synced' => false,
				'status' => $affected_rows > 0 ? 'pending' : 'acknowledged',
			),
			200
		);
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
	 * @param array<string,mixed> $payload
	 */
	private function resolve_split_idempotency_key( WP_REST_Request $request, string $cluster_id, int $expected_base_version, array $payload ): string {
		$provided = sanitize_text_field( (string) $request->get_param( 'idempotency_key' ) );
		if ( '' !== $provided ) {
			return $provided;
		}

		$basis = wp_json_encode(
			array(
				'cluster_id'             => trim( $cluster_id ),
				'expected_base_version'  => max( 0, $expected_base_version ),
				'n_clusters'             => max( 0, (int) ( $payload['n_clusters'] ?? 0 ) ),
				'anchor_identity_id'     => trim( (string) ( $payload['anchor_identity_id'] ?? '' ) ),
				'split_mode'             => trim( (string) ( $payload['split_mode'] ?? '' ) ),
				'desired_cluster_ids'    => $this->sanitize_cluster_ids( is_array( $payload['desired_cluster_ids'] ?? null ) ? $payload['desired_cluster_ids'] : array() ),
			)
		);

		if ( ! is_string( $basis ) || '' === $basis ) {
			return wp_generate_uuid4();
		}

		$hash = md5( $basis );

		return sprintf(
			'%s-%s-%s-%s-%s',
			substr( $hash, 0, 8 ),
			substr( $hash, 8, 4 ),
			substr( $hash, 12, 4 ),
			substr( $hash, 16, 4 ),
			substr( $hash, 20, 12 )
		);
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
