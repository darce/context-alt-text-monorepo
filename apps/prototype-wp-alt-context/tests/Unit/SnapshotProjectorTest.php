<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\SnapshotProjector;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\Stubs\SnapshotProjectorClustersSpy;
use AltContext\Tests\Stubs\SnapshotProjectorMembersSpy;
use AltContext\Tests\Stubs\SnapshotProjectorSyncStateSpy;
use AltContext\Tests\TestCase;
use RuntimeException;

/**
 * @covers \AltContext\Sovereign\Sync\SnapshotProjector
 */
class SnapshotProjectorTest extends TestCase
{
    public function testProjectUsesTransactionAndCommitsOnSuccess(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $snapshotEvents = [];
        add_action(
            'acx_snapshot_projected',
            static function (string $tenantId, int $clusterCount, int $nonSingletonCount, int $snapshotVersion) use (&$snapshotEvents): void {
                $snapshotEvents[] = [$tenantId, $clusterCount, $nonSingletonCount, $snapshotVersion];
            },
            10,
            4
        );

        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);
        $projector->project(
            'tenant-a',
            [
                'snapshot_version' => 7,
                'clusters' => [
                    ['cluster_uuid' => 'cluster-1', 'identity_count' => 1],
                    ['cluster_uuid' => 'cluster-2', 'identity_count' => 3],
                ],
                'members' => [['identity_uuid' => 'identity-1', 'cluster_uuid' => 'cluster-1']],
            ]
        );

        global $wpdb;
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertNotContains('ROLLBACK', $wpdb->queries);

