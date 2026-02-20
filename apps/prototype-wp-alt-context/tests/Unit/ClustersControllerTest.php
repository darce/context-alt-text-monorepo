<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersController;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\ClustersController
 */
class ClustersControllerTest extends TestCase
{
    private ClustersController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->controller = new ClustersController();
    }

    public function testRegisterRoutesIncludesReadOnlyClusterSurfaces(): void
    {
        $this->controller->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains('/recognition/clusters', $routes);
        $this->assertContains('/recognition/clusters/top-unlabeled', $routes);
        $this->assertContains('/recognition/clusters/labels', $routes);
        $this->assertContains('/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)', $routes);
        $this->assertContains('/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/members', $routes);

        $this->assertNotContains('/recognition/clusters/reassign', $routes);
        $this->assertNotContains('/recognition/media-identities', $routes);
    }

    public function testTopUnlabeledClustersHydrateThumbnailFallbacks(): void
    {
        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                [
                    'id' => 'cluster-1',
                    'representatives' => [
                        [
                            'id' => 'rep-1',
                            'media_id' => 101,
                            'thumb_url' => null,
                        ],
                        [
                            'id' => 'rep-2',
                            'media_id' => 202,
                            'thumbnail_url' => 'http://example.test/media/legacy-202.jpg',
                        ],
                    ],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $this->controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        $this->assertSame('http://example.test/media/101.jpg', $data[0]['representatives'][0]['thumb_url']);
        $this->assertSame('http://example.test/media/legacy-202.jpg', $data[0]['representatives'][1]['thumb_url']);
    }

    public function testTopUnlabeledClustersReturnsEmptyPayloadWhenProxyUnavailable(): void
    {
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $this->controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame([], $response->get_data());
    }

    public function testTopUnlabeledOfflineReturnsBareArray(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-unlabeled',
                        'label' => null,
                        'identity_count' => 3,
                    ],
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [];
            }
        };

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 1;
            }
            public function get_last_updated(string $tenant_id): ?string {
                return '2026-02-14 00:00:00';
            }
        };

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertArrayNotHasKey('clusters', $data);
        $this->assertArrayNotHasKey('tenant_id', $data);
        $this->assertSame('cluster-unlabeled', $data[0]['id']);
    }

    public function testListClustersUsesLocalProjectionWhenSyncStatePresent(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-local',
                        'label' => 'Local',
                        'identity_count' => 1,
                    ],
                ];
            }
            public function list_labels(string $tenant_id): array {
				return ['Local']; }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
            {
                return [
                    [
                        'identity_uuid' => 'identity-1',
                        'attachment_id' => 10,
                        'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                    ],
                ];
            }
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                $result = [];
                foreach ($cluster_uuids as $uuid) {
                    $result[$uuid] = [
                        [
                            'identity_uuid' => 'identity-1',
                            'attachment_id' => 10,
                            'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                        ],
                    ];
                }
                return $result;
            }
        };

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
				return 1; }
            public function get_last_updated(string $tenant_id): ?string {
				return '2026-02-14 00:00:00'; }
        };

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertSame('cluster-local', $data[0]['id']);

        // Offline must return a bare array — no { clusters, tenant_id } envelope.
        // The frontend calls fetchRequiredApi<ClusterSummary[]> and casts the raw
        // JSON body directly, so an envelope would silently produce an empty UI.
        $this->assertArrayNotHasKey('clusters', $data);
        $this->assertArrayNotHasKey('tenant_id', $data);
    }

    public function testListClustersProxiesWhenNoLocalProjection(): void
    {
        $clustersRepo = new NullClustersRepository();
        $membersRepo = new NullIdentityMembersRepository();

        // Sync repo with version 0 and no updated_at triggers proxy fallback
        $syncRepo = new NullSyncStateRepository();

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        // Queue a mock HTTP response for the proxy request
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('cluster-proxy', $data[0]['id']);
    }

    public function testSuccessfulProxyReadTriggersInlineBootstrapSyncWithoutSchedulingCron(): void
    {
        $syncRepo = new NullSyncStateRepository();
        $syncSpy = new ClustersControllerSyncPullSpy();

        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            $syncRepo,
            $syncSpy,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['id' => 'cluster-proxy', 'label' => 'Proxied'],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertTrue($syncSpy->performedBypass);
        $this->assertFalse($syncSpy->performed);
        $this->assertCount(0, $GLOBALS['__ac_scheduled']);
    }

    public function testFailedInlineBootstrapSchedulesCronRetry(): void
    {
        $syncRepo = new NullSyncStateRepository();
        $syncJob = new ClustersControllerFailingSyncPull();
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            $syncRepo,
            $syncJob,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['id' => 'cluster-proxy', 'label' => 'Proxied'],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
    }

    public function testFailedProxyReadDoesNotTriggerBootstrapSyncOrCron(): void
    {
        $syncRepo = new NullSyncStateRepository();
        $syncSpy = new ClustersControllerSyncPullSpy();
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            $syncRepo,
            $syncSpy,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertTrue(is_wp_error($response));
        $this->assertFalse($syncSpy->performedBypass);
        $this->assertCount(0, $GLOBALS['__ac_scheduled']);
    }

    public function testBootstrapCronCallbackInvokesBypassSyncWithTenant(): void
    {
        $syncSpy = new ClustersControllerSyncPullSpy();
        new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            $syncSpy,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        do_action('acx_bootstrap_sync', 'tenant-cron');

        $this->assertTrue($syncSpy->performedBypass);
        $this->assertSame('tenant-cron', $syncSpy->tenantIdBypass);
    }

    public function testGetClusterMembersProxiesWhenNoLocalProjection(): void
    {
        $clustersRepo = new NullClustersRepository();
        $membersRepo = new NullIdentityMembersRepository();

        // Sync repo with version 0 and no updated_at triggers proxy fallback
        $syncRepo = new NullSyncStateRepository();

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        // Queue a mock HTTP response for the proxy request
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['identity_uuid' => 'id-1', 'media_id' => 10],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-123/members');
        $request->set_param('cluster_id', 'cluster-123');
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('id-1', $data[0]['identity_uuid']);
    }

    public function testStaleProjectionTriggersSyncPullBeforeServing(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-stale',
                        'label' => 'Stale Data',
                        'identity_count' => 1,
                    ],
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [];
            }
        };

        // Sync version > 0 but updated_at is very old (stale).
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 5; }
            public function get_last_updated(string $tenant_id): ?string {
                return '2020-01-01 00:00:00'; }
        };

        $syncSpy = new ClustersControllerSyncPullSpy();

        $controller = new ClustersController(
            $clustersRepo,
            $membersRepo,
            $syncRepo,
            $syncSpy,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertTrue($syncSpy->performed, 'SyncPullJob::perform() must be called when projection is stale');
        $this->assertNotEmpty($syncSpy->tenantId, 'SyncPullJob must receive the tenant_id');

        // Even though sync was triggered, stale data is still served immediately
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertSame('cluster-stale', $data[0]['id']);
    }

    public function testStaleProjectionServesStaleDataWhenSyncFails(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-resilient',
                        'label' => 'Resilient',
                        'identity_count' => 2,
                    ],
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [];
            }
        };

        // Stale projection
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 3; }
            public function get_last_updated(string $tenant_id): ?string {
                return '2020-01-01 00:00:00'; }
        };

        // Sync job that always fails
        $failingSyncJob = new ClustersControllerFailingSyncPull();

        $controller = new ClustersController(
            $clustersRepo,
            $membersRepo,
            $syncRepo,
            $failingSyncJob,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        // Graceful degradation: stale data is served even when sync fails
        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertSame('cluster-resilient', $data[0]['id']);
    }

    public function testNullSyncPullJobDoesNotCrashOnStaleProjection(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-no-sync',
                        'label' => 'No Sync',
                        'identity_count' => 1,
                    ],
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [];
            }
        };

        // Stale projection, but sync_pull_job is null
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 1; }
            public function get_last_updated(string $tenant_id): ?string {
                return '2020-01-01 00:00:00'; }
        };

        // Pass null for sync_pull_job — controller must handle gracefully
        $controller = new ClustersController(
            $clustersRepo,
            $membersRepo,
            $syncRepo,
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '"invalid"',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertSame('cluster-no-sync', $data[0]['id']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/tenants/', $calls[0]['url']);
    }
}

class ClustersControllerSyncPullSpy implements SyncPullJobInterface
{
    public bool $performed = false;
    public string $tenantId = '';
    public bool $performedBypass = false;
    public string $tenantIdBypass = '';

    public function perform(string $tenant_id): bool
    {
        $this->performed = true;
        $this->tenantId = $tenant_id;
        return true;
    }

    public function perform_bypass_cooldown(string $tenant_id): bool
    {
        $this->performedBypass = true;
        $this->tenantIdBypass = $tenant_id;
        return true;
    }
}

class ClustersControllerFailingSyncPull implements SyncPullJobInterface
{
    public function perform(string $tenant_id): bool
    {
        return false;
    }

    public function perform_bypass_cooldown(string $tenant_id): bool
    {
        return false;
    }
}
