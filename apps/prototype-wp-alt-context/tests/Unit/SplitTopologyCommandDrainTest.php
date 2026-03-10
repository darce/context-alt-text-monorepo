<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Sovereign\Sync\CrossPlaneSequencer;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SnapshotClientTransport;
use AltContext\Sovereign\Sync\SnapshotProjectorInterface;
use AltContext\Sovereign\Sync\SplitTopologyCommandDrain;
use AltContext\Sovereign\Sync\TopologyCommandRepositoryInterface;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

class SplitTopologyCommandDrainTest extends TestCase
{
    public function testRegisterSchedulesDrainWhenPendingCommandsExist(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];

        $drain = new SplitTopologyCommandDrain(
            $repository,
            new SplitTransportFake([]),
            new SnapshotClientFake([]),
            new SnapshotProjectorFake(),
            new SplitClustersRepositoryFake(),
            new SplitMembersRepositoryFake(),
            new SplitSyncStateRepositoryFake()
        );
        $drain->register();

        $this->assertArrayHasKey('acx_sync_drain_split_topology_commands', $GLOBALS['__ac_actions']);
        $this->assertTrue($this->isHookScheduled('acx_sync_drain_split_topology_commands'));
    }

    public function testDrainAppliesDirectMemberDeltaAndMarksCommandReconciled(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'command_id' => 'remote-command-1',
                'status' => 'applied',
                'original_cluster_id' => 'cluster-source',
                'new_cluster_ids' => ['cluster-new-1', 'cluster-new-2'],
                'member_delta' => [
                    'source_cluster_id' => 'cluster-source',
                    'remaining_identity_ids' => ['identity-1'],
                    'created_clusters' => [
                        ['cluster_id' => 'cluster-new-1', 'identity_ids' => ['identity-2']],
                        ['cluster_id' => 'cluster-new-2', 'identity_ids' => ['identity-3']],
                    ],
                ],
                'moved_counts' => [1, 1],
                'affected_cluster_ids' => ['cluster-source', 'cluster-new-1', 'cluster-new-2'],
                'result_snapshot_version' => 44,
            ], 200),
        ]);
        $snapshotClient = new SnapshotClientFake([]);
        $projector = new SnapshotProjectorFake();
        $clustersRepository = new SplitClustersRepositoryFake();
        $membersRepository = new SplitMembersRepositoryFake();
        $syncStateRepository = new SplitSyncStateRepositoryFake();

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            $snapshotClient,
            $projector,
            $clustersRepository,
            $membersRepository,
            $syncStateRepository
        );
        $drain->drain();

        $this->assertCount(1, $repository->dispatchResults);
        $this->assertSame('remote-command-1', $repository->dispatchResults[0]['command_id']);
        $this->assertCount(1, $repository->reconciled);
        $this->assertSame([['tenant-test', 'cluster-new-1', '', 1, 44, 'thumb-2.jpg'], ['tenant-test', 'cluster-new-2', '', 1, 44, 'thumb-3.jpg']], $clustersRepository->upsertedProjectionClusters);
        $this->assertSame([['cluster-source', 1, 44, 'thumb-1.jpg']], $clustersRepository->updatedProjectionClusters);
        $this->assertSame([['identity-2', 'cluster-new-1', 44], ['identity-3', 'cluster-new-2', 44]], $membersRepository->projectionAssignments);
        $this->assertSame([['tenant-test', 44]], $syncStateRepository->snapshotUpserts);
        $this->assertSame([], $projector->projectCalls);
        $this->assertSame([['tenant-test']], $syncStateRepository->metricRefreshCalls);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testDrainFallsBackToTargetedReconciliationWhenMemberDeltaIsIncomplete(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'command_id' => 'remote-command-2',
                'status' => 'applied',
                'original_cluster_id' => 'cluster-source',
                'new_cluster_ids' => ['cluster-new-1'],
                'member_delta' => [
                    'source_cluster_id' => 'cluster-source',
                    'remaining_identity_ids' => ['identity-1'],
                    'created_clusters' => [],
                ],
                'moved_counts' => [2],
                'affected_cluster_ids' => ['cluster-source', 'cluster-new-1'],
                'result_snapshot_version' => 55,
            ], 200),
        ]);
        $snapshotClient = new SnapshotClientFake(
            [],
            [
                'tenant-test::cluster-new-1|cluster-source' => [
                    'snapshot_version' => 55,
                    'clusters' => [
                        ['cluster_uuid' => 'cluster-source'],
                        ['cluster_uuid' => 'cluster-new-1'],
                    ],
                    'members' => [
                        ['identity_uuid' => 'identity-1', 'cluster_uuid' => 'cluster-source'],
                        ['identity_uuid' => 'identity-2', 'cluster_uuid' => 'cluster-new-1'],
                        ['identity_uuid' => 'identity-3', 'cluster_uuid' => 'cluster-new-1'],
                    ],
                ],
            ]
        );
        $projector = new SnapshotProjectorFake();
        $clustersRepository = new SplitClustersRepositoryFake();
        $membersRepository = new SplitMembersRepositoryFake();
        $syncStateRepository = new SplitSyncStateRepositoryFake();

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            $snapshotClient,
            $projector,
            $clustersRepository,
            $membersRepository,
            $syncStateRepository
        );
        $drain->drain();

        $this->assertCount(1, $repository->dispatchResults);
        $this->assertCount(1, $repository->reconciled);
        $this->assertSame([['tenant-test', 'cluster-new-1', '', 2, 55, 'thumb-2.jpg']], $clustersRepository->upsertedProjectionClusters);
        $this->assertSame([['cluster-source', 1, 55, 'thumb-1.jpg']], $clustersRepository->updatedProjectionClusters);
        $this->assertSame([['identity-2', 'cluster-new-1', 55], ['identity-3', 'cluster-new-1', 55]], $membersRepository->projectionAssignments);
        $this->assertSame([], $projector->projectCalls);
        $this->assertSame([], $snapshotClient->fetchCalls);
        $this->assertSame([['tenant-test', ['cluster-new-1', 'cluster-source']]], $snapshotClient->targetedFetchCalls);
    }

    public function testDrainProjectsLatestSnapshotWhenBackendReportsConflict(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'conflict_code' => 'cluster_version_conflict',
                'backend_version' => 88,
                'message' => 'stale split request',
            ], 409),
        ]);
        $snapshotClient = new SnapshotClientFake([
            'tenant-test' => [
                'snapshot_version' => 88,
                'clusters' => [],
                'members' => [],
            ],
        ]);
        $projector = new SnapshotProjectorFake();
        $syncStateRepository = new SplitSyncStateRepositoryFake();

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            $snapshotClient,
            $projector,
            new SplitClustersRepositoryFake(),
            new SplitMembersRepositoryFake(),
            $syncStateRepository
        );
        $drain->drain();

        $this->assertCount(1, $repository->dispatchResults);
        $this->assertSame('conflict', $repository->dispatchResults[0]['status']);
        $this->assertSame(['tenant-test'], $snapshotClient->fetchCalls);
        $this->assertSame([['tenant-test', ['snapshot_version' => 88, 'clusters' => [], 'members' => []]]], $projector->projectCalls);
        $this->assertSame([['tenant-test']], $syncStateRepository->metricRefreshCalls);
        $this->assertSame([], $repository->failures);
    }

    public function testDrainMarksCommandFailedAfterRetryExhaustion(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand([
                'attempts' => 4,
            ]),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([
            new WP_Error('transport_error', 'network down'),
        ]);

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            new SnapshotClientFake([]),
            new SnapshotProjectorFake(),
            new SplitClustersRepositoryFake(),
            new SplitMembersRepositoryFake(),
            new SplitSyncStateRepositoryFake()
        );
        $drain->drain();

        $this->assertCount(1, $repository->failures);
        $this->assertSame('failed', $repository->failures[0]['status']);
        $this->assertSame('transport_error', $repository->failures[0]['error_code']);
    }

    public function testDrainReschedulesWhenBatchLeavesMorePendingCommands(): void
    {
        add_filter(
            'acx_split_topology_drain_batch_size',
            static fn (): int => 1
        );

        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(['id' => 7, 'idempotency_key' => 'idem-split-1']),
            $this->pendingSplitCommand(['id' => 8, 'idempotency_key' => 'idem-split-2']),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'command_id' => 'remote-command-1',
                'status' => 'applied',
                'original_cluster_id' => 'cluster-source',
                'new_cluster_ids' => ['cluster-new-1', 'cluster-new-2'],
                'member_delta' => [
                    'source_cluster_id' => 'cluster-source',
                    'remaining_identity_ids' => ['identity-1'],
                    'created_clusters' => [
                        ['cluster_id' => 'cluster-new-1', 'identity_ids' => ['identity-2']],
                        ['cluster_id' => 'cluster-new-2', 'identity_ids' => ['identity-3']],
                    ],
                ],
                'moved_counts' => [1, 1],
                'affected_cluster_ids' => ['cluster-source', 'cluster-new-1', 'cluster-new-2'],
                'result_snapshot_version' => 44,
            ], 200),
        ]);

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            new SnapshotClientFake([]),
            new SnapshotProjectorFake(),
            new SplitClustersRepositoryFake(),
            new SplitMembersRepositoryFake(),
            new SplitSyncStateRepositoryFake()
        );
        $drain->drain();

        $this->assertSame(1, count($repository->find_pending()));
        $this->assertTrue($this->isHookScheduled('acx_sync_drain_split_topology_commands'));
    }

    public function testDrainReconcilesPreviouslyAppliedCommandFromDurableResultPayload(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand([
                'status' => 'applied',
                'result_json' => wp_json_encode([
                    'command_id' => 'remote-command-3',
                    'status' => 'applied',
                    'original_cluster_id' => 'cluster-source',
                    'new_cluster_ids' => ['cluster-new-1', 'cluster-new-2'],
                    'member_delta' => [
                        'source_cluster_id' => 'cluster-source',
                        'remaining_identity_ids' => ['identity-1'],
                        'created_clusters' => [
                            ['cluster_id' => 'cluster-new-1', 'identity_ids' => ['identity-2']],
                            ['cluster_id' => 'cluster-new-2', 'identity_ids' => ['identity-3']],
                        ],
                    ],
                    'moved_counts' => [1, 1],
                    'affected_cluster_ids' => ['cluster-source', 'cluster-new-1', 'cluster-new-2'],
                    'result_snapshot_version' => 66,
                ]),
            ]),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([]);
        $snapshotClient = new SnapshotClientFake([]);
        $projector = new SnapshotProjectorFake();
        $clustersRepository = new SplitClustersRepositoryFake();
        $membersRepository = new SplitMembersRepositoryFake();
        $syncStateRepository = new SplitSyncStateRepositoryFake();

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            $snapshotClient,
            $projector,
            $clustersRepository,
            $membersRepository,
            $syncStateRepository
        );
        $drain->drain();

        $this->assertSame([], $transport->requests);
        $this->assertCount(1, $repository->reconciled);
        $this->assertSame([['tenant-test', 66]], $syncStateRepository->snapshotUpserts);
        $this->assertSame([], $projector->projectCalls);
    }

    public function testDrainReconcilesPreviouslyAppliedCommandFromDurableTargetedSnapshotAfterRestart(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand([
                'status' => 'applied',
                'result_json' => wp_json_encode([
                    'command_id' => 'remote-command-5',
                    'status' => 'applied',
                    'original_cluster_id' => 'cluster-source',
                    'new_cluster_ids' => ['cluster-new-1'],
                    'member_delta' => [
                        'source_cluster_id' => 'cluster-source',
                        'remaining_identity_ids' => ['identity-1'],
                        'created_clusters' => [],
                    ],
                    'affected_cluster_ids' => ['cluster-source', 'cluster-new-1'],
                    'result_snapshot_version' => 78,
                ]),
            ]),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $snapshotClient = new SnapshotClientFake(
            [],
            [
                'tenant-test::cluster-new-1|cluster-source' => [
                    'snapshot_version' => 78,
                    'clusters' => [
                        ['cluster_uuid' => 'cluster-source'],
                        ['cluster_uuid' => 'cluster-new-1'],
                    ],
                    'members' => [
                        ['identity_uuid' => 'identity-1', 'cluster_uuid' => 'cluster-source'],
                        ['identity_uuid' => 'identity-2', 'cluster_uuid' => 'cluster-new-1'],
                        ['identity_uuid' => 'identity-3', 'cluster_uuid' => 'cluster-new-1'],
                    ],
                ],
            ]
        );
        $transport = new SplitTransportFake([]);
        $clustersRepository = new SplitClustersRepositoryFake();
        $membersRepository = new SplitMembersRepositoryFake();
        $syncStateRepository = new SplitSyncStateRepositoryFake();

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            $snapshotClient,
            new SnapshotProjectorFake(),
            $clustersRepository,
            $membersRepository,
            $syncStateRepository
        );
        $drain->drain();

        $this->assertSame([], $transport->requests);
        $this->assertCount(1, $repository->reconciled);
        $this->assertSame([['tenant-test', ['cluster-new-1', 'cluster-source']]], $snapshotClient->targetedFetchCalls);
        $this->assertSame([['tenant-test', 'cluster-new-1', '', 2, 78, 'thumb-2.jpg']], $clustersRepository->upsertedProjectionClusters);
        $this->assertSame([['cluster-source', 1, 78, 'thumb-1.jpg']], $clustersRepository->updatedProjectionClusters);
    }

    public function testDrainUsesTargetedSnapshotBeforeFullSnapshotRepairFallback(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'command_id' => 'remote-command-4',
                'status' => 'applied',
                'original_cluster_id' => 'cluster-source',
                'new_cluster_ids' => ['cluster-new-1'],
                'member_delta' => [
                    'source_cluster_id' => 'cluster-source',
                    'remaining_identity_ids' => ['identity-1'],
                    'created_clusters' => [],
                ],
                'affected_cluster_ids' => ['cluster-source', 'cluster-new-1'],
                'result_snapshot_version' => 77,
            ], 200),
        ]);
        $snapshotClient = new SnapshotClientFake(
            [
                'tenant-test' => [
                    'snapshot_version' => 77,
                    'clusters' => [],
                    'members' => [],
                ],
            ],
            []
        );
        $projector = new SnapshotProjectorFake();

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            $snapshotClient,
            $projector,
            new SplitClustersRepositoryFake(),
            new SplitMembersRepositoryFake(),
            new SplitSyncStateRepositoryFake()
        );
        $drain->drain();

        $this->assertSame([['tenant-test', ['cluster-new-1', 'cluster-source']]], $snapshotClient->targetedFetchCalls);
        $this->assertSame(['tenant-test'], $snapshotClient->fetchCalls);
        $this->assertCount(1, $projector->projectCalls);
    }

    public function testDrainBlocksPendingSplitBehindEarlierReplayPlaneTopologyOperation(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand([
                'created_at' => '2026-03-10 12:00:01',
            ]),
        ]);
        global $wpdb;
        $wpdb->mockResults = [[
            'id' => 2,
            'tenant_id' => 'tenant-test',
            'operation_type' => 'cluster_merged',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-source',
            'payload' => '{"target_cluster_id":"cluster-target"}',
            'status' => 'pending',
            'created_at' => '2026-03-10 12:00:00',
        ],];

        $sequencer = new CrossPlaneSequencer($repository);
        $transport = new SplitTransportFake([]);
        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            new SnapshotClientFake([]),
            new SnapshotProjectorFake(),
            new SplitClustersRepositoryFake(),
            new SplitMembersRepositoryFake(),
            new SplitSyncStateRepositoryFake(),
            $sequencer
        );
        $drain->drain();

        $this->assertSame([], $transport->requests);
        $this->assertTrue($this->isHookScheduled('acx_sync_drain_split_topology_commands'));
    }

    public function testQueuedSplitCommandFlowsThroughDirectApplyConvergence(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $repository = new SplitTopologyCommandRepositoryFake([]);
        $clustersRepository = new SplitClustersRepositoryFake();
        $membersRepository = new SplitMembersRepositoryFake();
        $syncStateRepository = new SplitSyncStateRepositoryFake();

        $controller = new ClusterMutationsController(
            $clustersRepository,
            $syncStateRepository,
            $membersRepository,
            null,
            $repository
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/split');
        $request->set_param('cluster_id', 'cluster-source');
        $request->set_param('n_clusters', 3);

        $response = $controller->split_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame('pending', $response->get_data()['status']);
        $this->assertCount(1, $repository->find_pending());
        $tenantId = (string) $repository->pendingRows[0]['tenant_id'];

        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'command_id' => 'remote-command-flow-1',
                'status' => 'applied',
                'original_cluster_id' => 'cluster-source',
                'new_cluster_ids' => ['cluster-new-1', 'cluster-new-2'],
                'member_delta' => [
                    'source_cluster_id' => 'cluster-source',
                    'remaining_identity_ids' => ['identity-1'],
                    'created_clusters' => [
                        ['cluster_id' => 'cluster-new-1', 'identity_ids' => ['identity-2']],
                        ['cluster_id' => 'cluster-new-2', 'identity_ids' => ['identity-3']],
                    ],
                ],
                'moved_counts' => [1, 1],
                'affected_cluster_ids' => ['cluster-source', 'cluster-new-1', 'cluster-new-2'],
                'result_snapshot_version' => 88,
            ], 200),
        ]);

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            new SnapshotClientFake([]),
            new SnapshotProjectorFake(),
            $clustersRepository,
            $membersRepository,
            $syncStateRepository
        );
        $drain->drain();

        $this->assertCount(1, $repository->dispatchResults);
        $this->assertCount(1, $repository->reconciled);
        $this->assertSame('reconciled', $repository->pendingRows[0]['status']);
        $this->assertSame([['identity-2', 'cluster-new-1', 88], ['identity-3', 'cluster-new-2', 88]], $membersRepository->projectionAssignments);
        $this->assertSame([[$tenantId, 88]], $syncStateRepository->snapshotUpserts);
    }

    public function testQueuedSplitCommandFallsBackToTargetedReconciliationBeforeRepairSnapshot(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $repository = new SplitTopologyCommandRepositoryFake([]);
        $clustersRepository = new SplitClustersRepositoryFake();
        $membersRepository = new SplitMembersRepositoryFake();
        $syncStateRepository = new SplitSyncStateRepositoryFake();

        $controller = new ClusterMutationsController(
            $clustersRepository,
            $syncStateRepository,
            $membersRepository,
            null,
            $repository
        );

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/cluster-source/split');
        $request->set_param('cluster_id', 'cluster-source');
        $request->set_param('n_clusters', 2);

        $response = $controller->split_cluster($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertCount(1, $repository->find_pending());
        $tenantId = (string) $repository->pendingRows[0]['tenant_id'];

        $snapshotClient = new SnapshotClientFake(
            [],
            [
                $tenantId . '::cluster-new-1|cluster-source' => [
                    'snapshot_version' => 89,
                    'clusters' => [
                        ['cluster_uuid' => 'cluster-source'],
                        ['cluster_uuid' => 'cluster-new-1'],
                    ],
                    'members' => [
                        ['identity_uuid' => 'identity-1', 'cluster_uuid' => 'cluster-source'],
                        ['identity_uuid' => 'identity-2', 'cluster_uuid' => 'cluster-new-1'],
                        ['identity_uuid' => 'identity-3', 'cluster_uuid' => 'cluster-new-1'],
                    ],
                ],
            ]
        );
        $projector = new SnapshotProjectorFake();
        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'command_id' => 'remote-command-flow-2',
                'status' => 'applied',
                'original_cluster_id' => 'cluster-source',
                'new_cluster_ids' => ['cluster-new-1'],
                'member_delta' => [
                    'source_cluster_id' => 'cluster-source',
                    'remaining_identity_ids' => ['identity-1'],
                    'created_clusters' => [],
                ],
                'affected_cluster_ids' => ['cluster-source', 'cluster-new-1'],
                'result_snapshot_version' => 89,
            ], 200),
        ]);

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            $snapshotClient,
            $projector,
            $clustersRepository,
            $membersRepository,
            $syncStateRepository
        );
        $drain->drain();

        $this->assertCount(1, $repository->reconciled);
        $this->assertSame([[$tenantId, ['cluster-new-1', 'cluster-source']]], $snapshotClient->targetedFetchCalls);
        $this->assertSame([], $snapshotClient->fetchCalls);
        $this->assertSame([], $projector->projectCalls);
        $this->assertSame([['identity-2', 'cluster-new-1', 89], ['identity-3', 'cluster-new-1', 89]], $membersRepository->projectionAssignments);
    }

    /**
     * @param array<string,mixed> $overrides
     * @return array<string,mixed>
     */
    private function pendingSplitCommand(array $overrides = []): array
    {
        return array_merge([
            'id' => 7,
            'tenant_id' => 'tenant-test',
            'command_type' => 'cluster_split',
            'entity_key' => 'cluster-source',
            'payload_json' => [
                'cluster_id' => 'cluster-source',
                'n_clusters' => 3,
            ],
            'idempotency_key' => 'idem-split-1',
            'expected_base_version' => 12,
            'attempts' => 0,
            'status' => 'pending',
        ], $overrides);
    }

    private function isHookScheduled(string $hook): bool
    {
        foreach (array_keys($GLOBALS['__ac_scheduled']) as $key) {
            if (str_starts_with($key, $hook . '::')) {
                return true;
            }
        }

        foreach (array_keys($GLOBALS['__ac_action_scheduler'] ?? []) as $key) {
            if (str_starts_with($key, $hook . '::')) {
                return true;
            }
        }

        return false;
    }
}