        $this->assertSame('tenant-a', $clustersRepo->tenantId);
        $this->assertSame(7, $clustersRepo->snapshotVersion);
        $this->assertCount(2, $clustersRepo->clusters);
        $this->assertCount(1, $membersRepo->members);
        $this->assertSame(7, $syncRepo->snapshotVersion);
        $this->assertSame([['tenant-a', 2, 1, 7]], $snapshotEvents);
    }

    public function testProjectSkipsStaleFullSnapshotSoNewerDataAndVersionSurvive(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);

        $projector->project(
            'tenant-ooo',
            [
                'snapshot_version' => 5,
                'clusters' => [['cluster_uuid' => 'cluster-1', 'label' => 'V5 Label', 'identity_count' => 5]],
                'members' => [],
            ]
        );

        $this->assertSame(5, $syncRepo->snapshotVersion);
        $this->assertSame('V5 Label', $clustersRepo->mergedClusters[0]['label']);

        // COR-1: a later, out-of-order v4 full snapshot must not regress the
        // already-projected v5 data or the stored version.
        $projector->project(
            'tenant-ooo',
            [
                'snapshot_version' => 4,
                'clusters' => [['cluster_uuid' => 'cluster-1', 'label' => 'V4 STALE', 'identity_count' => 1]],
                'members' => [],
            ]
        );

        $this->assertSame(5, $syncRepo->snapshotVersion, 'stored version must stay at 5 after a stale v4 snapshot');
        $this->assertSame('V5 Label', $clustersRepo->mergedClusters[0]['label'], 'v5 cluster data must survive a later v4 merge');
        $this->assertSame(5, $clustersRepo->snapshotVersion, 'merger must not be re-invoked with the stale version');
    }

    public function testProjectDeltaSkipsStaleDeltaSoVersionAndDataSurvive(): void
    {
        global $wpdb;

        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $syncRepo->snapshotVersion = 9; // tenant already projected up to v9
        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);

        $projector->project_delta(
            'tenant-delta-stale',
            [
                'snapshot_version' => 8,
                'clusters' => [['cluster_uuid' => 'cluster-x', 'label' => 'stale']],
                'members' => [],
            ]
        );

        $this->assertSame(9, $syncRepo->snapshotVersion, 'a stale delta must not regress the stored version');
        $this->assertSame([], $clustersRepo->mergedClusters, 'merger must not run for a stale delta');
        $this->assertNotContains('START TRANSACTION', $wpdb->queries, 'a stale delta should be skipped before opening a transaction');
    }

    public function testProjectRollsBackWhenRepositoryThrows(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();

        $clustersRepo->shouldThrow = true;
        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('clusters-failure');

        try {
            $projector->project(
                'tenant-b',
                [
                    'snapshot_version' => 8,
                    'clusters' => [['cluster_uuid' => 'cluster-2']],
                    'members' => [],
                ]
            );
        } finally {
            global $wpdb;
            $this->assertContains('START TRANSACTION', $wpdb->queries);
            $this->assertContains('ROLLBACK', $wpdb->queries);
        }
    }

    public function testProjectRecordsSingleTransactionConflictsInsideRollbackBoundary(): void
    {
        global $wpdb;

        $clustersRepo = new SnapshotProjectorClustersSpy([
            'cluster-missing' => [
                'cluster_uuid' => 'cluster-missing',
                'label' => 'Curated',
                'person_id' => 22,
                'curation_state' => 'dismissed',
                'snapshot_version' => 12,
                'local_revision' => 5,
            ],
        ]);
        $clustersRepo->shouldThrow = true;

        $projector = new SnapshotProjector(
            $clustersRepo,
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy(),
            new ConflictRepository()
        );

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('clusters-failure');

        try {
            $projector->project(
                'tenant-conflict-rollback',
                [
                    'snapshot_version' => 19,
                    'clusters' => [],
                    'members' => [],
                ]
            );
        } finally {
            $startIndex = array_search('START TRANSACTION', $wpdb->queries, true);
            $rollbackIndex = array_search('ROLLBACK', $wpdb->queries, true);
            $conflictIndexes = array_keys(
                array_filter(
                    $wpdb->queries,
                    static fn(string $query): bool => str_contains($query, 'INSERT INTO `wp_acx_sync_conflicts`')
                )
            );

            $this->assertIsInt($startIndex);
            $this->assertIsInt($rollbackIndex);
            $this->assertCount(1, $conflictIndexes);
            $this->assertGreaterThan($startIndex, $conflictIndexes[0]);
            $this->assertLessThan($rollbackIndex, $conflictIndexes[0]);
        }
    }

    public function testProjectRecordsBatchedConflictsInsideFirstRollbackBoundary(): void
    {
        global $wpdb;

        $chunkSize = (new \ReflectionClass(SnapshotProjector::class))->getConstant('MAX_SNAPSHOT_BATCH_SIZE');
        $this->assertIsInt($chunkSize);

        $clustersRepo = new SnapshotProjectorClustersSpy([
            'cluster-1' => [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Local Name',
                'person_id' => 31,
                'curation_state' => 'confirmed',
                'snapshot_version' => 12,
                'local_revision' => 5,
            ],
        ]);
        $clustersRepo->shouldThrow = true;

        $clusters = [];
        for ($index = 1; $index <= $chunkSize + 1; $index++) {
            $clusters[] = [
                'cluster_uuid' => 'cluster-' . $index,
                'label' => 1 === $index ? 'Backend Name' : '',
                'identity_count' => 1,
            ];
        }

        $projector = new SnapshotProjector(
            $clustersRepo,
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy(),
            new ConflictRepository()
        );

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('clusters-failure');

        try {
            $projector->project(
                'tenant-batch-conflict-rollback',
                [
                    'snapshot_version' => 20,
                    'clusters' => $clusters,
                    'members' => [],
                ]
            );
        } finally {
            $startIndex = array_search('START TRANSACTION', $wpdb->queries, true);
            $rollbackIndex = array_search('ROLLBACK', $wpdb->queries, true);
            $conflictIndexes = array_keys(
                array_filter(
                    $wpdb->queries,
                    static fn(string $query): bool => str_contains($query, 'INSERT INTO `wp_acx_sync_conflicts`')
                )
            );

            $this->assertIsInt($startIndex);
            $this->assertIsInt($rollbackIndex);
            $this->assertCount(1, $conflictIndexes);
            $this->assertGreaterThan($startIndex, $conflictIndexes[0]);
            $this->assertLessThan($rollbackIndex, $conflictIndexes[0]);
        }
    }

    public function testProjectFailsClosedWhenTransactionCannotStart(): void
    {
        global $wpdb;
        $wpdb->queryResults['START TRANSACTION'] = false;

        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy(),
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('transaction support');

        $projector->project('tenant-c', ['snapshot_version' => 3, 'clusters' => [], 'members' => []]);
    }

    public function testProjectChunksLargeClusterOnlySnapshotsAcrossMultipleTransactions(): void
    {
        global $wpdb;

        $chunkSize = (new \ReflectionClass(SnapshotProjector::class))->getConstant('MAX_SNAPSHOT_BATCH_SIZE');
        $this->assertIsInt($chunkSize, 'SnapshotProjector should declare a typed MAX_SNAPSHOT_BATCH_SIZE cap.');

        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);

        $clusters = [];
        for ($index = 1; $index <= $chunkSize + 1; $index++) {
            $clusters[] = [
                'cluster_uuid' => 'cluster-' . $index,
                'identity_count' => 1,
            ];
        }

        $projector->project(
            'tenant-batch',
            [
                'snapshot_version' => 55,
                'clusters' => $clusters,
                'members' => [],
            ]
        );

        $this->assertCount(2, $clustersRepo->mergedClusterBatches);
        $this->assertCount($chunkSize, $clustersRepo->mergedClusterBatches[0]);
        $this->assertCount(1, $clustersRepo->mergedClusterBatches[1]);
        $this->assertCount(0, $membersRepo->mergedMemberBatches);
        $this->assertCount(2, array_values(array_filter($wpdb->queries, static fn(string $query): bool => 'START TRANSACTION' === $query)));
        $this->assertCount(2, array_values(array_filter($wpdb->queries, static fn(string $query): bool => 'COMMIT' === $query)));
        $this->assertSame(55, $syncRepo->snapshotVersion);
    }

    public function testProjectWithEmptyTenantIdDispatchesWarningAndSkipsDatabaseWork(): void
    {
        $warnings = [];
        add_action(
            'acx_sovereign_warning',
            static function (string $code, array $context) use (&$warnings): void {
                $warnings[] = [$code, $context['method'] ?? ''];
            },
            10,
            2
        );

        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy(),
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $projector->project('  ', ['snapshot_version' => 4, 'clusters' => [], 'members' => []]);

        global $wpdb;
        $this->assertSame([], $wpdb->queries);
        $this->assertCount(1, $warnings);
        $this->assertSame('empty_tenant_id', $warnings[0][0]);
    }

    public function testProjectMarksEmptySnapshotAsInitializedAndRefreshesMetrics(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $snapshotEvents = [];
        add_action(
            'acx_snapshot_projected',
            static function () use (&$snapshotEvents): void {
                $snapshotEvents[] = true;
            }
        );

        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);
        $projector->project(
            'tenant-empty',
            [
                'snapshot_version' => 0,
                'clusters' => [],
                'members' => [],
                'empty' => true,
            ]
        );

        global $wpdb;
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertNotContains('ROLLBACK', $wpdb->queries);
        $this->assertSame('', $clustersRepo->tenantId);
        $this->assertSame([], $clustersRepo->clusters);
        $this->assertSame([], $membersRepo->members);
        $this->assertSame(0, $syncRepo->snapshotVersion);
        $this->assertSame('tenant-empty', $syncRepo->refreshedTenantId);
        $this->assertSame([], $snapshotEvents);
    }

    public function testProjectTreatsEmptyClusterPayloadWithSnapshotVersionAsDeltaMerge(): void
    {
        global $wpdb;

        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();

        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);
        $projector->project(
            'tenant-delta-empty',
            [
                'snapshot_version' => 21,
                'clusters' => [],
                'members' => [],
            ]
        );

        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertNotContains('ROLLBACK', $wpdb->queries);
        $this->assertSame('tenant-delta-empty', $clustersRepo->tenantId);
        $this->assertSame([], $clustersRepo->clusters);
        $this->assertSame([], $membersRepo->members);
        $this->assertSame(21, $syncRepo->snapshotVersion);
        $this->assertSame('tenant-delta-empty', $syncRepo->refreshedTenantId);
    }

    public function testProjectRecordsCuratedClusterDeletionConflictsAndRefreshesMetrics(): void
    {
        global $wpdb;

        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $syncRepo->postRefreshConflictCount = 1;
        // Two curated clusters survive in the incoming snapshot so the single
        // missing cluster stays below the E15-35 storm threshold (1 of 3 <= 50%)
        // and the per-entity conflict path is exercised.
        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy([
                'cluster-missing' => [
                    'cluster_uuid' => 'cluster-missing',
                    'label' => 'Curated',
                    'person_id' => 22,
                    'curation_state' => 'dismissed',
                    'snapshot_version' => 12,
                    'local_revision' => 5,
                ],
                'cluster-kept-1' => [
                    'cluster_uuid' => 'cluster-kept-1',
                    'label' => 'Kept One',
                    'snapshot_version' => 12,
                    'local_revision' => 2,
                ],
                'cluster-kept-2' => [
                    'cluster_uuid' => 'cluster-kept-2',
                    'label' => 'Kept Two',
                    'snapshot_version' => 12,
                    'local_revision' => 2,
                ],
            ]),
            new SnapshotProjectorMembersSpy(),
            $syncRepo,
            new ConflictRepository()
        );

        $hookCalls = [];
        add_action(
            'acx_projection_conflicts_detected',
            static function (int $count, string $tenantId) use (&$hookCalls): void {
                $hookCalls[] = [$count, $tenantId];
            },
            10,
            2
        );

        $projector->project(
            'tenant-conflicts',
            [
                'snapshot_version' => 19,
                'clusters' => [
                    ['cluster_uuid' => 'cluster-kept-1', 'label' => 'Kept One', 'identity_count' => 1],
                    ['cluster_uuid' => 'cluster-kept-2', 'label' => 'Kept Two', 'identity_count' => 1],
                ],
                'members' => [],
            ]
        );

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('INSERT INTO `wp_acx_sync_conflicts`', $sql);
        $this->assertStringContainsString("'curated_cluster_deleted'", $sql);
        $this->assertSame('tenant-conflicts', $syncRepo->refreshedTenantId);
        $this->assertSame([[1, 'tenant-conflicts']], $hookCalls);
    }

    public function testProjectRecordsPersonNameConflictsForCuratedClustersWithDivergentLabels(): void
    {
        global $wpdb;

        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $syncRepo->postRefreshConflictCount = 1;
        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy([
                'cluster-person' => [
                    'cluster_uuid' => 'cluster-person',
                    'label' => 'Local Name',
                    'person_id' => 31,
                    'curation_state' => 'confirmed',
                    'snapshot_version' => 12,
                    'local_revision' => 5,
                ],
            ]),
            new SnapshotProjectorMembersSpy(),
            $syncRepo,
            new ConflictRepository()
        );

        $hookCalls = [];
        add_action(
            'acx_projection_conflicts_detected',
            static function (int $count, string $tenantId) use (&$hookCalls): void {
                $hookCalls[] = [$count, $tenantId];
            },
            10,
            2
        );

        $projector->project(
            'tenant-person-conflicts',
            [
                'snapshot_version' => 20,
                'clusters' => [
                    [
                        'cluster_uuid' => 'cluster-person',
                        'label' => 'Backend Name',
                        'identity_count' => 1,
                    ],
                ],
                'members' => [],
            ]
        );

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('INSERT INTO `wp_acx_sync_conflicts`', $sql);
        $this->assertStringContainsString("'person_name_conflict'", $sql);
        $this->assertStringContainsString("'Backend Name'", $sql);
        $this->assertSame('tenant-person-conflicts', $syncRepo->refreshedTenantId);
        $this->assertSame([[1, 'tenant-person-conflicts']], $hookCalls);
    }

    public function testProjectEmitsConflictHookForMemberConflictsAfterMetricsRefresh(): void
    {
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $syncRepo->postRefreshConflictCount = 2;

        $hookCalls = [];
        add_action(
            'acx_projection_conflicts_detected',
            static function (int $count, string $tenantId) use (&$hookCalls): void {
                $hookCalls[] = [$count, $tenantId];
            },
            10,
            2
        );

        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy(),
            new SnapshotProjectorMembersSpy(),
            $syncRepo,
            new ConflictRepository()
        );

        $projector->project(
            'tenant-member-conflicts',
            [
                'snapshot_version' => 21,
                'clusters' => [],
                'members' => [],
            ]
        );

        $this->assertSame([[2, 'tenant-member-conflicts']], $hookCalls);
    }

    public function testProjectDeltaCommitsWhenPayloadHasNoChangedRows(): void
    {
        global $wpdb;

        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy(),
            new SnapshotProjectorMembersSpy(),
            $syncRepo
        );

        $projector->project_delta('tenant-delta', [
            'snapshot_version' => 21,
            'clusters' => [],
            'members' => [],
        ]);

        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertNotContains('ROLLBACK', $wpdb->queries);
        $this->assertSame(21, $syncRepo->snapshotVersion);
        $this->assertSame('tenant-delta', $syncRepo->refreshedTenantId);
    }

    public function testProjectDeltaThrowsWhenChangedRowsNeedReplacementSetProjection(): void
    {
        global $wpdb;

        $clustersRepo = new SnapshotProjectorClustersSpy([
            'cluster-stable' => [
                'cluster_uuid' => 'cluster-stable',
                'tenant_id' => 'tenant-delta',
                'label' => 'Stable',
                'identity_count' => 1,
                'snapshot_version' => 20,
            ],
            'cluster-changed' => [
                'cluster_uuid' => 'cluster-changed',
                'tenant_id' => 'tenant-delta',
                'label' => 'Old label',
                'identity_count' => 1,
                'snapshot_version' => 20,
            ],
        ]);
        $membersRepo = new SnapshotProjectorMembersSpy([
            'cluster-stable' => [
                [
                    'identity_uuid' => 'identity-stable',
                    'cluster_uuid' => 'cluster-stable',
                    'attachment_id' => 101,
                    'thumb_path' => 'acx://identity/identity-stable/attachment/101',
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4},"normalized":{"x":0.1,"y":0.2,"width":0.3,"height":0.4},"coordinate_space":"original_image"}',
                ],
            ],
            'cluster-changed' => [
                [
                    'identity_uuid' => 'identity-old',
                    'cluster_uuid' => 'cluster-changed',
                    'attachment_id' => 202,
                    'thumb_path' => 'acx://identity/identity-old/attachment/202',
                    'bbox_json' => '{"pixels":{"x":5,"y":6,"width":7,"height":8},"normalized":{"x":0.5,"y":0.6,"width":0.7,"height":0.8},"coordinate_space":"original_image"}',
                ],
            ],
        ]);
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $projector = new SnapshotProjector(
            $clustersRepo,
            $membersRepo,
            $syncRepo
        );

        $projector->project_delta('tenant-delta', [
            'snapshot_version' => 21,
            'clusters' => [
                [
                    'cluster_uuid' => 'cluster-changed',
                    'label' => 'New label',
                    'identity_count' => 1,
                    'representative_thumb_path' => 'acx://cluster/cluster-changed/media/303',
                ],
            ],
            'members' => [
                [
                    'identity_uuid' => 'identity-new',
                    'cluster_uuid' => 'cluster-changed',
                    'attachment_id' => 303,
                    'thumb_path' => 'acx://identity/identity-new/attachment/303',
                    'similarity' => 0.97,
                    'bbox' => [
                        'x' => 9,
                        'y' => 10,
                        'width' => 11,
                        'height' => 12,
                    ],
                ],
            ],
        ]);

        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertSame(21, $syncRepo->snapshotVersion);
        $this->assertSame('tenant-delta', $syncRepo->refreshedTenantId);

        $this->assertCount(2, $clustersRepo->mergedClusters);
        $this->assertSame(['cluster-stable', 'cluster-changed'], array_column($clustersRepo->mergedClusters, 'cluster_uuid'));
        $this->assertSame('New label', $clustersRepo->mergedClusters[1]['label']);

        $this->assertCount(2, $membersRepo->mergedMembers);
        $this->assertSame(['identity-stable', 'identity-new'], array_column($membersRepo->mergedMembers, 'identity_uuid'));
        $this->assertArrayHasKey('bbox', $membersRepo->mergedMembers[0]);
        $this->assertSame(1, $membersRepo->mergedMembers[0]['bbox']['pixels']['x']);
        $this->assertSame('cluster-changed', $membersRepo->mergedMembers[1]['cluster_uuid']);
    }

    public function testProjectDeltaPreservesExistingMembersWhenChangedClusterOmitsMemberRows(): void
    {
        global $wpdb;

        $clustersRepo = new SnapshotProjectorClustersSpy([
            'cluster-changed' => [
                'cluster_uuid' => 'cluster-changed',
                'tenant_id' => 'tenant-delta',
                'label' => '',
                'identity_count' => 7,
                'snapshot_version' => 20,
            ],
        ]);
        $membersRepo = new SnapshotProjectorMembersSpy([
            'cluster-changed' => [
                [
                    'identity_uuid' => 'identity-existing',
                    'cluster_uuid' => 'cluster-changed',
                    'attachment_id' => 202,
                    'thumb_path' => 'acx://identity/identity-existing/attachment/202',
                    'bbox_json' => '{"pixels":{"x":5,"y":6,"width":7,"height":8},"normalized":{"x":0.5,"y":0.6,"width":0.7,"height":0.8},"coordinate_space":"original_image"}',
                ],
            ],
        ]);
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);

        $projector->project_delta('tenant-delta', [
            'snapshot_version' => 21,
            'clusters' => [
                [
                    'cluster_uuid' => 'cluster-changed',
                    'label' => '',
                    'identity_count' => 7,
                    'representative_thumb_path' => 'acx://cluster/cluster-changed/media/202',
                ],
            ],
            'members' => [],
        ]);

        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertSame(['identity-existing'], array_column($membersRepo->mergedMembers, 'identity_uuid'));
        $this->assertSame('cluster-changed', $membersRepo->mergedMembers[0]['cluster_uuid']);
        $this->assertSame(21, $syncRepo->snapshotVersion);
    }

    public function testProjectDeltaPaginatesExistingProjectionRows(): void
    {
        global $wpdb;

        $clustersRepo = new SnapshotProjectorClustersSpy([
            'cluster-page-1' => [
                'cluster_uuid' => 'cluster-page-1',
                'tenant_id' => 'tenant-delta',
                'label' => 'Page 1',
                'identity_count' => 1,
                'snapshot_version' => 20,
            ],
            'cluster-page-2' => [
                'cluster_uuid' => 'cluster-page-2',
                'tenant_id' => 'tenant-delta',
                'label' => 'Page 2',
                'identity_count' => 1,
                'snapshot_version' => 20,
            ],
            'cluster-changed' => [
                'cluster_uuid' => 'cluster-changed',
                'tenant_id' => 'tenant-delta',
                'label' => 'Old label',
                'identity_count' => 1,
                'snapshot_version' => 20,
            ],
        ]);
        $clustersRepo->tenantPageSize = 2;

        $membersRepo = new SnapshotProjectorMembersSpy([
            'cluster-page-1' => [
                [
                    'identity_uuid' => 'identity-page-1',
                    'cluster_uuid' => 'cluster-page-1',
                    'attachment_id' => 101,
                    'thumb_path' => 'acx://identity/identity-page-1/attachment/101',
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4},"normalized":{"x":0.1,"y":0.2,"width":0.3,"height":0.4},"coordinate_space":"original_image"}',
                ],
            ],
            'cluster-page-2' => [
                [
                    'identity_uuid' => 'identity-page-2',
                    'cluster_uuid' => 'cluster-page-2',
                    'attachment_id' => 202,
                    'thumb_path' => 'acx://identity/identity-page-2/attachment/202',
                    'bbox_json' => '{"pixels":{"x":5,"y":6,"width":7,"height":8},"normalized":{"x":0.5,"y":0.6,"width":0.7,"height":0.8},"coordinate_space":"original_image"}',
                ],
            ],
            'cluster-changed' => [
                [
                    'identity_uuid' => 'identity-old',
                    'cluster_uuid' => 'cluster-changed',
                    'attachment_id' => 303,
                    'thumb_path' => 'acx://identity/identity-old/attachment/303',
                    'bbox_json' => '{"pixels":{"x":9,"y":10,"width":11,"height":12},"normalized":{"x":0.9,"y":1.0,"width":1.1,"height":1.2},"coordinate_space":"original_image"}',
                ],
                [
                    'identity_uuid' => 'identity-new',
                    'cluster_uuid' => 'cluster-changed',
                    'attachment_id' => 404,
                    'thumb_path' => 'acx://identity/identity-new/attachment/404',
                    'bbox_json' => '{"pixels":{"x":13,"y":14,"width":15,"height":16},"normalized":{"x":1.3,"y":1.4,"width":1.5,"height":1.6},"coordinate_space":"original_image"}',
                ],
            ],
        ]);
        $membersRepo->memberPageSize = 1;

        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $projector = new SnapshotProjector(
            $clustersRepo,
            $membersRepo,
            $syncRepo
        );

        $projector->project_delta('tenant-delta', [
            'snapshot_version' => 22,
            'clusters' => [
                [
                    'cluster_uuid' => 'cluster-changed',
                    'label' => 'New label',
                    'identity_count' => 2,
                    'representative_thumb_path' => 'acx://cluster/cluster-changed/media/404',
                ],
            ],
            'members' => [
                [
                    'identity_uuid' => 'identity-old',
                    'cluster_uuid' => 'cluster-changed',
                    'attachment_id' => 303,
                    'thumb_path' => 'acx://identity/identity-old/attachment/303',
                    'similarity' => 0.91,
                    'bbox' => [
                        'x' => 9,
                        'y' => 10,
                        'width' => 11,
                        'height' => 12,
                    ],
                ],
                [
                    'identity_uuid' => 'identity-new',
                    'cluster_uuid' => 'cluster-changed',
                    'attachment_id' => 404,
                    'thumb_path' => 'acx://identity/identity-new/attachment/404',
                    'similarity' => 0.92,
                    'bbox' => [
                        'x' => 13,
                        'y' => 14,
                        'width' => 15,
                        'height' => 16,
                    ],
                ],
            ],
        ]);

        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertSame(['cluster-page-1', 'cluster-page-2', 'cluster-changed'], array_column($clustersRepo->mergedClusters, 'cluster_uuid'));
        $this->assertSame(
            ['identity-page-1', 'identity-page-2', 'identity-old', 'identity-new'],
            array_column($membersRepo->mergedMembers, 'identity_uuid')
        );
    }

    public function testProjectThenReadReturnsProjectedNonSingletonClusters(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);

        $projector->project(
            'tenant-readback',
            [
                'snapshot_version' => 11,
                'clusters' => [
                    [
                        'cluster_uuid' => 'cluster-singleton',
                        'label' => '',
                        'curation_state' => 'active',
                        'identity_count' => 1,
                    ],
                    [
                        'cluster_uuid' => 'cluster-visible',
                        'label' => '',
                        'curation_state' => 'active',
                        'identity_count' => 4,
                    ],
                ],
                'members' => [
                    [
                        'identity_uuid' => 'identity-visible',
                        'cluster_uuid' => 'cluster-visible',
                        'attachment_id' => 42,
                        'thumb_path' => 'acx://identity/identity-visible/attachment/42',
                    ],
                ],
            ]
        );

        $facade = new ClusterFacade($clustersRepo, $membersRepo);
        $result = $facade->list_top_unlabeled('tenant-readback', 10);

        $this->assertSame(['cluster-visible', 'cluster-singleton'], array_column($result['clusters'], 'cluster_uuid'));
        $this->assertCount(1, $result['members']['cluster-visible']);
        $this->assertSame('identity-visible', $result['members']['cluster-visible'][0]['identity_uuid']);
    }

    public function testProjectPassesEnvelopeCompletenessToClustersRepository(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $projector = new SnapshotProjector(
            $clustersRepo,
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $projector->project(
            'tenant-complete-flag',
            array(
                'snapshot_version' => 12,
                'is_complete' => true,
                'clusters' => array(
                    array('cluster_uuid' => 'cluster-keep', 'identity_count' => 1),
                ),
                'members' => array(
                    array('identity_uuid' => 'id-keep', 'cluster_uuid' => 'cluster-keep'),
                ),
            )
        );

        $this->assertTrue($clustersRepo->mergedIsComplete);
        $this->assertCount(1, $clustersRepo->clusters);
        $this->assertSame('cluster-keep', $clustersRepo->clusters[0]['cluster_uuid']);
    }

    public function testProjectHasMoreFalseIsCompleteAndHasMoreTrueIsNot(): void
    {
        $completeRepo = new SnapshotProjectorClustersSpy();
        $truncatedRepo = new SnapshotProjectorClustersSpy();
        $payload = array(
            'snapshot_version' => 13,
            'clusters' => array(
                array('cluster_uuid' => 'cluster-keep', 'identity_count' => 1),
            ),
            'members' => array(),
        );

        (new SnapshotProjector($completeRepo, new SnapshotProjectorMembersSpy(), new SnapshotProjectorSyncStateSpy()))
            ->project('tenant-has-more', array_merge($payload, array('has_more' => false)));
        (new SnapshotProjector($truncatedRepo, new SnapshotProjectorMembersSpy(), new SnapshotProjectorSyncStateSpy()))
            ->project('tenant-has-more', array_merge($payload, array('has_more' => true)));

        $this->assertTrue($completeRepo->mergedIsComplete);
        $this->assertFalse($truncatedRepo->mergedIsComplete);
    }

    public function testProjectEntitySetTruncatedIsNeverComplete(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $projector = new SnapshotProjector(
            $clustersRepo,
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $projector->project(
            'tenant-truncated-entities',
            array(
                'snapshot_version' => 14,
                'is_complete' => true,
                'entity_set_truncated' => true,
                'clusters' => array(
                    array('cluster_uuid' => 'cluster-keep', 'identity_count' => 1),
                ),
                'members' => array(),
            )
        );

        $this->assertFalse($clustersRepo->mergedIsComplete);
    }

    public function testProjectUndeclaredCompletenessDoesNotTombstone(): void
    {
        $this->seedTombstoneProjection('tenant-undeclared');
        $clustersRepo = new ClustersRepository();
        $projector = new SnapshotProjector(
            $clustersRepo,
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $projector->project(
            'tenant-undeclared',
            array(
                'snapshot_version' => 21,
                'clusters' => array(
                    array(
                        'cluster_uuid' => 'cluster-keep',
                        'label' => 'Keep',
                        'identity_count' => 1,
                    ),
                ),
                'members' => array(),
            )
        );

        $this->assertSame(
            array('cluster-keep', 'cluster-stale-a', 'cluster-stale-b'),
            $this->clusterIdsForTenant('tenant-undeclared')
        );
        $this->assertSame(
            array('id-keep', 'id-stale-a', 'id-stale-b'),
            $this->memberIds()
        );
        $this->assertContains('cluster_not_found:cluster-stale-a', $this->conflictKeys());
        $this->assertContains('cluster_not_found:cluster-stale-b', $this->conflictKeys());
    }

    public function testProjectTruncatedSnapshotDoesNotTombstone(): void
    {
        $this->seedTombstoneProjection('tenant-truncated');
        $clustersRepo = new ClustersRepository();
        $projector = new SnapshotProjector(
            $clustersRepo,
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $projector->project(
            'tenant-truncated',
            array(
                'snapshot_version' => 21,
                'has_more' => true,
                'clusters' => array(
                    array(
                        'cluster_uuid' => 'cluster-keep',
                        'label' => 'Keep',
                        'identity_count' => 1,
                    ),
                ),
                'members' => array(),
            )
        );

        $this->assertSame(
            array('cluster-keep', 'cluster-stale-a', 'cluster-stale-b'),
            $this->clusterIdsForTenant('tenant-truncated')
        );
        $this->assertSame(
            array('id-keep', 'id-stale-a', 'id-stale-b'),
            $this->memberIds()
        );
    }

    public function testProjectCompleteSnapshotTombsOmittedClustersAndMembers(): void
    {
        $this->seedTombstoneProjection('tenant-tombstone');
        $clustersRepo = new ClustersRepository();
        $projector = new SnapshotProjector(
            $clustersRepo,
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $projector->project(
            'tenant-tombstone',
            array(
                'snapshot_version' => 21,
                'is_complete' => true,
                'clusters' => array(
                    array(
                        'cluster_uuid' => 'cluster-keep',
                        'label' => 'Keep',
                        'identity_count' => 1,
                    ),
                ),
                'members' => array(
                    array(
                        'identity_uuid' => 'id-keep',
                        'cluster_uuid' => 'cluster-keep',
                    ),
                ),
            )
        );

        $this->assertSame(array('cluster-keep'), $this->clusterIdsForTenant('tenant-tombstone'));
        $this->assertSame(
            array('cluster-other-tenant'),
            $this->clusterIdsForTenant('other-tenant')
        );
        $this->assertSame(array('id-keep'), $this->memberIds());
        $this->assertContains('version_conflict:cluster-keep', $this->conflictKeys());
        $this->assertNotContains('cluster_not_found:cluster-stale-a', $this->conflictKeys());
        $this->assertNotContains('cluster_not_found:cluster-stale-b', $this->conflictKeys());
    }

    public function testProjectDeltaNeverPassesCompleteness(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $projector = new SnapshotProjector(
            $clustersRepo,
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $projector->project_delta(
            'tenant-delta',
            array(
                'snapshot_version' => 4,
                'is_complete' => true,
                'clusters' => array(
                    array('cluster_uuid' => 'cluster-keep', 'label' => 'Keep'),
                ),
                'members' => array(),
            )
        );

        $this->assertFalse($clustersRepo->mergedIsComplete);
        $this->assertNotSame([], $clustersRepo->mergedClusters);
    }

    public function testProjectBatchedCompleteSnapshotPassesCompletenessToPrepare(): void
    {
        $chunkSize = (new \ReflectionClass(SnapshotProjector::class))->getConstant('MAX_SNAPSHOT_BATCH_SIZE');
        $this->assertIsInt($chunkSize);

        $clustersRepo = new SnapshotProjectorClustersSpy();
        $clusters = [];
        for ($index = 1; $index <= $chunkSize + 1; $index++) {
            $clusters[] = [
                'cluster_uuid' => 'cluster-' . $index,
                'identity_count' => 1,
            ];
        }

        $projector = new SnapshotProjector(
            $clustersRepo,
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );
        $projector->project(
            'tenant-batch-complete',
            array(
                'snapshot_version' => 55,
                'is_complete' => true,
                'clusters' => $clusters,
                'members' => array(),
            )
        );

        $this->assertTrue($clustersRepo->prepareIsComplete);
        $this->assertCount(2, $clustersRepo->mergedClusterBatches);
    }

    /**
     * @return string[]
     */
    private function clusterIdsForTenant(string $tenantId): array
    {
        global $wpdb;

        $ids = array();
        foreach ($wpdb->tableRows['wp_acx_clusters'] ?? array() as $row) {
            if ((string) ($row['tenant_id'] ?? '') !== $tenantId) {
                continue;
            }
            $ids[] = (string) $row['cluster_uuid'];
        }
        sort($ids);

        return $ids;
    }

    /**
     * @return string[]
     */
    private function memberIds(): array
    {
        global $wpdb;

        $ids = array();
        foreach ($wpdb->tableRows['wp_acx_identity_members'] ?? array() as $row) {
            $ids[] = (string) ($row['identity_uuid'] ?? '');
        }
        sort($ids);

        return $ids;
    }

    /**
     * @return string[]
     */
    private function conflictKeys(): array
    {
        global $wpdb;

        $keys = array_map(
            static fn(array $row): string => (string) $row['conflict_code'] . ':' . (string) $row['entity_key'],
            $wpdb->tableRows['wp_acx_sync_conflicts'] ?? array()
        );
        sort($keys);

        return $keys;
    }

    private function seedTombstoneProjection(string $tenant): void
    {
        global $wpdb;

        $wpdb->tableRows['wp_acx_clusters'] = array(
            array(
                'cluster_uuid' => 'cluster-keep',
                'tenant_id' => $tenant,
                'label' => 'Keep',
                'is_user_confirmed' => 0,
            ),
            array(
                'cluster_uuid' => 'cluster-stale-a',
                'tenant_id' => $tenant,
                'label' => 'Stale A',
                'is_user_confirmed' => 0,
            ),
            array(
                'cluster_uuid' => 'cluster-stale-b',
                'tenant_id' => $tenant,
                'label' => 'Operator Name',
                'is_user_confirmed' => 1,
                'person_id' => 9,
            ),
            array(
                'cluster_uuid' => 'cluster-other-tenant',
                'tenant_id' => 'other-tenant',
                'label' => 'Other',
                'is_user_confirmed' => 0,
            ),
        );
        $wpdb->tableRows['wp_acx_identity_members'] = array(
            array(
                'identity_uuid' => 'id-keep',
                'cluster_uuid' => 'cluster-keep',
            ),
            array(
                'identity_uuid' => 'id-stale-a',
                'cluster_uuid' => 'cluster-stale-a',
            ),
            array(
                'identity_uuid' => 'id-stale-b',
                'cluster_uuid' => 'cluster-stale-b',
            ),
        );
        $wpdb->tableRows['wp_acx_sync_conflicts'] = array(
            array(
                'id' => 1,
                'tenant_id' => $tenant,
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-stale-a',
                'conflict_code' => 'cluster_not_found',
                'resolution_status' => 'open',
            ),
            array(
                'id' => 2,
                'tenant_id' => $tenant,
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-keep',
                'conflict_code' => 'version_conflict',
                'resolution_status' => 'open',
            ),
            array(
                'id' => 3,
                'tenant_id' => $tenant,
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-stale-b',
                'conflict_code' => 'cluster_not_found',
                'resolution_status' => 'open',
            ),
        );
    }
}
