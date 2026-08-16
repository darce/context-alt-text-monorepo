<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Sync\CrossPlaneSequencer;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SnapshotClientTransport;
use AltContext\Sovereign\Sync\SnapshotProjectorInterface;
use AltContext\Sovereign\Sync\SplitTopologyCommandDrain;
use AltContext\Sovereign\Sync\TopologyCommandRepository;
use AltContext\Sovereign\Sync\TopologyCommandRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
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
        $this->assertSame([['tenant-test', 'cluster-new-1', '', 1, 44, 'thumb-2.jpg', null, false], ['tenant-test', 'cluster-new-2', '', 1, 44, 'thumb-3.jpg', null, false]], $clustersRepository->upsertedProjectionClusters);
        $this->assertSame([['cluster-source', 1, 44, 'thumb-1.jpg', null, false]], $clustersRepository->updatedProjectionClusters);
        $this->assertSame([['identity-2', 'cluster-new-1', 44], ['identity-3', 'cluster-new-2', 44]], $membersRepository->projectionAssignments);
        $this->assertSame([['tenant-test', 44]], $syncStateRepository->snapshotUpserts);
        $this->assertSame([], $projector->projectCalls);
        $this->assertSame([['tenant-test']], $syncStateRepository->metricRefreshCalls);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    /**
     * E21-14-BR-11 / rg-007: ProjectionQueryException after claim must mark that
     * command failed and let the drain continue to the next command.
     */
    public function testDrainMarksCommandFailedOnProjectionQueryExceptionAndContinues(): void
    {
        $first = $this->pendingSplitCommand();
        $first['id'] = 1;
        $second = $this->pendingSplitCommand();
        $second['id'] = 2;
        $second['entity_key'] = 'cluster-source-b';

        $repository = new SplitTopologyCommandRepositoryFake([$first, $second]);
        global $wpdb;
        $wpdb->mockResults = [];

        $appliedPayload = [
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
        ];
        $transport = new SplitTransportFake([
            new WP_REST_Response($appliedPayload, 200),
            new WP_REST_Response(array_merge($appliedPayload, ['command_id' => 'remote-command-2']), 200),
        ]);

        $membersRepository = new class() extends SplitMembersRepositoryFake {
            public function list_for_cluster(
                string $cluster_uuid,
                int $limit = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT,
                int $offset = 0,
                ?string $tenant_id = null
            ): array {
                throw new ProjectionQueryException(
                    'Projection query failed [identity_members.list_for_cluster]: schema missing assigned_at'
                );
            }
        };

        $drain = new SplitTopologyCommandDrain(
            $repository,
            $transport,
            new SnapshotClientFake([]),
            new SnapshotProjectorFake(),
            new SplitClustersRepositoryFake(),
            $membersRepository,
            new SplitSyncStateRepositoryFake()
        );
        $drain->drain();

        $this->assertNotEmpty($repository->failures, 'claimed command must be marked failed, not left in limbo');
        $this->assertSame('projection_query_failed', $repository->failures[0]['error_code']);
        $this->assertGreaterThanOrEqual(2, count($repository->claimCalls), 'drain must continue to next command');
        $this->assertSame([], $repository->reconciled);
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
        $this->assertSame([['tenant-test', 'cluster-new-1', '', 2, 55, 'thumb-2.jpg', null, false]], $clustersRepository->upsertedProjectionClusters);
        $this->assertSame([['cluster-source', 1, 55, 'thumb-1.jpg', null, false]], $clustersRepository->updatedProjectionClusters);
        $this->assertSame([['identity-2', 'cluster-new-1', 55], ['identity-3', 'cluster-new-1', 55]], $membersRepository->projectionAssignments);
        $this->assertSame([], $projector->projectCalls);
        $this->assertSame([], $snapshotClient->fetchCalls);
        $this->assertSame([['tenant-test', ['cluster-new-1', 'cluster-source']]], $snapshotClient->targetedFetchCalls);
    }

    public function testDrainPagesSourceMembersWhenDirectMemberDeltaExceedsRepositoryCap(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];

        $allSourceMembers = [];
        for ($index = 1; $index <= 501; $index++) {
            $allSourceMembers[] = [
                'identity_uuid' => sprintf('identity-%03d', $index),
                'cluster_uuid' => 'cluster-source',
                'thumb_path' => sprintf('thumb-%03d.jpg', $index),
            ];
        }

        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'command_id' => 'remote-command-paged',
                'status' => 'applied',
                'original_cluster_id' => 'cluster-source',
                'new_cluster_ids' => ['cluster-new-1'],
                'member_delta' => [
                    'source_cluster_id' => 'cluster-source',
                    'remaining_identity_ids' => ['identity-001'],
                    'created_clusters' => [
                        [
                            'cluster_id' => 'cluster-new-1',
                            'identity_ids' => array_map(
                                static fn (int $memberIndex): string => sprintf('identity-%03d', $memberIndex),
                                range(2, 501)
                            ),
                        ],
                    ],
                ],
                'moved_counts' => [500],
                'affected_cluster_ids' => ['cluster-source', 'cluster-new-1'],
                'result_snapshot_version' => 77,
            ], 200),
        ]);

        $snapshotClient = new SnapshotClientFake([]);
        $projector = new SnapshotProjectorFake();
        $clustersRepository = new SplitClustersRepositoryFake();
        $membersRepository = new SplitMembersRepositoryFake($allSourceMembers, true);
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
        $this->assertSame([
            ['cluster-source', IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, 0, 'tenant-test'],
            ['cluster-source', IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, 'tenant-test'],
            ['cluster-source', IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, 0, 'tenant-test'],
            ['cluster-source', IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, 'tenant-test'],
        ], $membersRepository->listCalls);
        $this->assertSame([], $snapshotClient->targetedFetchCalls);
        $this->assertSame([], $snapshotClient->fetchCalls);
        $this->assertSame([], $projector->projectCalls);
    }

    public function testDrainLogsWarningAndFallsBackWhenPagedReadHitsOuterCeiling(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $GLOBALS['__ac_error_log'] = [];

        $allSourceMembers = [];
        for ($index = 1; $index <= 10050; $index++) {
            $allSourceMembers[] = [
                'identity_uuid' => sprintf('identity-%05d', $index),
                'cluster_uuid' => 'cluster-source',
                'thumb_path' => sprintf('thumb-%05d.jpg', $index),
                'total_count' => 10050,
            ];
        }

        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'command_id' => 'remote-command-over-ceiling',
                'status' => 'applied',
                'original_cluster_id' => 'cluster-source',
                'new_cluster_ids' => ['cluster-new-1'],
                'member_delta' => [
                    'source_cluster_id' => 'cluster-source',
                    'remaining_identity_ids' => ['identity-00001'],
                    'created_clusters' => [
                        [
                            'cluster_id' => 'cluster-new-1',
                            'identity_ids' => array_map(
                                static fn (int $memberIndex): string => sprintf('identity-%05d', $memberIndex),
                                range(2, 10050)
                            ),
                        ],
                    ],
                ],
                'moved_counts' => [10049],
                'affected_cluster_ids' => ['cluster-source', 'cluster-new-1'],
                'result_snapshot_version' => 88,
            ], 200),
        ]);

        $snapshotClient = new SnapshotClientFake(
            ['tenant-test' => ['snapshot_version' => 88, 'clusters' => [], 'members' => []]],
            ['tenant-test::cluster-new-1|cluster-source' => new \WP_Error('targeted-missing', 'targeted missing')]
        );
        $projector = new SnapshotProjectorFake();
        $clustersRepository = new SplitClustersRepositoryFake();
        $membersRepository = new SplitMembersRepositoryFake($allSourceMembers, true);
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
        $this->assertCount(1, $projector->projectCalls);
        $this->assertStringContainsString('capped member pagination for cluster cluster-source tenant tenant-test after 20 pages', $GLOBALS['__ac_error_log'][0] ?? '');

        unset($GLOBALS['__ac_error_log']);
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
        // Targeted snapshot is fetched at most once before the full-snapshot fallback;
        // re-fetching would double a remote call and change the fallback hook payload.
        $this->assertCount(1, $snapshotClient->targetedFetchCalls);
        $this->assertSame([['tenant-test', ['snapshot_version' => 88, 'clusters' => [], 'members' => []]]], $projector->projectCalls);
        $this->assertSame([['tenant-test']], $syncStateRepository->metricRefreshCalls);
        $this->assertSame([], $repository->failures);
    }

    public function testDrainConflictFetchesTargetedSnapshotOnceAndCarriesItsPayloadIntoFullSnapshotFallbackHook(): void
    {
        // Conflict reconcile: targeted snapshot is consulted, fails reconcile (no member
        // delta), then the full-snapshot repair also errors. The fallback conflict hook must
        // carry the *single* targeted-snapshot payload — re-fetching it (a) doubles a remote
        // call and (b) changes the hook payload. Pins the slice-3 extraction seam.
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'conflict_code' => 'cluster_version_conflict',
                'backend_version' => 91,
                'message' => 'stale split request',
            ], 409),
        ]);
        $targetedPayload = ['snapshot_version' => 5, 'clusters' => [], 'members' => []];
        $snapshotClient = new SnapshotClientFake(
            [],
            ['tenant-test::cluster-source' => $targetedPayload]
        );
        $projector = new SnapshotProjectorFake();
        $syncStateRepository = new SplitSyncStateRepositoryFake();

        $capturedPayloads = [];
        unset($GLOBALS['__ac_actions']['acx_split_topology_conflict_detected']);
        add_action(
            'acx_split_topology_conflict_detected',
            static function ($command, $result, $reconciled) use (&$capturedPayloads): void {
                $capturedPayloads[] = $reconciled;
            },
            10,
            3
        );

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

        // Targeted snapshot fetched exactly once (no doubled remote call on the fallback).
        $this->assertSame([['tenant-test', ['cluster-source']]], $snapshotClient->targetedFetchCalls);
        // Full-snapshot repair attempted once and errored, so nothing is projected.
        $this->assertSame(['tenant-test'], $snapshotClient->fetchCalls);
        $this->assertSame([], $projector->projectCalls);
        // The fallback hook fires once carrying the single targeted-snapshot payload verbatim.
        $this->assertSame([$targetedPayload], $capturedPayloads);
        $this->assertSame('conflict', $repository->dispatchResults[0]['status']);
    }

    public function testDrainApplyMemberDeltaRollsBackWhenCommitFails(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $wpdb->queryResults['COMMIT'] = false;
        $transport = new SplitTransportFake([
            new WP_REST_Response([
                'command_id' => 'remote-command-rollback',
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
        $clustersRepository = new SplitClustersRepositoryFake();
        $membersRepository = new SplitMembersRepositoryFake();
        $syncStateRepository = new SplitSyncStateRepositoryFake();

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

        $startIndex = array_search('START TRANSACTION', $wpdb->queries, true);
        $commitIndex = array_search('COMMIT', $wpdb->queries, true);
        $rollbackIndex = array_search('ROLLBACK', $wpdb->queries, true);
        $this->assertIsInt($startIndex);
        $this->assertIsInt($commitIndex);
        $this->assertIsInt($rollbackIndex);
        $this->assertGreaterThan($startIndex, $commitIndex);
        $this->assertGreaterThan($commitIndex, $rollbackIndex);
        $this->assertCount(0, $repository->reconciled);
        $this->assertCount(1, $repository->failures);
        $this->assertSame('applied', $repository->failures[0]['status']);
        $this->assertSame('projection_reconcile_failed', $repository->failures[0]['error_code']);
    }

    public function testDrainIsolatesTransportFailureAndContinuesProcessingPeerCommand(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(['id' => 7, 'idempotency_key' => 'idem-split-1']),
            $this->pendingSplitCommand(['id' => 8, 'idempotency_key' => 'idem-split-2']),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([
            new WP_Error('transport_error', 'network down'),
            new WP_REST_Response([
                'command_id' => 'remote-command-2',
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

        $this->assertCount(1, $repository->failures);
        $this->assertSame('pending', $repository->failures[0]['status']);
        $this->assertSame('transport_error', $repository->failures[0]['error_code']);
        $this->assertCount(1, $repository->reconciled);
    }

    public function testDrainKeepsCommandPendingWhenAttemptsRemainBelowMax(): void
    {
        add_filter(
            'acx_split_topology_max_attempts',
            static fn (): int => 5
        );

        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand([
                'attempts' => 3,
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
        $this->assertSame('pending', $repository->failures[0]['status']);
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

    public function testDrainMarksUnreconcilableAppliedCommandFailedAfterReconcileAttemptCap(): void
    {
        // COR-2: an applied command whose local reconcile never succeeds must reach
        // terminal `failed` within resolve_max_attempts() drains instead of looping
        // forever. The reconcile-attempt counter is dedicated, independent of dispatch attempts.
        add_filter(
            'acx_split_topology_max_attempts',
            static fn (): int => 2
        );

        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand([
                'status' => 'applied',
                'result_json' => wp_json_encode([
                    'status' => 'applied',
                    'original_cluster_id' => 'cluster-source',
                    'new_cluster_ids' => ['cluster-new-1'],
                    'member_delta' => [
                        'source_cluster_id' => 'cluster-source',
                        'remaining_identity_ids' => ['identity-1'],
                        // created_clusters empty against one new_cluster_id => member-delta incomplete.
                        'created_clusters' => [],
                    ],
                    'affected_cluster_ids' => ['cluster-source', 'cluster-new-1'],
                    'result_snapshot_version' => 90,
                ]),
            ]),
        ]);
        global $wpdb;
        $wpdb->mockResults = [];

        // No dispatch (already applied); no targeted/full snapshot available => every reconcile attempt fails.
        $drain = new SplitTopologyCommandDrain(
            $repository,
            new SplitTransportFake([]),
            new SnapshotClientFake([]),
            new SnapshotProjectorFake(),
            new SplitClustersRepositoryFake(),
            new SplitMembersRepositoryFake(),
            new SplitSyncStateRepositoryFake()
        );

        // Drain 1: reconcile fails, attempt 1 < 2 => stays applied, still reconcilable.
        $drain->drain();
        $this->assertSame('applied', $repository->pendingRows[0]['status']);
        $this->assertCount(1, $repository->find_reconcilable());

        // Drain 2: reconcile fails, attempt 2 >= 2 => terminal failed, no longer reconcilable.
        $drain->drain();
        $this->assertSame('failed', $repository->pendingRows[0]['status']);
        $this->assertSame(
            'projection_reconcile_failed',
            $repository->failures[array_key_last($repository->failures)]['error_code']
        );
        $this->assertCount(0, $repository->find_reconcilable());

        // Drain 3: nothing reconcilable => stopped re-fetching, no further failure writes.
        $failureCountAtTerminal = count($repository->failures);
        $drain->drain();
        $this->assertCount($failureCountAtTerminal, $repository->failures);
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
        $this->assertSame([['tenant-test', 'cluster-new-1', '', 2, 78, 'thumb-2.jpg', null, false]], $clustersRepository->upsertedProjectionClusters);
        $this->assertSame([['cluster-source', 1, 78, 'thumb-1.jpg', null, false]], $clustersRepository->updatedProjectionClusters);
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

    public function testRecordFailureClearsClaimedAtSoRetryableRowIsImmediatelyReclaimable(): void
    {
        // CON-4 review (REVA-1): a retryable failure that returns the row to pending/applied
        // must clear claimed_at, else the lease parks the row out of find_reconcilable for 300s.
        global $wpdb;
        $repository = new TopologyCommandRepository('wp_acx_topology_commands');
        $repository->record_failure(7, 'applied', 'projection_reconcile_failed', 'retry', false);

        $cleared = array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_contains($query, 'UPDATE wp_acx_topology_commands SET')
                && str_contains($query, 'claimed_at = NULL')
        );
        $this->assertNotEmpty($cleared, 'record_failure must clear claimed_at for prompt re-claim.');
    }

    public function testRecordReconcileFailureClearsClaimedAtSoRetryableRowIsImmediatelyReclaimable(): void
    {
        global $wpdb;
        $repository = new TopologyCommandRepository('wp_acx_topology_commands');
        $repository->record_reconcile_failure(7, 'applied', 'projection_reconcile_failed', 'retry');

        $cleared = array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_contains($query, 'reconcile_attempts = reconcile_attempts + 1')
                && str_contains($query, 'claimed_at = NULL')
        );
        $this->assertNotEmpty($cleared, 'record_reconcile_failure must clear claimed_at for prompt re-claim.');
    }

    public function testTerminalWritesGuardOnExpectedStatusSoStaleWorkerWriteIsNoOp(): void
    {
        // CON-4-FU-1: defense-in-depth on top of the lease claim. If a drain's processing
        // exceeds the claim lease and the row is re-claimed by a peer mid-flight, the late
        // drain's terminal write must match 0 rows instead of clobbering the peer's state.
        // Each terminal write carries the status it expects in its WHERE.
        global $wpdb;
        $repository = new TopologyCommandRepository('wp_acx_topology_commands');

        $repository->update_status(7, 'applied', null, null, 'pending');
        $repository->record_dispatch_result(9, ['status' => 'applied'], 'pending');
        $repository->mark_reconciled(11, null, 'applied');
        $repository->record_failure(13, 'applied', 'projection_reconcile_failed', 'retry', false, 'applied');
        $repository->record_reconcile_failure(15, 'failed', 'projection_reconcile_failed', 'retry', 'applied');

        $expectedGuards = [
            "WHERE id = 7 AND status = 'pending'",     // update_status transition
            "WHERE id = 9 AND status = 'pending'",     // record_dispatch_result -> update_status
            "WHERE id = 11 AND status = 'applied'",    // mark_reconciled status flip applied->reconciled
            "WHERE id = 11 AND status = 'reconciled'", // mark_reconciled projection_reconciled_at write
            "WHERE id = 13 AND status = 'applied'",    // record_failure reconcile-fail
            "WHERE id = 15 AND status = 'applied'",    // record_reconcile_failure
        ];
        foreach ($expectedGuards as $guard) {
            $matched = array_filter(
                $wpdb->queries,
                static fn (string $query): bool => str_contains($query, $guard)
            );
            $this->assertNotEmpty($matched, "Expected a status-guarded terminal write containing: {$guard}");
        }
    }

    public function testTerminalWriteReturnsFalseWhenStaleStatusGuardMatchesZeroRows(): void
    {
        // CON-4-FU-1: a guarded write whose expected status no longer matches affects 0 rows;
        // the method reports that no-op back to the drain so the stale worker stops.
        global $wpdb;
        $wpdb->defaultUpdateResult = 0;
        $wpdb->defaultQueryResult = 0;
        $repository = new TopologyCommandRepository('wp_acx_topology_commands');

        $this->assertFalse($repository->update_status(7, 'applied', null, null, 'pending'));
        $this->assertFalse($repository->record_dispatch_result(7, ['status' => 'applied'], 'pending'));
        $this->assertFalse($repository->mark_reconciled(7, null, 'applied'));
        $this->assertFalse($repository->record_failure(7, 'applied', 'projection_reconcile_failed', 'retry', false, 'applied'));
        $this->assertFalse($repository->record_reconcile_failure(7, 'failed', 'projection_reconcile_failed', 'retry', 'applied'));

        // Backward-compat: an unguarded call keeps the legacy "no DB error" success semantics.
        $this->assertTrue($repository->update_status(7, 'applied'));
    }

    public function testDrainSkipsPendingDispatchWhenCommandClaimLostToPeerDrain(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        $repository->claimGranted = false;
        global $wpdb;
        $wpdb->mockResults = [];
        $transport = new SplitTransportFake([
            new WP_REST_Response(['command_id' => 'remote-x', 'status' => 'applied'], 200),
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

        // CON-4: claim lost (peer drain owns it) -> no dispatch, no terminal writes.
        $this->assertSame([[7, 'pending']], $repository->claimCalls);
        $this->assertSame([], $transport->requests);
        $this->assertCount(0, $repository->dispatchResults);
        $this->assertCount(0, $repository->failures);
    }

    public function testDrainSkipsAppliedReconcileWhenCommandClaimLostToPeerDrain(): void
    {
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand([
                'status' => 'applied',
                'result_json' => wp_json_encode([
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
        $repository->claimGranted = false;
        global $wpdb;
        $wpdb->mockResults = [];
        $membersRepository = new SplitMembersRepositoryFake();

        $drain = new SplitTopologyCommandDrain(
            $repository,
            new SplitTransportFake([]),
            new SnapshotClientFake([]),
            new SnapshotProjectorFake(),
            new SplitClustersRepositoryFake(),
            $membersRepository,
            new SplitSyncStateRepositoryFake()
        );
        $drain->drain();

        // CON-4 headline: a 2nd drain that lost the claim must NOT re-apply the member delta,
        // so an interleaved user reassign is not reverted.
        $this->assertSame([[7, 'applied']], $repository->claimCalls);
        $this->assertCount(0, $repository->reconciled);
        $this->assertSame([], $membersRepository->projectionAssignments);
    }

    public function testDrainSkipsConflictReconcileWhenDispatchResultGuardLostToPeerDrain(): void
    {
        // CON-4-FU-1 (conflict branch): the claim is granted (lease reclaimed), but this drain's
        // slow dispatch outlived its lease and a peer re-claimed + advanced the row. The guarded
        // pending->conflict write then matches 0 rows; the drain must NOT re-project a stale
        // conflict snapshot over the peer's state — mirroring the applied branch's early return.
        // Without the guard check this test fails: reconcile_conflict would fetch + project.
        $repository = new SplitTopologyCommandRepositoryFake([
            $this->pendingSplitCommand(),
        ]);
        $repository->dispatchResultGranted = false;
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

        // Claim granted and dispatch ran, but the guarded write no-op'd -> no reconcile/projection.
        $this->assertSame([[7, 'pending']], $repository->claimCalls);
        $this->assertCount(1, $transport->requests);
        $this->assertCount(0, $repository->dispatchResults);
        $this->assertSame([], $snapshotClient->fetchCalls);
        $this->assertSame([], $snapshotClient->targetedFetchCalls);
        $this->assertSame([], $projector->projectCalls);
        $this->assertSame([], $repository->failures);
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
    /** @var array<int,array{0:int,1:string}> */
    public array $claimCalls = [];
    public bool $claimGranted = true;
    public bool $dispatchResultGranted = true;

    /**
     * @param array<int,array<string,mixed>> $pending
     */
    public function __construct(array $pending)
    {
        $this->pendingRows = $pending;
    }

    public function claim_command(int $command_id, string $expected_status): bool
    {
        $this->claimCalls[] = [$command_id, $expected_status];
        return $this->claimGranted;
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

    public function update_status(int $command_id, string $status, ?array $result_payload = null, ?string $backend_command_id = null, ?string $expected_status = null): bool
    {
        $this->setPendingStatus($command_id, $status);
        return true;
    }

    public function record_dispatch_result(int $command_id, array $response, ?string $expected_status = null): bool
    {
        if (!$this->dispatchResultGranted) {
            // Simulate the guarded pending->terminal write matching 0 rows because a peer
            // drain re-claimed past the lease and already advanced the row.
            return false;
        }

        $this->setPendingStatus($command_id, (string) ($response['status'] ?? 'applied'));
        $this->dispatchResults[] = $response;
        return true;
    }

    public function mark_reconciled(int $command_id, ?array $result_payload = null, ?string $expected_status = null): bool
    {
        $this->reconciled[] = $result_payload;
        $this->setPendingStatus($command_id, 'reconciled');
        return true;
    }

    public function record_failure(int $command_id, string $status, string $error_code, string $error_message, bool $increment_attempt = true, ?string $expected_status = null): bool
    {
        $this->setPendingStatus($command_id, $status);
        $this->failures[] = [
            'status' => $status,
            'error_code' => $error_code,
            'error_message' => $error_message,
        ];
        return true;
    }

    public function record_reconcile_failure(int $command_id, string $status, string $error_code, string $error_message, ?string $expected_status = null): bool
    {
        foreach ($this->pendingRows as $index => $command) {
            if (($command['id'] ?? 0) === $command_id) {
                $this->pendingRows[$index]['reconcile_attempts'] = (int) ($command['reconcile_attempts'] ?? 0) + 1;
                break;
            }
        }

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

    public function project_delta(string $tenant_id, array $delta): void
    {
        $this->projectCalls[] = [$tenant_id, $delta];
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
    /** @var array<int,array{0:string,1:string,2:string,3:int,4:int,5:?string,6:?string,7:bool}> */
    public array $upsertedProjectionClusters = [];
    /** @var array<int,array{0:string,1:int,2:int,3:?string,4:?string,5:bool}> */
    public array $updatedProjectionClusters = [];

    public function find_by_uuid(string $cluster_uuid): ?array
    {
        return $this->clustersByUuid[$cluster_uuid] ?? null;
    }

    public function upsert_projection_cluster(string $tenant_id, string $cluster_uuid, string $label, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false): int
    {
        $this->upsertedProjectionClusters[] = [$tenant_id, $cluster_uuid, $label, $identity_count, $snapshot_version, $representative_thumb_path, $representative_id, $is_pinned];
        return 1;
    }

    public function update_projection_cluster(string $cluster_uuid, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false): int
    {
        $this->updatedProjectionClusters[] = [$cluster_uuid, $identity_count, $snapshot_version, $representative_thumb_path, $representative_id, $is_pinned];
        return 1;
    }
}

class SplitMembersRepositoryFake extends NullIdentityMembersRepository
{
    /** @var array<int,array<string,mixed>> */
    private array $sourceMembers;

    private bool $enforceRepositoryCap;

    /** @var array<int,array{0:string,1:int,2:int,3:?string}> */
    public array $listCalls = [];

    /** @var array<int,array{0:string,1:string,2:int}> */
    public array $projectionAssignments = [];

    /**
     * @param array<int,array<string,mixed>>|null $sourceMembers
     */
    public function __construct(?array $sourceMembers = null, bool $enforceRepositoryCap = false)
    {
        $this->sourceMembers = $sourceMembers ?? [
            ['identity_uuid' => 'identity-1', 'cluster_uuid' => 'cluster-source', 'thumb_path' => 'thumb-1.jpg'],
            ['identity_uuid' => 'identity-2', 'cluster_uuid' => 'cluster-source', 'thumb_path' => 'thumb-2.jpg'],
            ['identity_uuid' => 'identity-3', 'cluster_uuid' => 'cluster-source', 'thumb_path' => 'thumb-3.jpg'],
        ];
        $this->enforceRepositoryCap = $enforceRepositoryCap;
    }

    public function list_for_cluster(string $cluster_uuid, int $limit = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, int $offset = 0, ?string $tenant_id = null): array
    {
        $this->listCalls[] = [$cluster_uuid, $limit, $offset, $tenant_id];

        if ('cluster-source' !== $cluster_uuid) {
            return [];
        }

        $effectiveLimit = $limit;
        if ($this->enforceRepositoryCap) {
            $effectiveLimit = min($effectiveLimit, IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT);
        }

        $page = array_slice($this->sourceMembers, $offset, $effectiveLimit);
        if ($this->enforceRepositoryCap) {
            foreach ($page as &$member) {
                if (!array_key_exists('total_count', $member)) {
                    $member['total_count'] = count($this->sourceMembers);
                }
            }
            unset($member);
        }

        return $page;
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