class SplitTopologyCommandRepositoryFake implements TopologyCommandRepositoryInterface
{
    /** @var array<int,array<string,mixed>> */
    public array $pendingRows;
    /** @var array<int,array<string,mixed>> */
    public array $dispatchResults = [];
    /** @var array<int,array<string,mixed>|null> */
    public array $reconciled = [];
    /** @var array<int,array<string,string>> */
    public array $failures = [];

    /**
     * @param array<int,array<string,mixed>> $pending
     */
    public function __construct(array $pending)
    {
        $this->pendingRows = $pending;
    }

    public function enqueue(
        string $tenant_id,
        string $command_type,
        string $entity_key,
        int $expected_base_version,
        array $payload,
        ?string $idempotency_key = null
    ): int|false {
        $nextId = count($this->pendingRows) + 1;
        $this->pendingRows[] = [
            'id' => $nextId,
            'tenant_id' => $tenant_id,
            'command_type' => $command_type,
            'entity_key' => $entity_key,
            'expected_base_version' => $expected_base_version,
            'payload_json' => $payload,
            'idempotency_key' => (string) $idempotency_key,
            'attempts' => 0,
            'status' => 'pending',
            'created_at' => '2026-03-10 12:00:00',
            'result_json' => null,
        ];

        return $nextId;
    }

