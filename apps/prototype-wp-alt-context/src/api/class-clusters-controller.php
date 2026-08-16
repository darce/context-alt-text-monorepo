<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-recognition-data-source.php';
require_once __DIR__ . '/interface-clusters-host.php';
require_once __DIR__ . '/services/class-cluster-response-envelope-service.php';
require_once __DIR__ . '/services/class-cluster-projection-sync-service.php';
require_once __DIR__ . '/services/class-cluster-read-config.php';
require_once __DIR__ . '/services/class-cluster-read-dependencies.php';
require_once __DIR__ . '/services/class-cluster-read-service.php';
require_once __DIR__ . '/../sovereign/mappers/class-cluster-response-mapper.php';
require_once __DIR__ . '/../sovereign/mappers/class-member-response-mapper.php';
require_once __DIR__ . '/../sovereign/repositories/interface-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/interface-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job-factory.php';
require_once __DIR__ . '/../sovereign/class-cluster-facade.php';

use AltContext\Api\Services\ClusterProjectionSyncService;
use AltContext\Api\Services\ClusterReadConfig;
use AltContext\Api\Services\ClusterReadDependencies;
use AltContext\Api\Services\ClusterReadService;
use AltContext\Api\Services\ClusterResponseEnvelopeService;
use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function add_action;

class ClustersController extends AbstractRecognitionProxyController implements ClustersHostInterface {
	private const BOOTSTRAP_SYNC_HOOK = RecognitionDataSource::BOOTSTRAP_SYNC_HOOK;
	private const DATA_SOURCE_BACKEND_PROXY = RecognitionDataSource::BACKEND_PROXY;
	private const DATA_SOURCE_LOCAL_PROJECTION = RecognitionDataSource::LOCAL_PROJECTION;
	private const DATA_SOURCE_UNAVAILABLE = RecognitionDataSource::UNAVAILABLE;
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
	private ClusterResponseEnvelopeService $response_envelope_service;
	private ClusterProjectionSyncService $projection_sync_service;
	private ClusterReadService $read_service;

	public function __construct(
		?ClustersRepositoryInterface $clusters_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?SyncPullJobInterface $sync_pull_job = null,
		?ClusterResponseMapper $cluster_mapper = null,
		?MemberResponseMapper $member_mapper = null,
		?ClusterFacade $cluster_facade = null,
		?SyncPullJobFactory $sync_pull_job_factory = null,
		?ClusterResponseEnvelopeService $response_envelope_service = null,
		?ClusterProjectionSyncService $projection_sync_service = null,
		?ClusterReadService $read_service = null
	) {
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->sync_pull_job = $sync_pull_job;
		$this->cluster_mapper = $cluster_mapper ?? new ClusterResponseMapper();
		$this->member_mapper = $member_mapper ?? new MemberResponseMapper();
		$this->cluster_facade = $cluster_facade ?? new ClusterFacade( $this->clusters_repository, $this->members_repository );
		$this->sync_pull_job_factory = $sync_pull_job_factory;
		$this->response_envelope_service = $response_envelope_service ?? new ClusterResponseEnvelopeService( $this->cluster_mapper );
		$this->projection_sync_service = $projection_sync_service ?? new ClusterProjectionSyncService(
			$this,
			self::BOOTSTRAP_SYNC_HOOK,
			$this->clusters_repository,
			$this->members_repository,
			$this->sync_state_repository,
			$this->sync_pull_job,
			$this->sync_pull_job_factory
		);
		$this->read_service = $read_service ?? new ClusterReadService(
			$this,
			new ClusterReadDependencies(
				$this->clusters_repository,
				$this->members_repository,
				$this->cluster_facade,
				$this->cluster_mapper,
				$this->member_mapper,
				$this->projection_sync_service,
				$this->response_envelope_service,
				new ClusterReadConfig(
					self::BOOTSTRAP_SYNC_HOOK,
					self::DATA_SOURCE_BACKEND_PROXY,
					self::DATA_SOURCE_LOCAL_PROJECTION,
					self::DATA_SOURCE_UNAVAILABLE,
					self::PROJECTION_STATUS_BOOTSTRAPPING,
					self::PROJECTION_STATUS_AVAILABLE
				)
			)
		);
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
				'args'                => array(
					'limit'  => array(
						'description'       => 'Maximum members to return (capped server-side).',
						'type'              => 'integer',
						'required'          => false,
						'sanitize_callback' => 'absint',
					),
					'offset' => array(
						'description'       => 'Number of members to skip before returning results.',
						'type'              => 'integer',
						'required'          => false,
						'sanitize_callback' => 'absint',
					),
				),
			)
		);
	}

	public function list_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->read_service->list_clusters( $request );
	}

	public function list_top_unlabeled_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->read_service->list_top_unlabeled_clusters( $request );
	}

	public function list_cluster_labels( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->read_service->list_cluster_labels( $request );
	}

	public function get_cluster_detail( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->read_service->get_cluster_detail( $request );
	}

	public function get_cluster_members( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->read_service->get_cluster_members( $request );
	}

	public function perform_bootstrap_sync( string $tenant_id ): void {
		$this->projection_sync_service->perform_bootstrap_sync( $tenant_id );
	}

	public function get_clusters_repository(): ClustersRepositoryInterface {
		return $this->clusters_repository;
	}

	public function get_sync_state_repository(): SyncStateRepositoryInterface {
		return $this->sync_state_repository;
	}

	public function get_tenant_id(): string {
		return parent::get_tenant_id();
	}

	/**
	 * @param array<string,mixed> $body
	 * @param array<string,mixed> $query
	 */
	public function proxy_recognition_request(
		string $method,
		string $path,
		array $body = array(),
		array $query = array(),
		string $request_class = 'auto',
		string $body_kind = 'json',
		?int $max_body_bytes = null
	): WP_REST_Response|WP_Error {
		return $this->proxy_request( $method, $path, $body, $query, $request_class, $body_kind, $max_body_bytes );
	}

	public function host_should_use_local_projection_gate(
		SyncStateRepositoryInterface $sync_state_repository,
		string $tenant_id
	): bool {
		return $this->should_use_local_projection_gate( $sync_state_repository, $tenant_id );
	}

	public function host_is_projection_stale( ?string $updated_at ): bool {
		return $this->is_projection_stale( $updated_at );
	}
}
