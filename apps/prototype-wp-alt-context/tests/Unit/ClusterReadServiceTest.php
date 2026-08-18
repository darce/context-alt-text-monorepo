<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersHostInterface;
use AltContext\Api\Services\ClusterProjectionSyncService;
use AltContext\Api\Services\ClusterReadConfig;
use AltContext\Api\Services\ClusterReadDependencies;
use AltContext\Api\Services\ClusterReadService;
use AltContext\Api\Services\ClusterResponseEnvelopeService;
use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\Stubs\SpySyncPullJob;
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

    public function testListTopUnlabeledSchedulesRepairFromMapperRequestedIds(): void
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
                return new WP_Error('unexpected', 'must stay local');
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

        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-upward',
                        'label' => '',
                        'identity_count' => 2,
                        'is_user_confirmed' => 0,
                    ],
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [
                    'cluster-upward' => [
                        ['identity_uuid' => 'id-1', 'attachment_id' => 1],
                        ['identity_uuid' => 'id-2', 'attachment_id' => 2],
                        ['identity_uuid' => 'id-3', 'attachment_id' => 3],
                        ['identity_uuid' => 'id-4', 'attachment_id' => 4],
                    ],
                ];
            }
        };

        $syncJob = new SpySyncPullJob();
        $service = $this->makeService(
            $host,
            use_local_projection: true,
            clusters_repository: $clustersRepo,
            sync_pull_job: $syncJob,
            members_repository: $membersRepo
        );

        $response = $service->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(4, $response->get_data()['clusters'][0]['identity_count']);
        $this->assertSame([], $syncJob->performCalls);
        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
        $scheduled = array_values($GLOBALS['__ac_scheduled'])[0];
        $this->assertSame(['tenant-1', ['cluster-upward']], $scheduled['args']);
    }

    /**
     * R2-06: envelope total/truncated describe the served list, not pre-drop COUNT(*).
     */
    public function testListTopUnlabeledEnvelopeDoesNotReportFilterAsPagingTruncation(): void
    {
        $host = $this->localHost();

        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-drop',
                        'label' => '',
                        'identity_count' => 7,
                        'is_user_confirmed' => 0,
                        'total_count' => 2,
                    ],
                    [
                        'cluster_uuid' => 'cluster-keep',
                        'label' => '',
                        'identity_count' => 2,
                        'is_user_confirmed' => 0,
                        'total_count' => 2,
                    ],
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [
                    'cluster-drop' => [],
                    'cluster-keep' => [
                        ['identity_uuid' => 'id-1', 'attachment_id' => 1],
                        ['identity_uuid' => 'id-2', 'attachment_id' => 2],
                    ],
                ];
            }
        };

        $service = $this->makeService(
            $host,
            use_local_projection: true,
            clusters_repository: $clustersRepo,
            members_repository: $membersRepo
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $request->set_param('limit', 10);
        $response = $service->list_top_unlabeled_clusters($request);
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertCount(1, $data['clusters']);
        $this->assertSame('cluster-keep', $data['clusters'][0]['id']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
    }

    /**
     * R2-11: drift ids for clusters absent from this page merge into the repair event.
     */
    public function testListTopUnlabeledMergesOffPageDriftIdsIntoRepairEvent(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $host = $this->localHost();

        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-page',
                        'label' => '',
                        'identity_count' => 2,
                        'is_user_confirmed' => 0,
                    ],
                ];
            }

            public function list_unlabeled_identity_count_drift(string $tenant_id, int $limit = 50): array
            {
                return ['cluster-off-page'];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [
                    'cluster-page' => [
                        ['identity_uuid' => 'id-1', 'attachment_id' => 1],
                        ['identity_uuid' => 'id-2', 'attachment_id' => 2],
                        ['identity_uuid' => 'id-3', 'attachment_id' => 3],
                        ['identity_uuid' => 'id-4', 'attachment_id' => 4],
                    ],
                ];
            }
        };

        $service = $this->makeService(
            $host,
            use_local_projection: true,
            clusters_repository: $clustersRepo,
            members_repository: $membersRepo
        );

        $response = $service->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
        $scheduled = array_values($GLOBALS['__ac_scheduled'])[0];
        $this->assertSame('tenant-1', $scheduled['args'][0]);
        $this->assertEqualsCanonicalizing(['cluster-off-page', 'cluster-page'], $scheduled['args'][1]);
    }

    /**
     * R2-09: overlapping large repair sets collide after sort+cap.
     */
    public function testListTopUnlabeledCapsAndCollidesOverlappingRepairBatches(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $host = $this->localHost();
        $call = 0;

        $clustersRepo = new class($call) extends NullClustersRepository {
            public function __construct(private int &$call)
            {
            }

            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return [];
            }

            public function list_unlabeled_identity_count_drift(string $tenant_id, int $limit = 50): array
            {
                ++$this->call;
                $ids = [];
                for ($i = 1; $i <= 25; $i++) {
                    $ids[] = sprintf('cluster-%02d', $i);
                }
                $ids[] = $this->call === 1 ? 'cluster-extra-a' : 'cluster-extra-b';
                return $ids;
            }
        };

        $service = $this->makeService(
            $host,
            use_local_projection: true,
            clusters_repository: $clustersRepo
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $service->list_top_unlabeled_clusters($request);
        $service->list_top_unlabeled_clusters($request);

        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
        $scheduled = array_values($GLOBALS['__ac_scheduled'])[0];
        $this->assertCount(ClusterReadService::TARGETED_REPAIR_ID_CEILING, $scheduled['args'][1]);
    }

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

    public function testListClustersWipeClassServesLocalWithAsyncHealAndZeroSynchronousHttp(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $host = new class() implements ClustersHostInterface {
            /** @var list<string> */
            public array $proxy_calls = [];

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
                $this->proxy_calls[] = $path;
                return new WP_Error('unexpected_proxy_call', 'Wipe-class local read must not proxy.', ['status' => 500]);
            }

            public function host_should_use_local_projection_gate(
                SyncStateRepositoryInterface $sync_state_repository,
                string $tenant_id
            ): bool {
                return false;
            }

            public function host_is_projection_stale(?string $updated_at): bool
            {
                return true;
            }
        };

        $rowsRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
            {
                return [
                    ['cluster_uuid' => 'cluster-1', 'label' => 'Alice', 'identity_count' => 2, 'total_count' => 1],
                ];
            }
        };

        $syncJob = new SpySyncPullJob();
        $service = $this->makeService(
            $host,
            use_local_projection: false,
            clusters_repository: $rowsRepo,
            sync_pull_job: $syncJob
        );
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $request->set_param('limit', 10);

        $response = $service->list_clusters($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertCount(1, $data['clusters']);
        $this->assertSame(1, $data['total']);
        $this->assertSame([], $host->proxy_calls, 'Sync-state wipe with surviving rows must serve local, never proxy.');
        $this->assertSame([], $syncJob->performCalls, 'Newly-qualifying read must not run an inline pull.');
        $this->assertSame([], $syncJob->bypassCalls);
        $this->assertCount(2, $GLOBALS['__ac_scheduled']);
        $args = array_column(array_values($GLOBALS['__ac_scheduled']), 'args');
        $this->assertContains(['tenant-1'], $args);
        $this->assertContains(['tenant-1', ['cluster-1']], $args);
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

    private function localHost(): ClustersHostInterface
    {
        return new class() implements ClustersHostInterface {
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
                return new WP_Error('unexpected', 'must stay local');
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
    }

    private function makeService(
        ClustersHostInterface $host,
        bool $use_local_projection,
        ?NullClustersRepository $clusters_repository = null,
        ?SyncPullJobInterface $sync_pull_job = null,
        ?NullIdentityMembersRepository $members_repository = null
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

        $syncJob = $sync_pull_job ?? new SpySyncPullJob();

        $clustersRepo = $clusters_repository ?? new NullClustersRepository();
        $membersRepo = $members_repository ?? new NullIdentityMembersRepository();

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
            new ClusterReadConfig(
                self::BOOTSTRAP_HOOK,
                'backend_proxy',
                'local_projection',
                'unavailable',
                'bootstrapping',
                'available'
            )
        );

        return new ClusterReadService($host, $dependencies);
    }
}