    public function find_pending(?string $tenant_id = null, int $limit = 25): array
    {
        $pending = array_values(array_filter(
            $this->pendingRows,
            static fn (array $command): bool => ($command['status'] ?? 'pending') === 'pending'
        ));

        if (null === $tenant_id) {
            return array_slice($pending, 0, $limit);
        }

        return array_values(array_filter(
            $pending,
            static fn (array $command): bool => $command['tenant_id'] === $tenant_id
        ));
    }

    public function find_reconcilable(?string $tenant_id = null, int $limit = 25): array
    {
        $reconcilable = array_values(array_filter(
            $this->pendingRows,
            static fn (array $command): bool => in_array(($command['status'] ?? 'pending'), ['pending', 'applied'], true)
        ));

        if (null === $tenant_id) {
            return array_slice($reconcilable, 0, $limit);
        }

        return array_values(array_filter(
            $reconcilable,
            static fn (array $command): bool => $command['tenant_id'] === $tenant_id
        ));
    }

    public function update_status(int $command_id, string $status, ?array $result_payload = null, ?string $backend_command_id = null): bool
    {
        $this->setPendingStatus($command_id, $status);
        return true;
    }

    public function record_dispatch_result(int $command_id, array $response): bool
    {
        $this->setPendingStatus($command_id, (string) ($response['status'] ?? 'applied'));
        $this->dispatchResults[] = $response;
        return true;
    }

