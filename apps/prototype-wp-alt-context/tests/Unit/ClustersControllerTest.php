<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersController;
use AltContext\Api\RecognitionDataSource;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Sovereign\Sync\TargetedSyncPullJobInterface;
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

    /**
     * Deduped async heal events scheduled on the read path, keyed by the
     * wp-cron stub as BOOTSTRAP_SYNC_HOOK . '::' . md5(serialize($args)).
     *
     * @return array<string,array{timestamp:int,args:array<int,string>}>
     */
    private function scheduledBootstrapEvents(): array
    {
        $events = [];
        foreach (($GLOBALS['__ac_scheduled'] ?? []) as $key => $event) {
            if (str_starts_with((string) $key, RecognitionDataSource::BOOTSTRAP_SYNC_HOOK . '::')) {
                $events[$key] = $event;
            }
        }

        return $events;
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
        $this->assertSame(10, $data['limit']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
        $this->assertSame(0, $data['singleton_count']);
        $this->assertTrue($data['has_clusters']);
        $this->assertSame('local_projection', $data['data_source']);
        $this->assertSame('available', $data['projection_status']);
        $this->assertSame('http://example.test/media/101.jpg', $data['clusters'][0]['representatives'][0]['thumb_url']);
    }

    public function testTopUnlabeledClustersExposeEmptyProjectionStateWhenNoProjectedClustersExist(): void
    {
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return false;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return [];
            }
        };

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 1;
            }
        };

        $controller = new ClustersController(
            $clustersRepo,
            new NullIdentityMembersRepository(),
            $syncRepo,
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame(
            [
                'clusters' => [],
                'limit' => 10,
                'total' => 0,
                'truncated' => false,
                'singleton_count' => 0,
                'has_clusters' => false,
                'data_source' => 'local_projection',
                'projection_status' => 'available',
            ],
            $response->get_data()
        );
    }

    public function testTopUnlabeledClustersScheduleAsyncHealForMissingMembersWithoutBlocking(): void
    {
        $projectionState = new \stdClass();
        $projectionState->membersByCluster = [];
        $projectionState->targetedClusterIds = [];

        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
                return [
                    [
                        'cluster_uuid' => 'cluster-needs-members',
                        'label' => null,
                        'identity_count' => 7,
                    ],
                ];
            }
        };

        $membersRepo = new class($projectionState) extends NullIdentityMembersRepository {
            private \stdClass $projectionState;

            public function __construct(\stdClass $projectionState)
            {
                $this->projectionState = $projectionState;
            }

            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return $this->projectionState->membersByCluster;
            }
        };

        $syncJob = new class($projectionState) implements TargetedSyncPullJobInterface {
            private \stdClass $projectionState;

            public function __construct(\stdClass $projectionState)
            {
                $this->projectionState = $projectionState;
            }

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

            public function perform_targeted_snapshot(string $tenant_id, array $cluster_ids): SyncPullResult
            {
                $this->projectionState->targetedClusterIds = $cluster_ids;
                $this->projectionState->membersByCluster = [
                    'cluster-needs-members' => [
                        [
                            'identity_uuid' => 'identity-repaired',
                            'cluster_uuid' => 'cluster-needs-members',
                            'attachment_id' => 202,
                            'media_id' => 202,
                            'distance' => 0.0,
                        ],
                    ],
                ];
                return SyncPullResult::ok();
            }
        };

        $controller = new ClustersController(
            $clustersRepo,
            $membersRepo,
            new class() extends NullSyncStateRepository {
                public function get_snapshot_version(string $tenant_id): int
                {
                    return 1;
                }
            },
            $syncJob,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();

        // Missing members converge off the request path: repair_targeted_projection
        // now returns false and never pulls inline, so perform_targeted_snapshot
        // must not run (the projection would regress to a synchronous repair if it did).
        $this->assertSame([], $projectionState->targetedClusterIds);

        // Memberless rows are dropped at the mapper boundary (R1-03).
        $this->assertSame([], $data['clusters']);

        // The drifted cluster is named on a scheduled event (R1-07). A
        // tenant-wide bootstrap may also be scheduled when the gate is stale.
        $events = $this->scheduledBootstrapEvents();
        $this->assertNotEmpty($events);
        $targeted = array_values(array_filter(
            $events,
            static fn (array $event): bool => ($event['args'][1] ?? null) === ['cluster-needs-members']
        ));
        $this->assertCount(1, $targeted);
        $this->assertSame(self::currentTenantId(), $targeted[0]['args'][0]);
    }

    public function testTopUnlabeledClustersClampExcessiveRequestLimit(): void
    {
        $capture = new \stdClass();
        $capture->limit = null;

        $clustersRepo = new class($capture) extends NullClustersRepository {
            private \stdClass $capture;

            public function __construct(\stdClass $capture)
            {
				$this->capture = $capture;
            }

            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
            {
				$this->capture->limit = $limit;

                return [];
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

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $request->set_param('limit', 9999);
        $response = $controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(500, $capture->limit);
        $this->assertSame(500, $response->get_data()['limit']);
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
                'clusters' => [
                    [
                        'id' => 'cluster-proxy-top',
                        'label' => null,
                        'identity_count' => 4,
                        'representatives' => [],
                    ],
                ],
                'limit' => 10,
                'total' => 1,
                'truncated' => false,
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
                'limit' => 10,
                'total' => 1,
                'truncated' => false,
                'data_source' => 'backend_proxy',
            ],
            $response->get_data()
        );

        // The proxy read is the only synchronous HTTP call; convergence is off-path.
        // A regression to an inline delta/bootstrap pull would add a second call.
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/clusters/top-unlabeled', $calls[0]['url']);

        // The successful proxy read schedules exactly one deduped async bootstrap heal.
        $events = $this->scheduledBootstrapEvents();
        $this->assertCount(1, $events);
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);
    }

    public function testTopUnlabeledClustersRejectPartialProxyEnvelope(): void
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
                'clusters' => [],
                'limit' => 10,
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

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_top_unlabeled_envelope', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status']);
    }

    public function testTopUnlabeledClustersRejectsLegacyBareArrayProxyPayload(): void
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

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_top_unlabeled_envelope', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
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
                'limit' => 10,
                'total' => 0,
                'truncated' => false,
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
            public function list_labels(string $tenant_id, string $search = '', int $limit = self::DEFAULT_LIST_LIMIT): array {
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

        // Queue a mock HTTP response for the proxy request (canonical envelope).
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'clusters' => [
                    ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
                ],
                'limit' => 50,
                'total' => 1,
                'truncated' => false,
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
                'clusters' => [
                    ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
                ],
                'limit' => 500,
                'total' => 1,
                'truncated' => false,
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
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('limit=500', $calls[0]['url']);
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
                'clusters' => [
                    ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
                ],
                'limit' => 1,
                'total' => 1,
                'truncated' => false,
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
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('limit=1', $calls[0]['url']);
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
                'clusters' => [
                    ['id' => 'cluster-proxy', 'label' => 'Proxied', 'identity_count' => 5],
                ],
                'limit' => 50,
                'total' => 1,
                'truncated' => false,
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

    public function testListClustersRejectsLegacyBareArrayProxyPayload(): void
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

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_cluster_list_envelope', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
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

    public function testSuccessfulProxyReadSchedulesAsyncBootstrapCronWithoutInlinePull(): void
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
                'clusters' => [
                    ['id' => 'cluster-proxy', 'label' => 'Proxied'],
                ],
                'limit' => 50,
                'total' => 1,
                'truncated' => false,
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);

        // BR-04/BR-02: a successful proxy read converges via the deduped async cron
        // event only. It must NOT block the response on an inline bypass/perform pull
        // (the spy records either call, so a regression to inline pulling fails here).
        $this->assertFalse($syncSpy->performedBypass);
        $this->assertFalse($syncSpy->performed);

        $events = $this->scheduledBootstrapEvents();
        $this->assertCount(1, $events);
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);
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
        $capturedSearch = null;
        $capturedLimit = null;

        $clustersRepo = new class() extends NullClustersRepository {
            public ?string $capturedSearch = null;
            public ?int $capturedLimit = null;

            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function list_labels(string $tenant_id, string $search = '', int $limit = self::DEFAULT_LIST_LIMIT): array
            {
                $this->capturedSearch = $search;
                $this->capturedLimit = $limit;

                return [
                    ['label' => 'Alice', 'total_count' => 2],
                ];
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
        $this->assertSame('ali', $clustersRepo->capturedSearch);
        $this->assertSame(1, $clustersRepo->capturedLimit);
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

            public function count_for_cluster(string $cluster_uuid, ?string $tenant_id = null): int
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

    public function testGetClusterMembersScheduleAsyncHealForMissingMembersWithoutBlocking(): void
    {
        $projectionState = new \stdClass();
        $projectionState->membersByCluster = [];
        $projectionState->targetedClusterIds = [];

        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }

            public function find_by_uuid(string $cluster_uuid): ?array
            {
                return [
                    'cluster_uuid' => $cluster_uuid,
                    'label' => null,
                    'identity_count' => 7,
                ];
            }
        };

        $membersRepo = new class($projectionState) extends NullIdentityMembersRepository {
            private \stdClass $projectionState;

            public function __construct(\stdClass $projectionState)
            {
                $this->projectionState = $projectionState;
            }

            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
            {
                return $this->projectionState->membersByCluster[$cluster_uuid] ?? [];
            }

            public function count_for_cluster(string $cluster_uuid, ?string $tenant_id = null): int
            {
                return count($this->projectionState->membersByCluster[$cluster_uuid] ?? []);
            }
        };

        $syncJob = new class($projectionState) implements TargetedSyncPullJobInterface {
            private \stdClass $projectionState;

            public function __construct(\stdClass $projectionState)
            {
                $this->projectionState = $projectionState;
            }

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

            public function perform_targeted_snapshot(string $tenant_id, array $cluster_ids): SyncPullResult
            {
                $this->projectionState->targetedClusterIds = $cluster_ids;
                $this->projectionState->membersByCluster['cluster-needs-members'] = [
                    [
                        'identity_uuid' => 'identity-repaired',
                        'cluster_uuid' => 'cluster-needs-members',
                        'attachment_id' => 202,
                        'similarity' => 0.99,
                    ],
                ];
                return SyncPullResult::ok();
            }
        };

        $controller = new ClustersController(
            $clustersRepo,
            $membersRepo,
            new class() extends NullSyncStateRepository {
                public function get_snapshot_version(string $tenant_id): int
                {
                    return 1;
                }
            },
            $syncJob,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-needs-members/members');
        $request->set_param('cluster_id', 'cluster-needs-members');
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();

        // repair_targeted_projection now returns false and schedules the async heal
        // instead of pulling inline, so perform_targeted_snapshot must not run (a
        // regression to synchronous repair would repopulate targetedClusterIds).
        $this->assertSame([], $projectionState->targetedClusterIds);

        // The current (unrepaired) projection is served immediately: no members yet.
        $this->assertSame([], $data['members']);
        $this->assertSame(0, $data['total']);
        $this->assertFalse($data['truncated']);

        // The drifted cluster is named on a scheduled event (R1-07). A
        // tenant-wide bootstrap may also be scheduled when the gate is stale.
        $events = $this->scheduledBootstrapEvents();
        $this->assertNotEmpty($events);
        $targeted = array_values(array_filter(
            $events,
            static fn (array $event): bool => ($event['args'][1] ?? null) === ['cluster-needs-members']
        ));
        $this->assertCount(1, $targeted);
        $this->assertSame(self::currentTenantId(), $targeted[0]['args'][0]);
    }

    public function testGetClusterMembersUsesRepositoryTotalMetadataBeforeFallbackCount(): void
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
                        'total_count' => IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT + 1,
                    ],
                ];
            }

            public function count_for_cluster(string $cluster_uuid, ?string $tenant_id = null): int
            {
                throw new \RuntimeException('count_for_cluster should not be called when total_count metadata is present.');
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
                'members' => [
                    ['identity_uuid' => 'id-1', 'media_id' => 10],
                ],
                'limit' => IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT,
                'total' => 1,
                'truncated' => false,
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

    /**
     * Legacy bare-array proxy payloads must not be normalized into a fabricated
     * envelope [rg-015]; the recognition service always emits the canonical
     * shape, so anything else is a contract violation.
     */
    public function testGetClusterMembersRejectsLegacyBareArrayProxyPayload(): void
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
                ['identity_uuid' => 'id-1', 'media_id' => 10],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-123/members');
        $request->set_param('cluster_id', 'cluster-123');
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_cluster_members_envelope', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
    }

    public function testGetClusterMembersRejectsPartialProxyEnvelope(): void
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
                'members' => [
                    ['identity_uuid' => 'id-1', 'media_id' => 10],
                ],
                'limit' => IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT,
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-123/members');
        $request->set_param('cluster_id', 'cluster-123');
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_cluster_members_envelope', $response->get_error_code());
        $this->assertSame(502, $response->get_error_data()['status'] ?? null);
    }

    public function testGetClusterMembersLocalProjectionHonorsLimitAndOffset(): void
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
                    'label' => 'Paged Local',
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public ?int $capturedLimit = null;
            public ?int $capturedOffset = null;

            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
            {
                $this->capturedLimit = $limit;
                $this->capturedOffset = $offset;

                return [
                    [
                        'identity_uuid' => 'identity-page-2',
                        'cluster_uuid' => $cluster_uuid,
                        'attachment_id' => 202,
                        'similarity' => 0.9,
                        'total_count' => 5,
                    ],
                ];
            }

            public function count_for_cluster(string $cluster_uuid, ?string $tenant_id = null): int
            {
                throw new \RuntimeException('count_for_cluster should not be called when total_count metadata is present.');
            }
        };

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int
            {
                return 1;
            }
        };

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-local/members');
        $request->set_param('cluster_id', 'cluster-local');
        $request->set_param('limit', 2);
        $request->set_param('offset', 2);
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame(2, $membersRepo->capturedLimit);
        $this->assertSame(2, $membersRepo->capturedOffset);
        $this->assertSame(2, $data['limit']);
        $this->assertSame(5, $data['total']);
        $this->assertTrue($data['truncated']);
        $this->assertSame('identity-page-2', $data['members'][0]['identity_id']);
    }

    /**
     * Reject-not-clamp parity with recognition's validate_paging: out-of-range
     * limits and negative offsets return 400 on the WP leg too, instead of
     * silently clamping into a different page than the caller requested.
     */
    public function testGetClusterMembersRejectsLimitAboveMaxWith400(): void
    {
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-local/members');
        $request->set_param('cluster_id', 'cluster-local');
        $request->set_param('limit', IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT + 100);
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_limit', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status'] ?? null);
    }

    public function testGetClusterMembersRejectsNonPositiveLimitWith400(): void
    {
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-local/members');
        $request->set_param('cluster_id', 'cluster-local');
        $request->set_param('limit', 0);
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_limit', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status'] ?? null);
    }

    public function testGetClusterMembersRejectsNegativeOffsetWith400(): void
    {
        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-local/members');
        $request->set_param('cluster_id', 'cluster-local');
        $request->set_param('offset', -1);
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_offset', $response->get_error_code());
        $this->assertSame(400, $response->get_error_data()['status'] ?? null);
    }

    /**
     * Literal-equality guard: the WP members page cap
     * (IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, aliased
     * by ClusterReadService::GET_CLUSTER_MEMBERS_MAX_LIMIT) must stay equal to
     * the recognition service's CLUSTER_MEMBERS_PAGE_LIMIT
     * (recognition/interface_adapters/http/routers/clusters_snapshot.py). Both
     * are 500; if either side changes, change the other in the same slice.
     */
    public function testClusterMembersPageLimitMatchesRecognitionConstant(): void
    {
        $this->assertSame(500, IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT);
    }

    /**
     * E21-14-R3-COORDINATOR-02 / sr-007: list-card preview fetch (ClusterFacade
     * + ClusterReadService load_members_by_cluster) and the mapper preview_limit
     * must share one domain constant so truncation semantics cannot desync.
     */
    public function testPreviewIdentitiesPerClusterIsCanonicalDomainConstant(): void
    {
        $this->assertSame(4, IdentityMembersRepositoryInterface::PREVIEW_IDENTITIES_PER_CLUSTER);

        $serviceReflection = new \ReflectionClass(\AltContext\Api\Services\ClusterReadService::class);
        $servicePreview = $serviceReflection->getReflectionConstant('PREVIEW_IDENTITIES_PER_CLUSTER');
        $this->assertNotFalse($servicePreview);
        $this->assertSame(
            IdentityMembersRepositoryInterface::PREVIEW_IDENTITIES_PER_CLUSTER,
            $servicePreview->getValue()
        );
    }

    public function testGetClusterMembersProxyForwardsLimitAndOffset(): void
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
                'members' => [
                    ['identity_uuid' => 'id-page', 'media_id' => 10],
                ],
                'limit' => 2,
                'total' => 5,
                'truncated' => true,
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-123/members');
        $request->set_param('cluster_id', 'cluster-123');
        $request->set_param('limit', 2);
        $request->set_param('offset', 2);
        $response = $controller->get_cluster_members($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame(2, $data['limit']);
        $this->assertSame(5, $data['total']);
        $this->assertTrue($data['truncated']);
        $this->assertSame('id-page', $data['members'][0]['identity_uuid']);

        $calls = $this->getHttpCalls();
        $this->assertNotEmpty($calls);
        $this->assertStringContainsString('/recognition/clusters/cluster-123/members', $calls[0]['url']);
        $this->assertStringContainsString('limit=2', $calls[0]['url']);
        $this->assertStringContainsString('offset=2', $calls[0]['url']);
    }

    public function testStaleProjectionSchedulesAsyncHealWithoutBlocking(): void
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
        $this->assertSame(200, $response->get_status());

        // BR-03: heal async, never inline. The prior inline perform() blocked the
        // read on a possibly-offline backend; a stale read must schedule the deduped
        // cron event and leave the sync job untouched on the request path.
        $this->assertFalse($syncSpy->performed, 'Stale read must not pull inline via perform()');
        $this->assertFalse($syncSpy->performedBypass, 'Stale read must not pull inline via perform_bypass_cooldown()');

        $events = $this->scheduledBootstrapEvents();
        $this->assertCount(1, $events);
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);

        // Stale data is still served immediately, off the convergence path.
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

    public function testNullSyncPullJobOnStaleProjectionSchedulesAsyncHealWithoutCrashing(): void
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

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        // The stale local projection is served immediately without crashing on the
        // null sync job.
        $data = $response->get_data();
        $this->assertIsArray($data);
        $this->assertSame('cluster-no-sync', $data['clusters'][0]['id']);

        // No inline pull: convergence is deferred to the deduped async cron event,
        // so the read path issues zero HTTP requests even with a null job.
        $this->assertSame([], $this->getHttpCalls());
        $events = $this->scheduledBootstrapEvents();
        $this->assertCount(1, $events);
        $this->assertSame([self::currentTenantId()], array_values($events)[0]['args']);
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
