<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/interface-cluster-mutation-host.php';
require_once __DIR__ . '/../support/trait-runs-transactional.php';
require_once __DIR__ . '/services/class-person-resolution-service.php';
require_once __DIR__ . '/services/class-cluster-label-service.php';
require_once __DIR__ . '/services/class-cluster-lifecycle-service.php';
require_once __DIR__ . '/services/class-cluster-merge-service.php';
require_once __DIR__ . '/services/class-cluster-split-service.php';
require_once __DIR__ . '/services/class-cluster-membership-service.php';
require_once __DIR__ . '/services/class-cluster-representative-service.php';
require_once __DIR__ . '/../sovereign/class-projection-query-exception.php';
require_once __DIR__ . '/../sovereign/sync/interface-outbox-writer.php';
require_once __DIR__ . '/../sovereign/sync/class-outbox-writer.php';
require_once __DIR__ . '/../sovereign/sync/class-curation-idempotency-key.php';
require_once __DIR__ . '/../sovereign/sync/interface-topology-command-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-topology-command-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-split-topology-command-drain.php';

use AltContext\Api\Services\ClusterLabelService;
use AltContext\Api\Services\ClusterLifecycleService;
use AltContext\Api\Services\ClusterMembershipService;
use AltContext\Api\Services\ClusterMergeService;
use AltContext\Api\Services\ClusterRepresentativeService;
use AltContext\Api\Services\ClusterSplitService;
use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\CurationIdempotencyKey;
use AltContext\Sovereign\Sync\OutboxWriter;
use AltContext\Sovereign\Sync\OutboxWriterInterface;
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
use function in_array;
use function is_array;
use function max;
use function md5;
use function sanitize_text_field;
use function sprintf;
use function substr;
use function time;
use function trim;
use function wp_generate_uuid4;
use function wp_json_encode;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class ClusterMutationsController extends AbstractRecognitionProxyController implements ClusterMutationHostInterface {
	private const XMP_REFRESH_CLUSTER_HOOK = 'acx_refresh_xmp_for_clusters';
	private const XMP_REFRESH_DELAY_SECONDS = 1;
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private OutboxWriterInterface $outbox_writer;
	private TopologyCommandRepositoryInterface $topology_command_repository;
	private ClusterLabelService $label_service;
	private ClusterLifecycleService $lifecycle_service;
	private ClusterMergeService $merge_service;
	private ClusterSplitService $split_service;
	private ClusterMembershipService $membership_service;
	private ClusterRepresentativeService $representative_service;

	public function __construct(
		?ClustersRepositoryInterface $clusters_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?OutboxWriterInterface $outbox_writer = null,
		?TopologyCommandRepositoryInterface $topology_command_repository = null,
		?ClusterLabelService $label_service = null,
		?ClusterLifecycleService $lifecycle_service = null,
		?ClusterMergeService $merge_service = null,
		?ClusterSplitService $split_service = null,
		?ClusterMembershipService $membership_service = null,
		?ClusterRepresentativeService $representative_service = null
	) {
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->outbox_writer = $outbox_writer ?? new OutboxWriter();
		$this->topology_command_repository = $topology_command_repository ?? new TopologyCommandRepository();
		$this->label_service = $label_service ?? new ClusterLabelService( $this, $this->clusters_repository, $this->sync_state_repository );
		$this->lifecycle_service = $lifecycle_service ?? new ClusterLifecycleService( $this, $this->clusters_repository );
		$this->merge_service = $merge_service ?? new ClusterMergeService( $this, $this->clusters_repository, $this->members_repository, $this->sync_state_repository );
		$this->split_service = $split_service ?? new ClusterSplitService( $this, $this->sync_state_repository, $this->topology_command_repository );
		$this->membership_service = $membership_service ?? new ClusterMembershipService( $this, $this->clusters_repository, $this->members_repository, $this->sync_state_repository );
		$this->representative_service = $representative_service ?? new ClusterRepresentativeService( $this, $this->clusters_repository, $this->sync_state_repository );
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

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/representatives/(?P<representative_id>[a-f0-9-]+)/pin',
			array(
				'methods'             => 'PATCH',
				'callback'            => array( $this, 'pin_representative' ),
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
		return $this->run_mutation( 'reassign_cluster_identity', function () use ( $request ) {
			return $this->membership_service->reassign_cluster_identity( $request );
		} );
	}

	public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->run_mutation( 'update_cluster_label', function () use ( $request ) {
			return $this->label_service->update_cluster_label( $request );
		} );
	}

	public function dismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->run_mutation( 'dismiss_cluster', function () use ( $request ) {
			return $this->lifecycle_service->dismiss_cluster( $request );
		} );
	}

	public function undismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->run_mutation( 'undismiss_cluster', function () use ( $request ) {
			return $this->lifecycle_service->undismiss_cluster( $request );
		} );
	}

	public function merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->run_mutation( 'merge_cluster', function () use ( $request ) {
			return $this->merge_service->merge_cluster( $request );
		} );
	}

	public function split_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->run_mutation( 'split_cluster', function () use ( $request ) {
			return $this->split_service->split_cluster( $request );
		} );
	}

	public function create_cluster_for_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->run_mutation( 'create_cluster_for_identity', function () use ( $request ) {
			return $this->membership_service->create_cluster_for_identity( $request );
		} );
	}

	public function revert_merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->run_mutation( 'revert_merge_cluster', function () use ( $request ) {
			return $this->merge_service->revert_merge_cluster( $request );
		} );
	}

	public function assign_outlier_to_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->run_mutation( 'assign_outlier_to_cluster', function () use ( $request ) {
			return $this->membership_service->assign_outlier_to_cluster( $request );
		} );
	}

	public function pin_representative( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->run_mutation( 'pin_representative', function () use ( $request ) {
			return $this->representative_service->pin_representative( $request );
		} );
	}

	public function get_tenant_id(): string {
		return parent::get_tenant_id();
	}

	/**
	 * Hard-fail on projection probe errors (do not fall back to backend proxy).
	 * A failed local read cannot be trusted as "empty projection"; proxying would
	 * risk split-brain writes against a broken local state (RLSE-05 / E21-14-BR-04).
	 */
	public function should_proxy_mutation_to_backend( string $tenant_id ): bool {
		return ! $this->clusters_repository->has_projection_rows_for_tenant( $tenant_id )
			&& ! $this->members_repository->has_projection_rows_for_tenant( $tenant_id );
	}

	/**
	 * @param callable(): (WP_REST_Response|WP_Error) $callback
	 */
	private function run_mutation( string $surface, callable $callback ): WP_REST_Response|WP_Error {
		try {
			return $callback();
		} catch ( ProjectionQueryException $exception ) {
			return ProjectionQueryException::to_rest_error( $surface );
		}
	}

	public function proxy_cluster_mutation(
		string $method,
		string $path,
		array $body = array()
	): WP_REST_Response|WP_Error {
		$response = $this->proxy_request( $method, $path, $body, array(), 'mutation' );
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}

		return $response;
	}

	public function get_projected_cluster_or_error(
		string $cluster_id,
		string $missing_code = 'cluster_not_found',
		string $missing_message = 'Cluster not found.'
	): array|WP_Error {
		$cluster = $this->clusters_repository->find_by_uuid( $cluster_id );
		if ( is_array( $cluster ) ) {
			return $cluster;
		}

		if ( ! $this->clusters_repository->has_projection_rows_for_tenant( $this->get_tenant_id() ) ) {
			return new WP_Error(
				'projection_not_ready',
				'Local projection is not ready for curation yet. Retry sync and try again.',
				array( 'status' => 409 )
			);
		}

		return new WP_Error( $missing_code, $missing_message, array( 'status' => 404 ) );
	}

	public function enqueue_curation_operation(
		string $operation_type,
		string $entity_key,
		array $context_row,
		array $payload = array(),
		string $entity_type = 'cluster'
	): bool {
		$tenant_id = trim( $this->get_tenant_id() );
		if ( '' === $tenant_id ) {
			return false;
		}

		$resolved_payload = ! empty( $payload ) ? $payload : array(
			'cluster_uuid' => $entity_key,
		);
		$snapshot_version = max( 0, (int) ( $context_row['snapshot_version'] ?? $this->sync_state_repository->get_snapshot_version( $tenant_id ) ) );
		$target_revision  = max( 1, (int) ( $context_row['local_revision'] ?? 0 ) + 1 );
		$result           = $this->outbox_writer->enqueue(
			$tenant_id,
			$operation_type,
			$entity_type,
			$entity_key,
			$snapshot_version,
			$target_revision,
			$resolved_payload,
			$this->derive_curation_idempotency_key( $tenant_id, $operation_type, $entity_type, $entity_key, $target_revision, $resolved_payload )
		);

		return false !== $result;
	}

	/**
	 * Deterministic idempotency key for a curation operation so a double-submit (or a retried
	 * request whose response was lost) collapses to a single outbox row via uq_idempotency,
	 * mirroring resolve_split_idempotency_key. A genuinely distinct operation (different entity
	 * or a newer local revision) yields a different key and is enqueued normally.
	 *
	 * Thin delegate to the shared CurationIdempotencyKey helper (E15-35 Slice 3);
	 * existing keys stay byte-identical (characterization-tested).
	 *
	 * @param array<string,mixed> $payload
	 */
	private function derive_curation_idempotency_key( string $tenant_id, string $operation_type, string $entity_type, string $entity_key, int $target_revision, array $payload ): string {
		return CurationIdempotencyKey::derive( $tenant_id, $operation_type, $entity_type, $entity_key, $target_revision, $payload );
	}

	public function trigger_xmp_refresh_for_cluster_ids( array $cluster_ids, string $context ): void {
		$normalized_cluster_ids = $this->sanitize_cluster_ids( $cluster_ids );
		if ( empty( $normalized_cluster_ids ) ) {
			return;
		}

		$args = array( $normalized_cluster_ids, $context );
		if ( false === wp_next_scheduled( self::XMP_REFRESH_CLUSTER_HOOK, $args ) ) {
			wp_schedule_single_event( time() + self::XMP_REFRESH_DELAY_SECONDS, self::XMP_REFRESH_CLUSTER_HOOK, $args );
		}
	}

	public function resolve_split_idempotency_key(
		WP_REST_Request $request,
		string $cluster_id,
		int $expected_base_version,
		array $payload
	): string {
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

		return $this->format_idempotency_key( $basis );
	}

	private function format_idempotency_key( string $basis ): string {
		return CurationIdempotencyKey::format( $basis );
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
			do_action( 'acx_xmp_refresh_requested', $media_id, $context );
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