    public function mark_reconciled(int $command_id, ?array $result_payload = null): bool
    {
        $this->reconciled[] = $result_payload;
        $this->setPendingStatus($command_id, 'reconciled');
        return true;
    }

    public function record_failure(int $command_id, string $status, string $error_code, string $error_message, bool $increment_attempt = true): bool
    {
        $this->setPendingStatus($command_id, $status);
        $this->failures[] = [
            'status' => $status,
            'error_code' => $error_code,
            'error_message' => $error_message,
        ];
        return true;
    }

    private function setPendingStatus(int $command_id, string $status): void
    {
        foreach ($this->pendingRows as $index => $command) {
            if (($command['id'] ?? 0) !== $command_id) {
                continue;
            }

            if ('pending' === $status) {
                $this->pendingRows[$index]['status'] = 'pending';
                return;
            }

            $this->pendingRows[$index]['status'] = $status;
            return;
        }
    }
}

class SplitTransportFake extends SnapshotClientTransport
{
    /** @var array<int,WP_REST_Response|WP_Error> */
    private array $responses;
    /** @var array<int,array<string,mixed>> */
    public array $requests = [];

    /**
     * @param array<int,WP_REST_Response|WP_Error> $responses
     */
    public function __construct(array $responses)
    {
        $this->responses = $responses;
    }

