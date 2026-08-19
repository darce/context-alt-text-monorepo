<?php

declare(strict_types=1);

namespace AltContext\Tests\Support;

use AltContext\Api\ClustersController;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\TargetedSyncPullJobInterface;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use WP_REST_Request;

/**
 * Deterministic scenario harness for clusters-read golden characterization.
 */
final class ClustersReadCharacterizationScenarios
{
    /**
     * @return list<string>
     */
    public static function scenarioIds(): array
    {
        return [
            'list_clusters_local_projection',
            'list_clusters_stale_projection_sync',
            'list_clusters_stale_projection_sync_failed',
            'list_clusters_proxy_success',
            'list_clusters_proxy_invalid_envelope',
            'list_clusters_proxy_bootstrap_inline_success',
            'list_clusters_proxy_bootstrap_cron_scheduled',
            'list_top_unlabeled_local_projection',
            'list_top_unlabeled_proxy_success',
            'list_top_unlabeled_proxy_canonical_envelope',
            'list_top_unlabeled_proxy_invalid_envelope',
            'list_top_unlabeled_proxy_bootstrapping_fallback',
            'list_top_unlabeled_targeted_repair',
            'list_cluster_labels_local_projection',
            'list_cluster_labels_proxy_success',
            'list_cluster_labels_proxy_invalid_envelope',
            'get_cluster_detail_local_projection',
            'get_cluster_detail_proxy_success',
            'get_cluster_detail_local_not_found',
            'get_cluster_members_local_projection',
            'get_cluster_members_local_not_found',
            'get_cluster_members_proxy_success',
            'get_cluster_members_proxy_invalid_envelope',
            'get_cluster_members_targeted_repair',
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     * @throws \InvalidArgumentException When $scenario_id is unknown.
     */
    public static function run(string $scenario_id): array
    {
        return match ($scenario_id) {
            'list_clusters_local_projection' => self::listClustersLocalProjection(),
            'list_clusters_stale_projection_sync' => self::listClustersStaleProjectionSync(),
            'list_clusters_stale_projection_sync_failed' => self::listClustersStaleProjectionSyncFailed(),
            'list_clusters_proxy_success' => self::listClustersProxySuccess(),
            'list_clusters_proxy_invalid_envelope' => self::listClustersProxyInvalidEnvelope(),
            'list_clusters_proxy_bootstrap_inline_success' => self::listClustersProxyBootstrapInlineSuccess(),
            'list_clusters_proxy_bootstrap_cron_scheduled' => self::listClustersProxyBootstrapCronScheduled(),
            'list_top_unlabeled_local_projection' => self::listTopUnlabeledLocalProjection(),
            'list_top_unlabeled_proxy_success' => self::listTopUnlabeledProxySuccess(),
            'list_top_unlabeled_proxy_canonical_envelope' => self::listTopUnlabeledProxyCanonicalEnvelope(),
            'list_top_unlabeled_proxy_invalid_envelope' => self::listTopUnlabeledProxyInvalidEnvelope(),
            'list_top_unlabeled_proxy_bootstrapping_fallback' => self::listTopUnlabeledProxyBootstrappingFallback(),
            'list_top_unlabeled_targeted_repair' => self::listTopUnlabeledTargetedRepair(),
            'list_cluster_labels_local_projection' => self::listClusterLabelsLocalProjection(),
            'list_cluster_labels_proxy_success' => self::listClusterLabelsProxySuccess(),
            'list_cluster_labels_proxy_invalid_envelope' => self::listClusterLabelsProxyInvalidEnvelope(),
            'get_cluster_detail_local_projection' => self::getClusterDetailLocalProjection(),
            'get_cluster_detail_proxy_success' => self::getClusterDetailProxySuccess(),
            'get_cluster_detail_local_not_found' => self::getClusterDetailLocalNotFound(),
            'get_cluster_members_local_projection' => self::getClusterMembersLocalProjection(),
            'get_cluster_members_local_not_found' => self::getClusterMembersLocalNotFound(),
            'get_cluster_members_proxy_success' => self::getClusterMembersProxySuccess(),
            'get_cluster_members_proxy_invalid_envelope' => self::getClusterMembersProxyInvalidEnvelope(),
            'get_cluster_members_targeted_repair' => self::getClusterMembersTargetedRepair(),
            default => throw new \InvalidArgumentException(
                sprintf('Unknown characterization scenario: %s', esc_html($scenario_id))
            ),
        };
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClustersLocalProjection(): array
    {
        self::resetHarness();

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
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return [
                    'cluster-local' => [
                        [
                            'identity_uuid' => 'identity-1',
                            'attachment_id' => 10,
                            'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                        ],
                    ],
                ];
            }
        };

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int
            {
                return 1;
            }
            public function get_last_updated(string $tenant_id): ?string
            {
                return gmdate('Y-m-d H:i:s');
            }
        };

        $controller = new ClustersController($clustersRepo, $membersRepo, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $request->set_param('limit', 1);

        return [
            'response' => $controller->list_clusters($request),
            'side_effects' => self::baseSideEffects('local_projection'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClustersProxySuccess(): array
    {
        self::resetHarness();
        $controller = self::proxyFallbackController();
        // Canonical envelope required — bare-array fabrication is forbidden [rg-015].
        self::queueHttpResponse([
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

        return [
            'response' => $controller->list_clusters($request),
            'side_effects' => self::baseSideEffects('proxy_success'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClustersProxyInvalidEnvelope(): array
    {
        self::resetHarness();
        $controller = self::proxyFallbackController();
        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'clusters' => [],
                'limit' => 50,
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');

        return [
            'response' => $controller->list_clusters($request),
            'side_effects' => self::baseSideEffects('proxy_invalid_envelope'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClustersProxyBootstrapInlineSuccess(): array
    {
        self::resetHarness();
        $syncSpy = new class() implements SyncPullJobInterface {
            public bool $performedBypass = false;
            public function perform(string $tenant_id): SyncPullResult
            {
                return SyncPullResult::ok();
            }
            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
            {
                $this->performedBypass = true;
                return SyncPullResult::ok();
            }
            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
            {
                return SyncPullResult::ok();
            }
        };

        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            $syncSpy,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        self::queueHttpResponse([
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
        $sideEffects = self::baseSideEffects('proxy_bootstrap_inline_success');
        $sideEffects['sync_bypass_performed'] = $syncSpy->performedBypass;

        return ['response' => $response, 'side_effects' => $sideEffects];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClustersProxyBootstrapCronScheduled(): array
    {
        self::resetHarness();
        $syncJob = new class() implements SyncPullJobInterface {
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
        };

        $controller = new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            $syncJob,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        self::queueHttpResponse([
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

        return [
            'response' => $controller->list_clusters($request),
            'side_effects' => self::baseSideEffects('proxy_bootstrap_cron_scheduled'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listTopUnlabeledLocalProjection(): array
    {
        self::resetHarness();
        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';
        $GLOBALS['__ac_attachment_urls'][102] = 'http://example.test/media/102.jpg';

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
                        'identity_count' => 2,
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
                            'identity_uuid' => 'identity-1',
                            'media_id' => 101,
                            'cluster_uuid' => 'cluster-1',
                            'distance' => 0.0,
                        ],
                        [
                            'identity_uuid' => 'identity-2',
                            'media_id' => 102,
                            'cluster_uuid' => 'cluster-1',
                            'distance' => 0.0,
                        ],
                    ],
                ];
            }
        };

        $controller = new ClustersController($clustersRepo, $membersRepo, self::freshLocalSyncStateRepository(), null, new ClusterResponseMapper(), new MemberResponseMapper());
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');

        return [
            'response' => $controller->list_top_unlabeled_clusters($request),
            'side_effects' => self::baseSideEffects('local_projection'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listTopUnlabeledProxySuccess(): array
    {
        self::resetHarness();
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int
            {
                return 0;
            }
            public function get_last_updated(string $tenant_id): ?string
            {
                return null;
            }
        };

        $controller = new ClustersController(null, null, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        // Canonical envelope required — bare-array fabrication is forbidden [rg-015].
        // One schema-valid served row plus one empty-rep drop (R2-02 / R3).
        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'clusters' => [
                    [
                        'id' => 'cluster-proxy-top',
                        'tenant_id' => 'tenant-1',
                        'label' => null,
                        'is_labeled' => false,
                        'is_auto_label' => false,
                        'identity_count' => 2,
                        'user_confirmed' => false,
                        'representatives' => [
                            ['id' => 'rep-proxy-top', 'media_id' => 101, 'is_pinned' => false],
                        ],
                    ],
                    [
                        'id' => 'cluster-proxy-drop',
                        'tenant_id' => 'tenant-1',
                        'label' => null,
                        'identity_count' => 4,
                        'representatives' => [],
                    ],
                ],
                'limit' => 10,
                'total' => 2,
                'truncated' => false,
            ]),
        ]);
        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'snapshot_version' => 0,
                'clusters' => [],
                'members' => [],
                'empty' => true,
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');

        return [
            'response' => $controller->list_top_unlabeled_clusters($request),
            'side_effects' => self::baseSideEffects('proxy_success'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listTopUnlabeledProxyInvalidEnvelope(): array
    {
        self::resetHarness();
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int
            {
                return 0;
            }
            public function get_last_updated(string $tenant_id): ?string
            {
                return null;
            }
        };

        $controller = new ClustersController(null, null, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'clusters' => [],
                'limit' => 10,
            ]),
        ]);
        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'snapshot_version' => 0,
                'clusters' => [],
                'members' => [],
                'empty' => true,
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');

        return [
            'response' => $controller->list_top_unlabeled_clusters($request),
            'side_effects' => self::baseSideEffects('proxy_invalid_envelope'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listTopUnlabeledProxyBootstrappingFallback(): array
    {
        self::resetHarness();
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int
            {
                return 0;
            }
            public function get_last_updated(string $tenant_id): ?string
            {
                return null;
            }
        };

        $controller = new ClustersController(null, null, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        self::queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        self::queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        self::queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');

        return [
            'response' => $controller->list_top_unlabeled_clusters($request),
            'side_effects' => self::baseSideEffects('proxy_bootstrapping_fallback'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listTopUnlabeledTargetedRepair(): array
    {
        self::resetHarness();
        $GLOBALS['__ac_attachment_urls'][202] = 'http://example.test/media/202.jpg';
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
            public function __construct(private \stdClass $projectionState)
            {
            }
            public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
            {
                return $this->projectionState->membersByCluster;
            }
        };

        $syncJob = new class($projectionState) implements TargetedSyncPullJobInterface {
            public function __construct(private \stdClass $projectionState)
            {
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
        $sideEffects = self::baseSideEffects('targeted_repair');
        $sideEffects['targeted_cluster_ids'] = $projectionState->targetedClusterIds;

        return ['response' => $response, 'side_effects' => $sideEffects];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClusterLabelsLocalProjection(): array
    {
        self::resetHarness();
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
            public function list_labels(string $tenant_id, string $search = '', int $limit = self::DEFAULT_LIST_LIMIT): array
            {
                return [
                    ['label' => 'Alice', 'total_count' => 2],
                ];
            }
        };

        $controller = new ClustersController(
            $clustersRepo,
            new NullIdentityMembersRepository(),
            self::freshLocalSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/labels');
        $request->set_param('search', 'ali');
        $request->set_param('limit', 1);

        return [
            'response' => $controller->list_cluster_labels($request),
            'side_effects' => self::baseSideEffects('local_projection'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClusterLabelsProxySuccess(): array
    {
        self::resetHarness();
        $controller = self::proxyFallbackController();
        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'labels' => ['Alice', 'Alicia'],
                'limit' => 50,
                'total' => 2,
                'truncated' => false,
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/labels');

        return [
            'response' => $controller->list_cluster_labels($request),
            'side_effects' => self::baseSideEffects('proxy_success'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClusterLabelsProxyInvalidEnvelope(): array
    {
        self::resetHarness();
        $controller = self::proxyFallbackController();
        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'labels' => ['Alice', 'Alicia'],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/labels');

        return [
            'response' => $controller->list_cluster_labels($request),
            'side_effects' => self::baseSideEffects('proxy_invalid_envelope'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function getClusterDetailLocalProjection(): array
    {
        self::resetHarness();
        $clustersRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
            public function find_by_uuid(string $cluster_uuid): ?array
            {
                return [
                    'cluster_uuid' => $cluster_uuid,
                    'label' => 'Detail Local',
                    'identity_count' => 2,
                ];
            }
        };

        $membersRepo = new class() extends NullIdentityMembersRepository {
            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
            {
                return [
                    [
                        'identity_uuid' => 'identity-detail',
                        'attachment_id' => 55,
                        'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                    ],
                ];
            }
        };

        $controller = new ClustersController(
            $clustersRepo,
            $membersRepo,
            self::freshLocalSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-detail-local');
        $request->set_param('cluster_id', 'cluster-detail-local');

        return [
            'response' => $controller->get_cluster_detail($request),
            'side_effects' => self::baseSideEffects('local_projection'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function getClusterDetailProxySuccess(): array
    {
        self::resetHarness();
        $controller = self::proxyFallbackController();
        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => 'cluster-proxy-detail',
                'label' => 'Proxy Detail',
                'identity_count' => 3,
                'members' => [],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-proxy-detail');
        $request->set_param('cluster_id', 'cluster-proxy-detail');

        return [
            'response' => $controller->get_cluster_detail($request),
            'side_effects' => self::baseSideEffects('proxy_success'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function getClusterDetailLocalNotFound(): array
    {
        self::resetHarness();
        $controller = new ClustersController(
            new class() extends NullClustersRepository {
                public function has_projection_rows_for_tenant(string $tenant_id): bool
                {
                    return true;
                }
                public function find_by_uuid(string $cluster_uuid): ?array
                {
                    return null;
                }
            },
            new NullIdentityMembersRepository(),
            self::freshLocalSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/missing-cluster');
        $request->set_param('cluster_id', 'missing-cluster');

        return [
            'response' => $controller->get_cluster_detail($request),
            'side_effects' => self::baseSideEffects('local_not_found'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function getClusterMembersLocalProjection(): array
    {
        self::resetHarness();
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
                        'identity_uuid' => 'identity-member',
                        'attachment_id' => 77,
                        'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                        'total_count' => 1,
                    ],
                ];
            }
        };

        $controller = new ClustersController(
            $clustersRepo,
            $membersRepo,
            self::freshLocalSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-local/members');
        $request->set_param('cluster_id', 'cluster-local');

        return [
            'response' => $controller->get_cluster_members($request),
            'side_effects' => self::baseSideEffects('local_projection'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function getClusterMembersProxySuccess(): array
    {
        self::resetHarness();
        $controller = self::proxyFallbackController();
        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'members' => [
                    ['id' => 'member-proxy', 'media_id' => 88],
                ],
                'limit' => 500,
                'total' => 1,
                'truncated' => false,
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-proxy/members');
        $request->set_param('cluster_id', 'cluster-proxy');

        return [
            'response' => $controller->get_cluster_members($request),
            'side_effects' => self::baseSideEffects('proxy_success'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function getClusterMembersProxyInvalidEnvelope(): array
    {
        self::resetHarness();
        $controller = self::proxyFallbackController();
        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'members' => [],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/cluster-proxy/members');
        $request->set_param('cluster_id', 'cluster-proxy');

        return [
            'response' => $controller->get_cluster_members($request),
            'side_effects' => self::baseSideEffects('proxy_invalid_envelope'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function getClusterMembersTargetedRepair(): array
    {
        self::resetHarness();
        $projectionState = new \stdClass();
        $projectionState->members = [];
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
                    'label' => 'Needs Members',
                    'identity_count' => 4,
                ];
            }
        };

        $membersRepo = new class($projectionState) extends NullIdentityMembersRepository {
            public function __construct(private \stdClass $projectionState)
            {
            }
            public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
            {
                return $this->projectionState->members;
            }
        };

        $syncJob = new class($projectionState) implements TargetedSyncPullJobInterface {
            public function __construct(private \stdClass $projectionState)
            {
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
                $this->projectionState->members = [
                    [
                        'identity_uuid' => 'identity-repaired-member',
                        'attachment_id' => 303,
                        'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                        'total_count' => 1,
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
        $sideEffects = self::baseSideEffects('targeted_repair');
        $sideEffects['targeted_cluster_ids'] = $projectionState->targetedClusterIds;

        return ['response' => $response, 'side_effects' => $sideEffects];
    }

    private static function resetHarness(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $GLOBALS['__ac_do_action_log'] = [];
        $GLOBALS['__ac_http_queue'] = [];
        $GLOBALS['__ac_http_calls'] = [];
        $GLOBALS['__ac_options']['acx_recognition_url'] = 'http://localhost:8000';
        $GLOBALS['__ac_options']['acx_recognition_api_key'] = 'test-key';
    }

    private static function proxyFallbackController(): ClustersController
    {
        return new ClustersController(
            new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );
    }

    private static function freshLocalSyncStateRepository(): NullSyncStateRepository
    {
        return new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int
            {
                return 1;
            }

            public function get_last_updated(string $tenant_id): ?string
            {
                return gmdate('Y-m-d H:i:s');
            }
        };
    }

    /**
     * @param array<string,mixed>|\WP_Error $response
     */
    private static function queueHttpResponse(array|\WP_Error $response): void
    {
        $GLOBALS['__ac_http_queue'][] = $response;
    }

    /**
     * @param array<string,mixed> $extra
     * @return array<string,mixed>
     */
    private static function baseSideEffects(string $branch, array $extra = []): array
    {
        return array_merge(
            [
                'branch' => $branch,
                'scheduled_event_count' => count($GLOBALS['__ac_scheduled'] ?? []),
                'scheduled_events' => self::scheduledEvents(),
                'http_call_count' => count($GLOBALS['__ac_http_calls'] ?? []),
                'do_action_log' => $GLOBALS['__ac_do_action_log'] ?? [],
            ],
            $extra
        );
    }

    /**
     * @return list<array{hook: string, args: array<int,mixed>}>
     */
    private static function scheduledEvents(): array
    {
        $events = [];
        foreach ($GLOBALS['__ac_scheduled'] ?? [] as $key => $entry) {
            if (! is_array($entry)) {
                continue;
            }

            $hook = explode('::', (string) $key, 2)[0];
            $events[] = [
                'hook' => $hook,
                'args' => $entry['args'] ?? [],
            ];
        }

        return $events;
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClustersStaleProjectionSync(): array
    {
        self::resetHarness();

        $syncSpy = new class() implements SyncPullJobInterface {
            public bool $performed = false;
            public string $tenantId = '';
            public function perform(string $tenant_id): SyncPullResult
            {
                $this->performed = true;
                $this->tenantId = $tenant_id;
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

        $controller = new ClustersController(
            $clustersRepo,
            new class() extends NullIdentityMembersRepository {
                public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
                {
                    return [];
                }
            },
            new class() extends NullSyncStateRepository {
                public function get_snapshot_version(string $tenant_id): int
                {
                    return 5;
                }
                public function get_last_updated(string $tenant_id): ?string
                {
                    return '2020-01-01 00:00:00';
                }
            },
            $syncSpy,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        return [
            'response' => $response,
            'side_effects' => self::baseSideEffects('stale_projection_sync', [
                'sync_performed' => $syncSpy->performed,
            ]),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listClustersStaleProjectionSyncFailed(): array
    {
        self::resetHarness();

        $syncJob = new class() implements SyncPullJobInterface {
            public function perform(string $tenant_id): SyncPullResult
            {
                throw new \RuntimeException('sync boom');
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

        $controller = new ClustersController(
            new class() extends NullClustersRepository {
                public function has_projection_rows_for_tenant(string $tenant_id): bool
                {
                    return true;
                }
                public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
                {
                    return [
                        [
                            'cluster_uuid' => 'cluster-stale-fail',
                            'label' => 'Stale Fail',
                            'identity_count' => 1,
                        ],
                    ];
                }
            },
            new class() extends NullIdentityMembersRepository {
                public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
                {
                    return [];
                }
            },
            new class() extends NullSyncStateRepository {
                public function get_snapshot_version(string $tenant_id): int
                {
                    return 5;
                }
                public function get_last_updated(string $tenant_id): ?string
                {
                    return '2020-01-01 00:00:00';
                }
            },
            $syncJob,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters');
        $response = $controller->list_clusters($request);

        return [
            'response' => $response,
            'side_effects' => self::baseSideEffects('stale_projection_sync_failed'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function listTopUnlabeledProxyCanonicalEnvelope(): array
    {
        self::resetHarness();

        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int
            {
                return 0;
            }
            public function get_last_updated(string $tenant_id): ?string
            {
                return null;
            }
        };

        $controller = new ClustersController(null, null, $syncRepo, null, new ClusterResponseMapper(), new MemberResponseMapper());

        self::queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'clusters' => [
                    [
                        'id' => 'cluster-canonical',
                        'tenant_id' => 'tenant-1',
                        'label' => null,
                        'is_labeled' => false,
                        'is_auto_label' => false,
                        'identity_count' => 2,
                        'user_confirmed' => false,
                        'representatives' => [
                            ['id' => 'rep-canonical', 'media_id' => 102, 'is_pinned' => false],
                        ],
                    ],
                    [
                        'id' => 'cluster-canonical-drop',
                        'tenant_id' => 'tenant-1',
                        'label' => null,
                        'identity_count' => 3,
                        'representatives' => [],
                    ],
                ],
                'limit' => 10,
                'total' => 2,
                'truncated' => false,
            ]),
        ]);
        self::queueHttpResponse([
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

        return [
            'response' => $response,
            'side_effects' => self::baseSideEffects('proxy_canonical_envelope'),
        ];
    }

    /**
     * @return array{response: mixed, side_effects: array<string,mixed>}
     */
    private static function getClusterMembersLocalNotFound(): array
    {
        self::resetHarness();

        $controller = new ClustersController(
            new class() extends NullClustersRepository {
                public function has_projection_rows_for_tenant(string $tenant_id): bool
                {
                    return true;
                }
                public function find_by_uuid(string $cluster_uuid): ?array
                {
                    return null;
                }
            },
            new NullIdentityMembersRepository(),
            self::freshLocalSyncStateRepository(),
            null,
            new ClusterResponseMapper(),
            new MemberResponseMapper()
        );

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/missing-members/members');
        $request->set_param('cluster_id', 'missing-members');
        $response = $controller->get_cluster_members($request);

        return [
            'response' => $response,
            'side_effects' => self::baseSideEffects('local_not_found'),
        ];
    }
}
