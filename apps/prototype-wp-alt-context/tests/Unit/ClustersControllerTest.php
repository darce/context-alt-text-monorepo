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
use AltContext\Sovereign\Sync\SyncPullResult;
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

    public function testTopUnlabeledClustersHydrateThumbnailFallbacksFromLocalProjection(): void
    {
        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-1',
                        'label' => null,
                        'identity_count' => 1,
                    ],
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [
                    'cluster-1' => [
                        [
                            'media_id' => 101,
                            'cluster_uuid' => 'cluster-1',
                            'distance' => 0.0,
                        ],
                    ],
                ];
            }
        };

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 1;
            }
        };

        $syncSpy = new ClustersControllerSyncPullSpy();
        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, $syncSpy, new ClusterResponseMapper(), new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        $this->assertSame(0, $data['singleton_count']);
        $this->assertSame('local_projection', $data['data_source']);
        $this->assertSame('available', $data['projection_status']);
        $this->assertSame('http://example.test/media/101.jpg', $data['clusters'][0]['representatives'][0]['thumb_url']);
    }

    public function testTopUnlabeledClustersFallsBackToBackendProxyWhileProjectionBootstraps(): void
    {
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 0;
            }
            public function get_last_updated(string $tenant_id): ?string {
                return null;
            }
        };
        $controller = new ClustersController(null, null, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                [
                    'id' => 'cluster-proxy-top',
                    'label' => null,
                    'identity_count' => 4,
                    'representatives' => [],
                ],
            ]),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'snapshot_version' => 0,
                'clusters' => [],
                'members' => [],
                'empty' => true,
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame(
            [
                'clusters' => [
                    [
                        'id' => 'cluster-proxy-top',
                        'label' => null,
                        'identity_count' => 4,
                        'representatives' => [],
                    ],
                ],
                'data_source' => 'backend_proxy',
            ],
            $response->get_data()
        );

        $calls = $this->getHttpCalls();
        $this->assertCount(2, $calls);
        $this->assertStringContainsString('/recognition/clusters/top-unlabeled', $calls[0]['url']);
        $this->assertStringContainsString('/clusters/delta', $calls[1]['url']);
        $this->assertStringContainsString('since_version=0', $calls[1]['url']);
        $this->assertCount(0, $GLOBALS['__ac_scheduled']);
    }

    public function testTopUnlabeledClustersSchedulesBootstrapWhenProxyAndProjectionAreUnavailable(): void
    {
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 0;
            }
            public function get_last_updated(string $tenant_id): ?string {
                return null;
            }
        };
        $controller = new ClustersController(null, null, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(
            [
                'clusters' => [],
                'singleton_count' => 0,
                'data_source' => 'unavailable',
                'projection_status' => 'bootstrapping',
            ],
            $response->get_data()
        );

        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
    }

    public function testTopUnlabeledOfflineReturnsBareArray(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
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

        $syncSpy = new ClustersControllerSyncPullSpy();
        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, $syncSpy, new ClusterResponseMapper(), new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertArrayHasKey('clusters', $data);
        $this->assertArrayHasKey('singleton_count', $data);
        $this->assertSame('local_projection', $data['data_source']);
        $this->assertSame('available', $data['projection_status']);
        $this->assertSame('cluster-unlabeled', $data['clusters'][0]['id']);
    }

    public function testListClustersUsesLocalProjectionWhenSyncStatePresent(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-local',
                        'label' => 'Local',
                        'identity_count' => 1,
                        'total_count' => 2,
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
        $request->set_param('limit', 1);
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertSame(1, $data['limit']);
        $this->assertSame(2, $data['total']);
        $this->assertTrue($data['truncated']);
        $this->assertSame('cluster-local', $data['clusters'][0]['id']);

        $this->assertArrayHasKey('clusters', $data);
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
        $this->assertSame(50, $data['limit']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
        $this->assertSame('cluster-proxy', $data['clusters'][0]['id']);
    }

    public function testListClustersClampsProxyLimitToConfiguredMaximum(): void
    {
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $request->set_param('limit', 10000);
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(
            \WP_REST_Response::class,
            $response
        );
        $data = $response->get_data();
        $this->assertSame(500, $data['limit']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
    }

    public function testListClustersClampsProxyLimitToConfiguredMinimum(): void
    {
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $request->set_param('limit', 0);
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(
            \WP_REST_Response::class,
            $response
        );
        $data = $response->get_data();
        $this->assertSame(1, $data['limit']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
    }

    public function testListClustersUsesDefaultLimitWhenProxyLimitIsOmitted(): void
    {
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(
            \WP_REST_Response::class,
            $response
        );
        $data = $response->get_data();
        $this->assertSame(50, $data['limit']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
    }

    public function testListClustersRejectsPartialProxyEnvelope(): void
    {
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $partialEnvelope = [
            'clusters' => [
                ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
            ],
        ];

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode($partialEnvelope),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_cluster_list_envelope', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
    }

    public function testListClustersTreatsZeroRowsAsAuthoritativeWhenSyncStateWasInitialized(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return false;
            }
            public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
            {
                return [];
            }
        };

        $membersRepo = new NullIdentityMembersRepository();

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 9;
            }
            public function get_last_updated(string $tenant_id): ?string {
                return '2026-03-26 12:00:00';
            }
        };

        $syncSpy = new ClustersControllerSyncPullSpy();
        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, $syncSpy, new ClusterResponseMapper(), new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame(
            [
                'clusters' => [],
                'limit' => 50,
                'total' => 0,
                'truncated' => false,
            ],
            $data
        );
        $this->assertFalse($syncSpy->performedBypass);
        $this->assertCount(0, $this->getHttpCalls());
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

    public function testListClusterLabelsUsesEnvelopeForLocalProjection(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_labels(string $tenant_id): array
            {
                return ['Alice', 'Alicia', 'Bob'];
            }
        };

        $controller = new ClustersController(
            $clustersRepo,
            new NullIdentityMembersRepository(),
            new class() extends NullSyncStateRepository {
                public function get_snapshot_version(string $tenant_id): int
                {
                    return 1;
                }
            },
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/labels');
        $request->set_param('search', 'ali');
        $request->set_param('limit', 1);
        $response = $controller->list_cluster_labels($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(
            [
                'labels' => ['Alice'],
                'limit' => 1,
                'total' => 2,
                'truncated' => true,
            ],
            $response->get_data()
        );
    }

    public function testListClusterLabelsRejectsPartialProxyEnvelope(): void
    {
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'labels' => ['Alice', 'Alicia'],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/labels');
        $response = $controller->list_cluster_labels($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_cluster_labels_envelope', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
    }

    public function testGetClusterMembersUsesEnvelopeForLocalProjection(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function find_by_uuid(string $cluster_uuid): ?array
            {
                return [
                    'cluster_uuid' => $cluster_uuid,
                    'label' => 'Cluster Local',
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
            {
                return [
                    [
                        'identity_uuid' => 'identity-local-1',
                        'cluster_uuid' => $cluster_uuid,
                        'attachment_id' => 101,
                        'similarity' => 0.98,
                    ],
                ];
            }

            public function count_for_cluster(string $cluster_uuid): int
            {
                return IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT + 1;
            }
        };

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 1;
            }
        };

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-local/members');
        $request->set_param('cluster_id', 'cluster-local');
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame(IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, $data['limit']);
        $this->assertSame(IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT + 1, $data['total']);
        $this->assertTrue($data['truncated']);
        $this->assertSame('identity-local-1', $data['members'][0]['identity_id']);
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
        $this->assertSame(IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, $data['limit']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
        $this->assertSame('id-1', $data['members'][0]['identity_uuid']);
    }

    public function testStaleProjectionTriggersSyncPullBeforeServing(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
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
        $this->assertSame('cluster-stale', $data['clusters'][0]['id']);
    }

    public function testStaleProjectionServesStaleDataWhenSyncFails(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
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
        $this->assertSame('cluster-resilient', $data['clusters'][0]['id']);
    }

    public function testNullSyncPullJobDoesNotCrashOnStaleProjection(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
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
            'body' => json_encode([
                'fallback_to_snapshot' => true,
            ]),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '"invalid"',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertSame('cluster-no-sync', $data['clusters'][0]['id']);

        $calls = $this->getHttpCalls();
        $this->assertCount(2, $calls);
        $this->assertStringContainsString('/recognition/tenants/', $calls[0]['url']);
        $this->assertStringContainsString('/clusters/delta', $calls[0]['url']);
        $this->assertStringContainsString('/clusters/snapshot', $calls[1]['url']);
    }
}

class ClustersControllerSyncPullSpy implements SyncPullJobInterface
{
    public bool $performed = false;
    public string $tenantId = '';
    public bool $performedBypass = false;
    public string $tenantIdBypass = '';

    public function perform(string $tenant_id): SyncPullResult
    {
        $this->performed = true;
        $this->tenantId = $tenant_id;
        return SyncPullResult::ok();
    }

    public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
    {
        $this->performedBypass = true;
        $this->tenantIdBypass = $tenant_id;
        return SyncPullResult::ok();
    }

    public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
    {
        $this->performedBypass = true;
        $this->tenantIdBypass = $tenant_id;
        return SyncPullResult::ok();
    }
}

class ClustersControllerFailingSyncPull implements SyncPullJobInterface
{
    public function perform(string $tenant_id): SyncPullResult
    {
        return SyncPullResult::failed();
    }

    public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
    {
        return SyncPullResult::failed();
    }

    public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
    {
        return SyncPullResult::failed();
    }
}