    public function request(string $method, string $path, array $body = array(), array $query = array()): WP_REST_Response|\WP_Error
    {
        $this->requests[] = [
            'method' => $method,
            'path' => $path,
            'body' => $body,
            'query' => $query,
        ];
        return array_shift($this->responses) ?? new WP_REST_Response(['message' => 'missing fake response'], 500);
    }
}

class SnapshotClientFake extends SnapshotClient
{
    /** @var array<string,array<string,mixed>> */
    private array $snapshotsByTenant;
    /** @var array<string,array<string,mixed>> */
    private array $targetedSnapshotsByKey;
    /** @var array<int,string> */
    public array $fetchCalls = [];
    /** @var array<int,array{0:string,1:array<int,string>}> */
    public array $targetedFetchCalls = [];

    /**
     * @param array<string,array<string,mixed>> $snapshotsByTenant
     * @param array<string,array<string,mixed>> $targetedSnapshotsByKey
     */
    public function __construct(array $snapshotsByTenant, array $targetedSnapshotsByKey = [])
    {
        $this->snapshotsByTenant = $snapshotsByTenant;
        $this->targetedSnapshotsByKey = $targetedSnapshotsByKey;
    }

    public function fetch_snapshot(string $tenant_id): array|\WP_Error
    {
        $this->fetchCalls[] = $tenant_id;
        return $this->snapshotsByTenant[$tenant_id] ?? new \WP_Error('missing_snapshot', 'missing snapshot');
    }

