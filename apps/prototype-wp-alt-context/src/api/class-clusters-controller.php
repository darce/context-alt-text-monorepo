<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/../sovereign/mappers/class-cluster-response-mapper.php';
require_once __DIR__ . '/../sovereign/mappers/class-member-response-mapper.php';
require_once __DIR__ . '/../sovereign/repositories/interface-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/interface-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/sync/interface-snapshot-projector.php';
require_once __DIR__ . '/../sovereign/sync/class-snapshot-client.php';
require_once __DIR__ . '/../sovereign/sync/class-snapshot-projector.php';
require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-result.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job-factory.php';
require_once __DIR__ . '/../sovereign/class-cluster-facade.php';

use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJob;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function add_action;
use function absint;
use function do_action;
use function is_array;
use function is_string;
use function max;
use function min;
use function rest_sanitize_boolean;
use function sanitize_text_field;
use function sprintf;
use function time;
use function trim;
use function wp_get_attachment_url;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class ClustersController extends AbstractRecognitionProxyController {
	private const BOOTSTRAP_SYNC_HOOK = 'acx_bootstrap_sync';
	private const DATA_SOURCE_BACKEND_PROXY = 'backend_proxy';
	private const DATA_SOURCE_LOCAL_PROJECTION = 'local_projection';
	private const DATA_SOURCE_UNAVAILABLE = 'unavailable';
	private const PROJECTION_STATUS_AVAILABLE = 'available';
	private const PROJECTION_STATUS_BOOTSTRAPPING = 'bootstrapping';
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private ?SyncPullJobInterface $sync_pull_job;
	private ?SyncPullJobFactory $sync_pull_job_factory;
	private ClusterResponseMapper $cluster_mapper;
	private MemberResponseMapper $member_mapper;
	private ClusterFacade $cluster_facade;

	public function __construct(
		?ClustersRepositoryInterface $clusters_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?SyncPullJobInterface $sync_pull_job = null,
		?ClusterResponseMapper $cluster_mapper = null,
		?MemberResponseMapper $member_mapper = null,
		?ClusterFacade $cluster_facade = null,
		?SyncPullJobFactory $sync_pull_job_factory = null
	) {
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->sync_pull_job = $sync_pull_job;
		$this->cluster_mapper = $cluster_mapper ?? new ClusterResponseMapper();
		$this->member_mapper = $member_mapper ?? new MemberResponseMapper();
		$this->cluster_facade = $cluster_facade ?? new ClusterFacade( $this->clusters_repository, $this->members_repository );
		$this->sync_pull_job_factory = $sync_pull_job_factory;
		add_action( self::BOOTSTRAP_SYNC_HOOK, array( $this, 'perform_bootstrap_sync' ), 10, 1 );
	}

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
		$tenant_id = $this->get_tenant_id();
		$limit  = absint( $request->get_param( 'limit' ) ?? 50 );
		$limit  = min( $limit, 500 );
		$search = sanitize_text_field( (string) $request->get_param( 'search' ) );
		$labeled_only = rest_sanitize_boolean( $request->get_param( 'labeled_only' ) );

		if ( $this->should_use_local_projection( $tenant_id ) ) {
			$rows = $this->clusters_repository->list_for_tenant(
				$tenant_id,
				$limit,
				absint( $request->get_param( 'offset' ) ?? 0 ),
				array(
					'search' => $search,
					'labeled_only' => $labeled_only,
				)
			);

			$members_by_cluster = $this->load_members_by_cluster( $rows, 4 );
			$clusters = $this->cluster_mapper->map_cluster_list( $rows, $members_by_cluster );

			return new WP_REST_Response( $clusters, 200 );
		}

		$query = array(
			'tenant_id' => $tenant_id,
			'limit'     => $limit,
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		);

		if ( $labeled_only ) {
			$query['labeled_only'] = 'true';
		}

		if ( '' !== $search ) {
			$query['search'] = $search;
		}

		$response = $this->proxy_request( 'GET', '/recognition/clusters', array(), $query );
		return $this->maybe_bootstrap_after_proxy_read( $tenant_id, $response );
	}

	public function list_top_unlabeled_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$limit     = absint( $request->get_param( 'limit' ) ?? 10 );

		if ( ! $this->should_use_local_projection( $tenant_id ) ) {
			$response = $this->proxy_request(
				'GET',
				'/recognition/clusters/top-unlabeled',
				array(),
				array(
					'tenant_id' => $tenant_id,
					'limit'     => $limit,
				)
			);
			$response = $this->maybe_bootstrap_after_proxy_read( $tenant_id, $response );

			if ( $response instanceof WP_REST_Response && $response->get_status() >= 200 && $response->get_status() < 300 ) {
				$data = $response->get_data();
				if ( is_array( $data ) ) {
					return new WP_REST_Response(
						array(
							'clusters'    => $data,
							'data_source' => self::DATA_SOURCE_BACKEND_PROXY,
						),
						200
					);
				}
			}

			$args = array( $tenant_id );
			if ( false === wp_next_scheduled( self::BOOTSTRAP_SYNC_HOOK, $args ) ) {
				wp_schedule_single_event( time(), self::BOOTSTRAP_SYNC_HOOK, $args );
			}
			return new WP_REST_Response(
				array(
					'clusters'          => array(),
					'singleton_count'   => 0,
					'data_source'       => self::DATA_SOURCE_UNAVAILABLE,
					'projection_status' => self::PROJECTION_STATUS_BOOTSTRAPPING,
				),
				200
			);
		}

		$sovereign_data = $this->cluster_facade->list_top_unlabeled( $tenant_id, $limit );
		$unlabeled_items = $this->cluster_mapper->map_top_unlabeled_clusters(
			$sovereign_data['clusters'],
			$sovereign_data['members'],
			$tenant_id
		);

		return new WP_REST_Response(
			array(
				'clusters' => $unlabeled_items,
				'singleton_count' => max( 0, (int) ( $sovereign_data['singleton_count'] ?? 0 ) ),
				'data_source' => self::DATA_SOURCE_LOCAL_PROJECTION,
				'projection_status' => self::PROJECTION_STATUS_AVAILABLE,
			),
			200
		);
	}

	public function list_cluster_labels( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		if ( $this->should_use_local_projection( $tenant_id ) ) {
			$labels = $this->clusters_repository->list_labels( $tenant_id );
			$payload = $this->cluster_mapper->map_labels_list( $labels );
			return new WP_REST_Response( $payload, 200 );
		}

		$query = array(
			'tenant_id' => $tenant_id,
		);

		$response = $this->proxy_request( 'GET', '/recognition/clusters/labels', array(), $query );
		return $this->maybe_bootstrap_after_proxy_read( $tenant_id, $response );
	}

	public function get_cluster_detail( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $this->should_use_local_projection( $tenant_id ) ) {
			$cluster_row = $this->clusters_repository->find_by_uuid( $cluster_id );
			if ( is_array( $cluster_row ) ) {
				$members = $this->members_repository->list_for_cluster( $cluster_id, 500, 0, $tenant_id );
				$payload = $this->cluster_mapper->map_cluster_detail( $cluster_row, $members );
				return new WP_REST_Response( $payload, 200 );
			}

			// Local projection is authoritative, but cluster not found
			return new WP_Error(
				'cluster_not_found',
				sprintf( 'Cluster %s not found.', $cluster_id ),
				array( 'status' => 404 )
			);
		}

		$response = $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s', $cluster_id ),
			array(),
			array( 'tenant_id' => $tenant_id )
		);
		return $this->maybe_bootstrap_after_proxy_read( $tenant_id, $response );
	}

	public function get_cluster_members( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( $this->should_use_local_projection( $tenant_id ) ) {
			// Verify cluster exists before listing members
			$cluster_row = $this->clusters_repository->find_by_uuid( $cluster_id );
			if ( ! is_array( $cluster_row ) ) {
				return new WP_Error(
					'cluster_not_found',
					sprintf( 'Cluster %s not found.', $cluster_id ),
					array( 'status' => 404 )
				);
			}

			$members = $this->members_repository->list_for_cluster( $cluster_id, 500, 0, $tenant_id );
			$payload = $this->member_mapper->map_cluster_members( $members );
			return new WP_REST_Response( $payload, 200 );
		}

		$response = $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s/members', $cluster_id ),
			array(),
			array( 'tenant_id' => $tenant_id )
		);
		return $this->maybe_bootstrap_after_proxy_read( $tenant_id, $response );
	}

	public function perform_bootstrap_sync( string $tenant_id ): void {
		$sync_pull_job = $this->resolve_sync_pull_job();
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id || null === $sync_pull_job ) {
			return;
		}

		$sync_pull_job->perform_bypass_cooldown( $normalized_tenant_id );
	}

	public function get_clusters_repository(): ClustersRepositoryInterface {
		return $this->clusters_repository;
	}

	public function get_sync_state_repository(): SyncStateRepositoryInterface {
		return $this->sync_state_repository;
	}

	/**
	 * @param array<int,array<string,mixed>> $cluster_rows
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	private function load_members_by_cluster( array $cluster_rows, int $limit ): array {
		// Extract cluster UUIDs for batch query
		$cluster_uuids = array();
		foreach ( $cluster_rows as $row ) {
			$cluster_id = sanitize_text_field( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' !== $cluster_id ) {
				$cluster_uuids[] = $cluster_id;
			}
		}

		if ( empty( $cluster_uuids ) ) {
			return array();
		}

		// Batch query all members at once
		return $this->members_repository->list_for_cluster_uuids( $cluster_uuids, $limit );
	}

	private function should_use_local_projection( string $tenant_id ): bool {
		$has_projection = $this->should_use_local_projection_gate( $this->sync_state_repository, $tenant_id );
		if ( ! $has_projection ) {
			return false;
		}

		// If projection is stale, attempt on-demand sync.
		// Wrap in try/catch so a projector failure degrades to stale data
		// instead of crashing the request.
		$updated_at    = $this->sync_state_repository->get_last_updated( $tenant_id );
		$sync_pull_job = $this->resolve_sync_pull_job();
		if ( $this->is_projection_stale( $updated_at ) && null !== $sync_pull_job ) {
			try {
				$sync_pull_job->perform( $tenant_id );
			} catch ( \Throwable $e ) {
				do_action(
					'acx_sync_pull_failed',
					array(
						'tenant_id' => $tenant_id,
						'context' => 'stale_projection_read',
						'message' => $e->getMessage(),
					)
				);
			}
		}

		return true;
	}

	private function maybe_bootstrap_after_proxy_read( string $tenant_id, WP_REST_Response|WP_Error $response ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( $response->get_status() < 200 || $response->get_status() >= 300 ) {
			return $response;
		}

		$sync_pull_job = $this->resolve_sync_pull_job();
		if ( null === $sync_pull_job ) {
			return $response;
		}

		$inline_result = $sync_pull_job->perform_bypass_cooldown( $tenant_id );
		if ( ! $inline_result->is_success() ) {
			$args = array( $tenant_id );
			if ( false === wp_next_scheduled( self::BOOTSTRAP_SYNC_HOOK, $args ) ) {
				wp_schedule_single_event( time(), self::BOOTSTRAP_SYNC_HOOK, $args );
			}
		}

		return $response;
	}

	private function resolve_sync_pull_job(): ?SyncPullJobInterface {
		if ( null !== $this->sync_pull_job ) {
			return $this->sync_pull_job;
		}

		try {
			$factory = $this->sync_pull_job_factory ?? new SyncPullJobFactory(
				$this->clusters_repository,
				$this->members_repository,
				$this->sync_state_repository,
				new SnapshotClient()
			);
			$this->sync_pull_job = $factory->create();
		} catch ( \Throwable $e ) {
			do_action(
				'acx_recognition_composition_failed',
				array(
					'message' => $e->getMessage(),
					'controller' => __CLASS__,
					'context' => 'clusters_lazy_sync_pull_job',
				)
			);
			return null;
		}

		return $this->sync_pull_job;
	}
}
