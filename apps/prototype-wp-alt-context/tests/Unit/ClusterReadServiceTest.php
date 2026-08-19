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
use AltContext\Tests\Support\TopUnlabeledSchemaValidator;
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

    /** @var (ClusterProjectionSyncService&object{repairCalls: list<array<int,mixed>>})|null */
    private ?ClusterProjectionSyncService $countingSync = null;

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
     * R5-12: count repair at the service seam. Cron-layer observers
     * overwrite on the same hook+args key and miss a duplicated call.
     */
    public function testListTopUnlabeledSchedulesRepairExactlyOncePerRead(): void
    {
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
            members_repository: $membersRepo,
            count_repair_calls: true
        );

        $response = $service->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertNotNull($this->countingSync);
        $this->assertCount(1, $this->countingSync->repairCalls, 'one read must emit exactly one repair schedule');
        $this->assertSame(['tenant-1', ['cluster-upward']], $this->countingSync->repairCalls[0]);
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
        $this->assertSame(2, $data['total']);
        $this->assertFalse($data['truncated']);
        $this->assertTrue($data['repair_pending']);
    }

    /**
     * R2-06 residual: a full last page (limit == fetched == total_count, no
     * drops) is not truncated. Mutant: truncated => fetched_page >= limit.
     */
    public function testListTopUnlabeledFullLastPageIsNotTruncated(): void
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
                        'cluster_uuid' => 'cluster-a',
                        'label' => '',
                        'identity_count' => 2,
                        'is_user_confirmed' => 0,
                        'total_count' => 2,
                    ],
                    [
                        'cluster_uuid' => 'cluster-b',
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
                    'cluster-a' => [
                        ['identity_uuid' => 'id-a1', 'attachment_id' => 1],
                        ['identity_uuid' => 'id-a2', 'attachment_id' => 2],
                    ],
                    'cluster-b' => [
                        ['identity_uuid' => 'id-b1', 'attachment_id' => 3],
                        ['identity_uuid' => 'id-b2', 'attachment_id' => 4],
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
        $request->set_param('limit', 2);
        $response = $service->list_top_unlabeled_clusters($request);
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertCount(2, $data['clusters']);
        $this->assertFalse($data['truncated']);
    }

    /**
     * R2-11 residual: a drop whose id the mapper did not request repair for
     * still sets repair_pending. Mutant: delete || $dropped > 0.
     */
    public function testListTopUnlabeledDropWithoutMapperRepairIdSetsRepairPending(): void
    {
        $host = $this->localHost();
        $driftCalls = 0;

        $clustersRepo = new class($driftCalls) extends NullClustersRepository {
            public function __construct(private int &$driftCalls)
            {
            }

            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-drop-matched',
                        'label' => '',
                        'identity_count' => 1,
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

            public function list_unlabeled_identity_count_drift(string $tenant_id, int $limit = 50): array
            {
                ++$this->driftCalls;
                return [];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [
                    'cluster-drop-matched' => [
                        ['identity_uuid' => 'id-d1', 'attachment_id' => 1],
                    ],
                    'cluster-keep' => [
                        ['identity_uuid' => 'id-k1', 'attachment_id' => 2],
                        ['identity_uuid' => 'id-k2', 'attachment_id' => 3],
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
        $data = $response->get_data();
        $this->assertCount(1, $data['clusters']);
        $this->assertSame('cluster-keep', $data['clusters'][0]['id']);
        $this->assertTrue($data['repair_pending']);
        $this->assertSame(2, $data['total']);
        $this->assertSame(1, $driftCalls);
    }

    /**
     * R3-04: total is the pre-filter qualifying COUNT(*) OVER() (total_count).
     * Page-local mapper drops do not shrink it; repair_pending carries the signal.
     * Mutant: subtract $dropped from total.
     */
    public function testListTopUnlabeledTotalIsPreFilterQualifyingCount(): void
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
                        'cluster_uuid' => 'cluster-drop-matched',
                        'label' => '',
                        'identity_count' => 1,
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
                    'cluster-drop-matched' => [
                        ['identity_uuid' => 'id-d1', 'attachment_id' => 1],
                    ],
                    'cluster-keep' => [
                        ['identity_uuid' => 'id-k1', 'attachment_id' => 2],
                        ['identity_uuid' => 'id-k2', 'attachment_id' => 3],
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
        $data = $response->get_data();
        $this->assertCount(1, $data['clusters']);
        $this->assertSame(2, $data['total']);
        $this->assertTrue($data['repair_pending']);
    }

    /**
     * R4-05: missing total_count falls back to the pre-drop fetched-row
     * count, not the post-drop served length. Mutant: $total = count( $unlabeled_items ).
     */
    public function testListTopUnlabeledMissingTotalCountDoesNotShrinkOnDrop(): void
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
                        'cluster_uuid' => 'cluster-drop-matched',
                        'label' => '',
                        'identity_count' => 1,
                        'is_user_confirmed' => 0,
                    ],
                    [
                        'cluster_uuid' => 'cluster-keep',
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
                    'cluster-drop-matched' => [
                        ['identity_uuid' => 'id-d1', 'attachment_id' => 1],
                    ],
                    'cluster-keep' => [
                        ['identity_uuid' => 'id-k1', 'attachment_id' => 2],
                        ['identity_uuid' => 'id-k2', 'attachment_id' => 3],
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
        $data = $response->get_data();
        $this->assertCount(1, $data['clusters']);
        $this->assertSame(
            2,
            $data['total'],
            'missing total_count must fall back to pre-drop fetched-row count'
        );
        $this->assertFalse($data['truncated']);
        $this->assertTrue($data['repair_pending']);
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

    /**
     * R2-09: mapper-requested ids are not evicted by lexically-earlier drift ids.
     * Mutant: array_merge → sort → slice.
     */
    public function testListTopUnlabeledMapperRepairIdsAreNotEvictedByDriftIds(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $host = $this->localHost();

        $mapperIds = [];
        for ($i = 1; $i <= 20; $i++) {
            $mapperIds[] = sprintf('zzz-%02d', $i);
        }

        $clustersRepo = new class($mapperIds) extends NullClustersRepository {
            /** @param list<string> $mapperIds */
            public function __construct(private array $mapperIds)
            {
            }

            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                $rows = [];
                foreach ($this->mapperIds as $id) {
                    $rows[] = [
                        'cluster_uuid' => $id,
                        'label' => '',
                        'identity_count' => 2,
                        'is_user_confirmed' => 0,
                    ];
                }
                return $rows;
            }

            public function list_unlabeled_identity_count_drift(string $tenant_id, int $limit = 50): array
            {
                $ids = [];
                for ($i = 1; $i <= 10; $i++) {
                    $ids[] = sprintf('aaa-%02d', $i);
                }
                return $ids;
            }
        };

        $membersRepo = new class($mapperIds) extends NullIdentityMembersRepository {
            /** @param list<string> $mapperIds */
            public function __construct(private array $mapperIds)
            {
            }

            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                $out = [];
                foreach ($this->mapperIds as $id) {
                    $out[$id] = [
                        ['identity_uuid' => $id . '-m1', 'attachment_id' => 1],
                        ['identity_uuid' => $id . '-m2', 'attachment_id' => 2],
                        ['identity_uuid' => $id . '-m3', 'attachment_id' => 3],
                        ['identity_uuid' => $id . '-m4', 'attachment_id' => 4],
                    ];
                }
                return $out;
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
        $scheduled = array_values($GLOBALS['__ac_scheduled'])[0]['args'][1];
        $this->assertSame(
            array_merge($mapperIds, ['aaa-01', 'aaa-02', 'aaa-03', 'aaa-04', 'aaa-05']),
            $scheduled
        );
    }

    /**
     * R2-09: extra-id top-up is sorted so deleting sort changes the scheduled list.
     * Mutant: delete sort( $normalized ) / sort of extras.
     */
    public function testListTopUnlabeledRepairExtraIdsAreSorted(): void
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
                        'cluster_uuid' => 'mid-keep',
                        'label' => '',
                        'identity_count' => 2,
                        'is_user_confirmed' => 0,
                    ],
                ];
            }

            public function list_unlabeled_identity_count_drift(string $tenant_id, int $limit = 50): array
            {
                return ['ccc-extra', 'aaa-extra', 'bbb-extra'];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [
                    'mid-keep' => [
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

        $service->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
        $scheduled = array_values($GLOBALS['__ac_scheduled'])[0]['args'][1];
        $this->assertSame(['mid-keep', 'aaa-extra', 'bbb-extra', 'ccc-extra'], $scheduled);
    }

    /**
     * R2-09: skip the correlated drift scan once mapper ids already fill the ceiling.
     * Mutant: delete the count($mapper_ids) < CEILING guard.
     */
    public function testListTopUnlabeledSkipsDriftScanWhenMapperIdsFillCeiling(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $host = $this->localHost();
        $driftCalls = 0;

        $mapperIds = [];
        for ($i = 1; $i <= ClusterReadService::TARGETED_REPAIR_ID_CEILING; $i++) {
            $mapperIds[] = sprintf('zzz-%02d', $i);
        }

        $clustersRepo = new class($mapperIds, $driftCalls) extends NullClustersRepository {
            /** @param list<string> $mapperIds */
            public function __construct(private array $mapperIds, private int &$driftCalls)
            {
            }

            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                $rows = [];
                foreach ($this->mapperIds as $id) {
                    $rows[] = [
                        'cluster_uuid' => $id,
                        'label' => '',
                        'identity_count' => 2,
                        'is_user_confirmed' => 0,
                    ];
                }
                return $rows;
            }

            public function list_unlabeled_identity_count_drift(string $tenant_id, int $limit = 50): array
            {
                ++$this->driftCalls;
                return ['aaa-drift'];
            }
        };

        $membersRepo = new class($mapperIds) extends NullIdentityMembersRepository {
            /** @param list<string> $mapperIds */
            public function __construct(private array $mapperIds)
            {
            }

            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                $out = [];
                foreach ($this->mapperIds as $id) {
                    $out[$id] = [
                        ['identity_uuid' => $id . '-m1', 'attachment_id' => 1],
                        ['identity_uuid' => $id . '-m2', 'attachment_id' => 2],
                        ['identity_uuid' => $id . '-m3', 'attachment_id' => 3],
                        ['identity_uuid' => $id . '-m4', 'attachment_id' => 4],
                    ];
                }
                return $out;
            }
        };

        $service = $this->makeService(
            $host,
            use_local_projection: true,
            clusters_repository: $clustersRepo,
            members_repository: $membersRepo
        );

        $service->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
        $this->assertSame(0, $driftCalls);
        $scheduled = array_values($GLOBALS['__ac_scheduled'])[0]['args'][1];
        $this->assertSame($mapperIds, $scheduled);
    }

    /**
     * R4-04: 25 raw mapper ids that collapse below the ceiling after
     * unique-normalize must still run the off-page drift scan.
     * Mutant: gate on the raw requested_repair_cluster_ids() array.
     */
    public function testListTopUnlabeledDuplicateMapperIdsStillRunDriftScan(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $host = $this->localHost();
        $driftCalls = 0;

        $rawIds = [];
        for ($i = 1; $i <= ClusterReadService::TARGETED_REPAIR_ID_CEILING - 1; $i++) {
            $rawIds[] = sprintf('dup-%02d', $i);
        }
        $rawIds[] = 'dup-01';

        $mapper = new class($rawIds) extends ClusterResponseMapper {
            /** @param list<string> $forcedIds */
            public function __construct(private array $forcedIds)
            {
            }

            public function requested_repair_cluster_ids(): array
            {
                return $this->forcedIds;
            }
        };

        $clustersRepo = new class($driftCalls) extends NullClustersRepository {
            public function __construct(private int &$driftCalls)
            {
            }

            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_unlabeled_identity_count_drift(string $tenant_id, int $limit = 50): array
            {
                ++$this->driftCalls;
                return ['aaa-drift'];
            }
        };

        $service = $this->makeService(
            $host,
            use_local_projection: true,
            clusters_repository: $clustersRepo,
            cluster_mapper: $mapper
        );

        $service->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
        $this->assertSame(
            1,
            $driftCalls,
            'duplicate-bearing 25 raw mapper ids must still run the off-page drift scan'
        );
        $scheduled = array_values($GLOBALS['__ac_scheduled'])[0]['args'][1];
        $this->assertContains('aaa-drift', $scheduled);
        $this->assertCount(ClusterReadService::TARGETED_REPAIR_ID_CEILING, $scheduled);
    }

    /**
     * R4-04: all-blank mapper ids normalize to empty, so repair_pending is
     * false when nothing was dropped and no extras were queued.
     * Mutant: set repair_pending from the raw requested_repair_cluster_ids() array.
     */
    public function testListTopUnlabeledAllBlankMapperIdsDoNotSetRepairPending(): void
    {
        $host = $this->localHost();

        $mapper = new class() extends ClusterResponseMapper {
            public function requested_repair_cluster_ids(): array
            {
                return ['', '   ', ''];
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
                        'cluster_uuid' => 'cluster-keep',
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
                    'cluster-keep' => [
                        ['identity_uuid' => 'id-k1', 'attachment_id' => 1],
                        ['identity_uuid' => 'id-k2', 'attachment_id' => 2],
                    ],
                ];
            }
        };

        $service = $this->makeService(
            $host,
            use_local_projection: true,
            clusters_repository: $clustersRepo,
            members_repository: $membersRepo,
            cluster_mapper: $mapper
        );

        $response = $service->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertCount(1, $data['clusters']);
        $this->assertFalse(
            $data['repair_pending'],
            'all-blank mapper ids must not publish repair_pending'
        );
    }

    /**
     * R10A-02: raw extra_ids that normalize to nothing must not publish
     * repair_pending. Mapper requests nothing; dropped is 0.
     * Mutant M1: $repair_pending = array() !== $extra_ids.
     * Mutant M2: schedule_repair_from_mapper returns raw $extra_ids.
     */
    public function testListTopUnlabeledMalformedDriftIdsDoNotSetRepairPending(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $host = $this->localHost();

        $mapper = new class() extends ClusterResponseMapper {
            public function requested_repair_cluster_ids(): array
            {
                return [];
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
                        'cluster_uuid' => 'cluster-keep',
                        'label' => '',
                        'identity_count' => 2,
                        'is_user_confirmed' => 0,
                    ],
                ];
            }

            public function list_unlabeled_identity_count_drift(string $tenant_id, int $limit = 50): array
            {
                return ['', '   ', ''];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [
                    'cluster-keep' => [
                        ['identity_uuid' => 'id-k1', 'attachment_id' => 1],
                        ['identity_uuid' => 'id-k2', 'attachment_id' => 2],
                    ],
                ];
            }
        };

        $service = $this->makeService(
            $host,
            use_local_projection: true,
            clusters_repository: $clustersRepo,
            members_repository: $membersRepo,
            cluster_mapper: $mapper
        );

        $response = $service->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertFalse(
            $data['repair_pending'],
            'malformed drift ids must not publish repair_pending'
        );
        $this->assertSame([], $GLOBALS['__ac_scheduled']);
    }

    /**
     * R10A-02 true-positive: a drift id that survives normalize and fits
     * in the remaining room still sets repair_pending.
     */
    public function testListTopUnlabeledNormalizedDriftIdSetsRepairPending(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $host = $this->localHost();

        $mapper = new class() extends ClusterResponseMapper {
            public function requested_repair_cluster_ids(): array
            {
                return [];
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
                        'cluster_uuid' => 'cluster-keep',
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
                    'cluster-keep' => [
                        ['identity_uuid' => 'id-k1', 'attachment_id' => 1],
                        ['identity_uuid' => 'id-k2', 'attachment_id' => 2],
                    ],
                ];
            }
        };

        $service = $this->makeService(
            $host,
            use_local_projection: true,
            clusters_repository: $clustersRepo,
            members_repository: $membersRepo,
            cluster_mapper: $mapper
        );

        $response = $service->list_top_unlabeled_clusters(new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled'));
        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertTrue(
            $data['repair_pending'],
            'a normalized drift id that fits in the room must publish repair_pending'
        );
        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
        $scheduled = array_values($GLOBALS['__ac_scheduled'])[0]['args'][1];
        $this->assertSame(['cluster-off-page'], $scheduled);
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

    /**
     * R8-05: the bootstrapping/unavailable 200 envelope must satisfy the
     * shared top-unlabeled schema, including required repair_pending.
     * Mutant: omit 'repair_pending' => false from the unavailable envelope.
     */
    public function testListTopUnlabeledBootstrappingEnvelopeValidatesAgainstSchema(): void
    {
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
        TopUnlabeledSchemaValidator::validate($response->get_data());
    }

    /**
     * R8-05: backend_proxy must guarantee repair_pending. Upstream omission
     * normalizes to false — do not invent true.
     */
    public function testListTopUnlabeledBackendProxyOmittingRepairPendingValidatesAgainstSchema(): void
    {
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
                return new WP_REST_Response(
                    [
                        'clusters' => [
                            [
                                'id' => 'cluster-proxy-omit',
                                'tenant_id' => 'tenant-1',
                                'label' => null,
                                'is_labeled' => false,
                                'is_auto_label' => false,
                                'identity_count' => 2,
                                'user_confirmed' => false,
                                'representatives' => [
                                    [
                                        'id' => 'rep-omit',
                                        'media_id' => 101,
                                        'is_pinned' => false,
                                    ],
                                ],
                            ],
                        ],
                        'limit' => 10,
                        'total' => 1,
                        'truncated' => false,
                    ],
                    200
                );
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
        $response = $service->list_top_unlabeled_clusters(
            new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled')
        );

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('backend_proxy', $data['data_source']);
        $this->assertArrayHasKey('repair_pending', $data);
        $this->assertFalse($data['repair_pending']);
        $this->assertSame('unlabeled', $data['clusters'][0]['label_state']);
        TopUnlabeledSchemaValidator::validate($data);
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
        ?NullIdentityMembersRepository $members_repository = null,
        bool $count_repair_calls = false,
        ?ClusterResponseMapper $cluster_mapper = null
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

        if ($count_repair_calls) {
            $this->countingSync = new class($syncHost, self::BOOTSTRAP_HOOK, $clustersRepo, $membersRepo, new NullSyncStateRepository(), $syncJob, null) extends ClusterProjectionSyncService {
                /** @var list<array<int,mixed>> */
                public array $repairCalls = [];

                public function repair_targeted_projection(string $tenant_id, array $cluster_ids): bool
                {
                    $this->repairCalls[] = [$tenant_id, $cluster_ids];

                    return parent::repair_targeted_projection($tenant_id, $cluster_ids);
                }
            };
            $projectionSync = $this->countingSync;
        } else {
            $this->countingSync = null;
            $projectionSync = new ClusterProjectionSyncService(
                $syncHost,
                self::BOOTSTRAP_HOOK,
                $clustersRepo,
                $membersRepo,
                new NullSyncStateRepository(),
                $syncJob,
                null
            );
        }

        $dependencies = new ClusterReadDependencies(
            $clustersRepo,
            $membersRepo,
            new ClusterFacade($clustersRepo, $membersRepo),
            $cluster_mapper ?? new ClusterResponseMapper(),
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