    public function fetch_targeted_snapshot(string $tenant_id, array $cluster_ids): array|\WP_Error
    {
        sort($cluster_ids);
        $this->targetedFetchCalls[] = [$tenant_id, $cluster_ids];
        $key = $tenant_id . '::' . implode('|', $cluster_ids);
        return $this->targetedSnapshotsByKey[$key] ?? new \WP_Error('missing_targeted_snapshot', 'missing targeted snapshot');
    }
}

class SnapshotProjectorFake implements SnapshotProjectorInterface
{
    /** @var array<int,array{0:string,1:array<string,mixed>}> */
    public array $projectCalls = [];

    public function project(string $tenant_id, array $snapshot): void
    {
        $this->projectCalls[] = [$tenant_id, $snapshot];
    }
}

class SplitClustersRepositoryFake extends NullClustersRepository
{
    /** @var array<string,array<string,mixed>> */
    private array $clustersByUuid = [
        'cluster-source' => [
            'cluster_uuid' => 'cluster-source',
            'snapshot_version' => 12,
            'label' => 'Source',
        ],
    ];
    /** @var array<int,array{0:string,1:string,2:string,3:int,4:int,5:?string}> */
    public array $upsertedProjectionClusters = [];
    /** @var array<int,array{0:string,1:int,2:int,3:?string}> */
    public array $updatedProjectionClusters = [];

