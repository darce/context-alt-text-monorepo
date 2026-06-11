<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersHostInterface;
use AltContext\Api\Services\ClusterProjectionSyncService;
use AltContext\Api\Services\ClusterReadDependencies;
use AltContext\Api\Services\ClusterReadService;
use AltContext\Api\Services\ClusterResponseEnvelopeService;
use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterReadService
 */
class ClusterReadServiceTest extends TestCase
{
    private const BOOTSTRAP_HOOK = 'acx_bootstrap_sync_test';

    public function testListTopUnlabeledProxyBootstrappingFallbackEnvelope(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $host = new class() implements ClustersHostInterface {
            public function get_tenant_id(): string
            {
                return 'tenant-1';
            }

            public function proxy_recognition_request(
                string $method,
                string $path,
                array $body = [],
                array $query = [],
                string $request_class = 'auto',
                string $body_kind = 'json',
                ?int $max_body_bytes = null
            ): WP_REST_Response|WP_Error {
                return new WP_Error('upstream_unavailable', 'Recognition service unavailable.', ['status' => 503]);
            }

            public function host_should_use_local_projection_gate(
                SyncStateRepositoryInterface $sync_state_repository,
                string $tenant_id
            ): bool {
                return false;
            }

            public function host_is_projection_stale(?string $updated_at): bool
            {
                return false;
            }
        };

        $service = $this->makeService($host, use_local_projection: false);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $request->set_param('limit', 5);

        $response = $service->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame([], $data['clusters']);
        $this->assertSame(5, $data['limit']);
        $this->assertSame(0, $data['total']);
        $this->assertFalse($data['truncated']);
        $this->assertSame(0, $data['singleton_count']);
        $this->assertSame('unavailable', $data['data_source']);
        $this->assertSame('bootstrapping', $data['projection_status']);
        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
    }

    public function testListClusterLabelsLocalProjectionUsesEnvelopeService(): void
    {
        $labelsRepo = new class() extends NullClustersRepository {
            public function list_labels(string $tenant_id, string $search = '', int $limit = self::DEFAULT_LIST_LIMIT): array
            {
                return [
                    ['label' => 'Alice', 'total_count' => 2],
                ];
            }
        };

        $host = new class() implements ClustersHostInterface {
            public function get_tenant_id(): string
            {
                return 'tenant-1';
            }

            public function proxy_recognition_request(
                string $method,
                string $path,
                array $body = [],
                array $query = [],
                string $request_class = 'auto',
                string $body_kind = 'json',
                ?int $max_body_bytes = null
            ): WP_REST_Response|WP_Error {
                return new WP_REST_Response([], 200);
            }

            public function host_should_use_local_projection_gate(
                SyncStateRepositoryInterface $sync_state_repository,
                string $tenant_id
            ): bool {
                return true;
            }

            public function host_is_projection_stale(?string $updated_at): bool
            {
                return false;
            }
        };

        $service = $this->makeService($host, use_local_projection: true, clusters_repository: $labelsRepo);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/labels');
        $request->set_param('limit', 10);

        $response = $service->list_cluster_labels($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame(['Alice'], $data['labels']);
        $this->assertSame(10, $data['limit']);
        $this->assertSame(2, $data['total']);
        $this->assertTrue($data['truncated']);
    }

    private function makeService(
        ClustersHostInterface $host,
        bool $use_local_projection,
        ?NullClustersRepository $clusters_repository = null
    ): ClusterReadService {
        $syncHost = new class($use_local_projection) implements ClustersHostInterface {
            public function __construct(private bool $use_local_projection) {}

            public function get_tenant_id(): string
            {
                return 'tenant-1';
            }

            public function proxy_recognition_request(
                string $method,
                string $path,
                array $body = [],
                array $query = [],
                string $request_class = 'auto',
                string $body_kind = 'json',
                ?int $max_body_bytes = null
            ): WP_REST_Response|WP_Error {
                return new WP_REST_Response([], 200);
            }

            public function host_should_use_local_projection_gate(
                SyncStateRepositoryInterface $sync_state_repository,
                string $tenant_id
            ): bool {
                return $this->use_local_projection;
            }

            public function host_is_projection_stale(?string $updated_at): bool
            {
                return false;
            }
        };

        $syncJob = new class() implements SyncPullJobInterface {
            public function perform(string $tenant_id): SyncPullResult
            {
                return SyncPullResult::ok();
            }

            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
            {
                return SyncPullResult::ok();
            }

            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
            {
                return SyncPullResult::ok();
            }
        };

        $clustersRepo = $clusters_repository ?? new NullClustersRepository();
        $membersRepo = new NullIdentityMembersRepository();

        $projectionSync = new ClusterProjectionSyncService(
            $syncHost,
            self::BOOTSTRAP_HOOK,
            $clustersRepo,
            $membersRepo,
            new NullSyncStateRepository(),
            $syncJob,
            null
        );

        $dependencies = new ClusterReadDependencies(
            $clustersRepo,
            $membersRepo,
            new ClusterFacade($clustersRepo, $membersRepo),
            new ClusterResponseMapper(),
            new MemberResponseMapper(),
            $projectionSync,
            new ClusterResponseEnvelopeService(),
            self::BOOTSTRAP_HOOK,
            'backend_proxy',
            'local_projection',
            'unavailable',
            'bootstrapping',
            'available'
        );

        return new ClusterReadService($host, $dependencies);
    }
}