    public function find_by_uuid(string $cluster_uuid): ?array
    {
        return $this->clustersByUuid[$cluster_uuid] ?? null;
    }

    public function upsert_projection_cluster(string $tenant_id, string $cluster_uuid, string $label, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null): int
    {
        $this->upsertedProjectionClusters[] = [$tenant_id, $cluster_uuid, $label, $identity_count, $snapshot_version, $representative_thumb_path];
        return 1;
    }

    public function update_projection_cluster(string $cluster_uuid, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null): int
    {
        $this->updatedProjectionClusters[] = [$cluster_uuid, $identity_count, $snapshot_version, $representative_thumb_path];
        return 1;
    }
}

class SplitMembersRepositoryFake extends NullIdentityMembersRepository
{
    /** @var array<int,array<string,mixed>> */
    private array $sourceMembers = [
        ['identity_uuid' => 'identity-1', 'cluster_uuid' => 'cluster-source', 'thumb_path' => 'thumb-1.jpg'],
        ['identity_uuid' => 'identity-2', 'cluster_uuid' => 'cluster-source', 'thumb_path' => 'thumb-2.jpg'],
        ['identity_uuid' => 'identity-3', 'cluster_uuid' => 'cluster-source', 'thumb_path' => 'thumb-3.jpg'],
    ];

    /** @var array<int,array{0:string,1:string,2:int}> */
    public array $projectionAssignments = [];

    public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
    {
        if ('cluster-source' !== $cluster_uuid) {
            return [];
        }

        return $this->sourceMembers;
    }

    public function assign_to_cluster_for_projection(string $identity_uuid, string $target_cluster_uuid, int $projection_version): int
    {
        $this->projectionAssignments[] = [$identity_uuid, $target_cluster_uuid, $projection_version];
        return 1;
    }
}

class SplitSyncStateRepositoryFake extends NullSyncStateRepository
{
    /** @var array<int,array{0:string,1:int}> */
    public array $snapshotUpserts = [];
    /** @var array<int,array{0:string}> */
    public array $metricRefreshCalls = [];
    public string $lastTouchedTenantId = '';

    public function get_snapshot_version(string $tenant_id): int
    {
        return 12;
    }

    public function touch_local_curation_marker(string $tenant_id): void
    {
        $this->lastTouchedTenantId = $tenant_id;
    }

    public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void
    {
        $this->snapshotUpserts[] = [$tenant_id, $snapshot_version];
    }

    public function refresh_curation_metrics(string $tenant_id): void
    {
        $this->metricRefreshCalls[] = [$tenant_id];
    }
}
