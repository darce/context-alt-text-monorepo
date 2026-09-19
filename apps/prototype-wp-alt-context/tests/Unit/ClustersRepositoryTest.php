<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClusterSnapshotMerger;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\ClustersRepository
 */
class ClustersRepositoryTest extends TestCase
{
    private ClustersRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClustersRepository();
    }

    public function testMergeSnapshotForTenantUsesCurationSafeDeleteAndGuardedUpsert(): void
    {
        $this->repository->merge_snapshot_for_tenant(
            'tenant-a',
            [
                [
                    'cluster_uuid' => 'cluster-1',
                    'label' => 'Daniel',
                    'curation_state' => 'confirmed',
                    'is_user_confirmed' => true,
                    'identity_count' => 4,
                    'representative_media_id' => 1001,
                    'representative_id' => 'identity-1',
                    'is_pinned' => true,
                ],
                [
                    'cluster_uuid' => 'cluster-2',
                    'label' => 'Mina',
                    'curation_state' => 'uncurated',
                    'is_user_confirmed' => false,
                    'identity_count' => 2,
                ],
            ],
            14
        );

        global $wpdb;
        $queries = $wpdb->queries;
        $this->assertNotEmpty($queries);

        $mergedSql = implode("\n", $queries);
        $this->assertStringNotContainsString('DELETE FROM `wp_acx_clusters`', $mergedSql);
        $this->assertStringNotContainsString('cluster_uuid NOT IN', $mergedSql);

        $this->assertStringContainsString('INSERT INTO `wp_acx_clusters`', $mergedSql);
        $this->assertStringContainsString('label = IF(is_user_confirmed = 1, label, VALUES(label))', $mergedSql);
        $this->assertStringContainsString('curation_state = IF(is_user_confirmed = 1, curation_state, VALUES(curation_state))', $mergedSql);
        $this->assertStringContainsString('person_id = IF(is_user_confirmed = 1, person_id, person_id)', $mergedSql);
        $this->assertStringContainsString('local_revision = IF(is_user_confirmed = 1, local_revision, local_revision)', $mergedSql);
        // COR-1: overwritten data columns are version-gated so a stale snapshot cannot regress them.
        $this->assertStringContainsString('representative_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_id), representative_id)', $mergedSql);
        $this->assertStringContainsString('is_pinned = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(is_pinned), is_pinned)', $mergedSql);
        $this->assertStringContainsString('snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version))', $mergedSql);
    }

    public function testMergeSnapshotDerivesDeterministicRepresentativeThumbKey(): void
    {
        $this->repository->merge_snapshot_for_tenant(
            'tenant-thumb',
            [
                [
                    'cluster_uuid' => 'cluster-thumb',
                    'label' => 'Label',
                    'representative_media_id' => 501,
                ],
            ],
            2
        );

        global $wpdb;
        $mergedSql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('acx://cluster/cluster-thumb/media/501', $mergedSql);
    }

    public function testUndeclaredMergeDoesNotTombstoneAbsentClusters(): void
    {
        $this->seedTombstoneProjection('tenant-empty-clusters');

        $this->repository->merge_snapshot_for_tenant('tenant-empty-clusters', [], 5);

        global $wpdb;
        $mergedSql = implode("\n", $wpdb->queries);

        $this->assertStringNotContainsString('DELETE FROM wp_acx_clusters', $mergedSql);
        $this->assertSame(
            array('cluster-keep', 'cluster-stale-a', 'cluster-stale-b'),
            $this->clusterIdsForTenant('tenant-empty-clusters')
        );
        $this->assertCount(3, $wpdb->tableRows['wp_acx_identity_members']);
    }

    public function testCompleteMergeTombsOmittedClustersAndMembers(): void
    {
        $this->seedTombstoneProjection('tenant-tombstone');

        $this->repository->merge_snapshot_for_tenant(
            'tenant-tombstone',
            array(
                array(
                    'cluster_uuid' => 'cluster-keep',
                    'label' => 'Keep',
                    'identity_count' => 1,
                ),
            ),
            21,
            true
        );

        global $wpdb;
        // cluster-stale-b is operator-confirmed and person-bound: snapshot absence must not delete it (1075a021).
        $this->assertSame(array('cluster-keep', 'cluster-stale-b'), $this->clusterIdsForTenant('tenant-tombstone'));
        $this->assertSame(
            array('cluster-other-tenant'),
            $this->clusterIdsForTenant('other-tenant')
        );
        $this->assertSame(
            array('id-keep', 'id-stale-b'),
            array_values(
                array_map(
                    static fn(array $row): string => (string) $row['identity_uuid'],
                    $wpdb->tableRows['wp_acx_identity_members']
                )
            )
        );
        $this->assertSame(
            array('cluster_not_found:cluster-stale-b', 'version_conflict:cluster-keep'),
            $this->conflictKeys()
        );
    }

    public function testMergeSnapshotForTenantChunksLargePayloadsIntoBoundedBatches(): void
    {
        $merger = new class('wp_acx_clusters') extends ClusterSnapshotMerger {
            public array $preparedCalls = [];
            public array $batchCalls = [];

            public function prepare_snapshot_merge_for_tenant(string $tenant_id, array $incoming_cluster_ids, bool $is_complete = false): array
            {
                $this->preparedCalls[] = [
                    'tenant_id' => $tenant_id,
                    'incoming_cluster_ids' => $incoming_cluster_ids,
                    'is_complete' => $is_complete,
                ];

                return array(
                    'tombstoned_clusters' => 0,
                    'tombstoned_members' => 0,
                    'preserved_curated' => 0,
                );
            }

            public function merge_snapshot_batch_for_tenant(string $tenant_id, array $clusters, int $snapshot_version): void
            {
                $this->batchCalls[] = [
                    'tenant_id' => $tenant_id,
                    'clusters' => $clusters,
                    'snapshot_version' => $snapshot_version,
                ];
            }
        };

        $repository = new ClustersRepository(
            'wp_acx_clusters',
            null,
            null,
            null,
            $merger
        );

        $clusters = [];
        for ($index = 1; $index <= 501; $index++) {
            $clusters[] = [
                'cluster_uuid' => sprintf('cluster-%03d', $index),
                'identity_count' => 1,
            ];
        }

        $repository->merge_snapshot_for_tenant('tenant-batched', $clusters, 8);

        $this->assertCount(1, $merger->preparedCalls);
        $this->assertSame('tenant-batched', $merger->preparedCalls[0]['tenant_id']);
        $this->assertCount(501, $merger->preparedCalls[0]['incoming_cluster_ids']);
        $this->assertFalse($merger->preparedCalls[0]['is_complete']);
        $this->assertCount(2, $merger->batchCalls);
        $this->assertCount(500, $merger->batchCalls[0]['clusters']);
        $this->assertCount(1, $merger->batchCalls[1]['clusters']);
        $this->assertSame(8, $merger->batchCalls[0]['snapshot_version']);
        $this->assertSame(8, $merger->batchCalls[1]['snapshot_version']);
    }

    public function testListForTenantReturnsRowsFromDatabaseLayer(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-list',
                'tenant_id' => 'tenant-list',
                'label' => 'Listed',
            ],
        ];

        $rows = $this->repository->list_for_tenant('tenant-list', 10, 0);

        $this->assertCount(1, $rows);
        $this->assertSame('cluster-list', $rows[0]['cluster_uuid']);
    }

    public function testListForTenantAddsSearchAndLabelFilters(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $this->repository->list_for_tenant('tenant-search', 25, 5, [
            'search' => 'Alice',
            'labeled_only' => true,
        ]);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('THEN p.name', $sql);
        $this->assertStringContainsString("label LIKE", $sql);
    }

    public function testListLabelsReturnsBoundedRowsWithTotalCountMetadata(): void
    {
        global $wpdb;
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'c-a',
                'tenant_id' => 'tenant-labels',
                'label' => 'Alice',
                'person_id' => 1,
            ],
            [
                'cluster_uuid' => 'c-b',
                'tenant_id' => 'tenant-labels',
                'label' => 'Bob',
                'person_id' => 2,
            ],
        ];

        $labels = $this->repository->list_labels('tenant-labels', '', 25);

        $this->assertSame(
            [
                ['label' => 'Alice', 'total_count' => 2],
                ['label' => 'Bob', 'total_count' => 2],
            ],
            $labels
        );
    }

    public function testListLabelsAddsSearchAndLimitFilters(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $this->repository->list_labels('tenant-search', 'Alice', 25);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString("label IS NOT NULL", $sql);
        $this->assertStringContainsString("label LIKE", $sql);
        $this->assertStringContainsString("LIMIT 25", $sql);
    }

    public function testListTopUnlabeledQueriesByIdentityCount(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $this->repository->list_top_unlabeled('tenant-top', 7);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('`wp_acx_identity_members`', $sql);
        $this->assertStringContainsString(') DESC', $sql);
        $this->assertStringContainsString("c.is_user_confirmed = 0", $sql);
        $this->assertStringNotContainsString("c.identity_count >= 2", $sql);
        $this->assertStringContainsString(') >= 2', $sql);
        $this->assertStringContainsString("label IS NULL", $sql);
        $this->assertStringContainsString("curation_state <> 'dismissed'", $sql);
    }

    public function testListTopUnlabeledTreatsAutoGeneratedClusterLabelsAsUnlabeled(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $this->repository->list_top_unlabeled('tenant-auto-labels', 5);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString("LOWER(c.label) LIKE 'cluster-%%'", $sql);
    }

    public function testCountTopUnlabeledSingletonsUsesSingletonPredicate(): void
    {
        global $wpdb;
        $wpdb->mockVar = 4;

        $count = $this->repository->count_top_unlabeled_singletons('tenant-singletons');

        $this->assertSame(4, $count);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('COUNT(*)', $sql);
        $this->assertStringContainsString('`wp_acx_identity_members`', $sql);
        $this->assertStringContainsString(') <= 1', $sql);
        $this->assertStringNotContainsString('c.identity_count <= 1', $sql);
    }

    public function testFindByUuidReturnsNullWhenRowMissing(): void
    {
        global $wpdb;
        $wpdb->mockRow = null;

        $row = $this->repository->find_by_uuid('cluster-missing');

        $this->assertNull($row);
    }

    public function testListForTenantUsesLeftJoinForLabelDerivation(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $this->repository->list_for_tenant('tenant-join', 10, 0);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('LEFT JOIN `wp_acx_persons` p', $sql);
        $this->assertStringContainsString('THEN p.name', $sql);
        $this->assertStringContainsString("LOWER(c.label) LIKE 'cluster-%%'", $sql);
        $this->assertStringNotContainsString('COALESCE(p.name, c.label)', $sql);
    }

    public function testMergeSnapshotWritesSuggestedLabelColumns(): void
    {
        $this->repository->merge_snapshot_for_tenant(
            'tenant-sugg',
            [
                [
                    'cluster_uuid' => 'cluster-sugg',
                    'label' => null,
                    'curation_state' => 'active',
                    'is_user_confirmed' => false,
                    'identity_count' => 3,
                    'suggested_label' => 'Alice',
                    'suggested_label_source' => 'similar_cluster',
                    'suggested_label_confidence' => 0.92,
                    'suggested_target_cluster_id' => 'cluster-target',
                ],
            ],
            7
        );

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('suggested_label', $sql);
        $this->assertStringContainsString("'Alice'", $sql);
        $this->assertStringContainsString("'similar_cluster'", $sql);
        $this->assertStringContainsString('0.92', $sql);
        $this->assertStringContainsString('cluster-target', $sql);
        $this->assertStringContainsString('NULLIF', $sql);
        $this->assertStringContainsString('suggested_label = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_label), suggested_label)', $sql);
        $this->assertStringContainsString('suggested_label_source = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_label_source), suggested_label_source)', $sql);
        $this->assertStringContainsString('suggested_label_confidence = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_label_confidence), suggested_label_confidence)', $sql);
        $this->assertStringContainsString('suggested_target_cluster_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_target_cluster_id), suggested_target_cluster_id)', $sql);
    }

    public function testMergeSnapshotUsesNullIfForAbsentSuggestedLabel(): void
    {
        $this->repository->merge_snapshot_for_tenant(
            'tenant-nullsugg',
            [
                [
                    'cluster_uuid' => 'cluster-nosugg',
                    'label' => null,
                    'curation_state' => 'active',
                    'is_user_confirmed' => false,
                    'identity_count' => 1,
                ],
            ],
            2
        );

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        // Absent suggested_label fields must use NULLIF(%s, '') so MySQL stores NULL, not ''
        $this->assertStringContainsString('NULLIF', $sql);
        $this->assertStringContainsString('suggested_label', $sql);
        $this->assertStringContainsString('suggested_label = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_label), suggested_label)', $sql);
    }

    public function testMergeSnapshotForwardsCompletenessToMerger(): void
    {
        $merger = new class('wp_acx_clusters') extends ClusterSnapshotMerger {
            public array $mergeCalls = [];

            public function merge_snapshot_for_tenant(string $tenant_id, array $clusters, int $snapshot_version, bool $is_complete = false): array
            {
                $this->mergeCalls[] = [
                    'tenant_id' => $tenant_id,
                    'clusters' => $clusters,
                    'snapshot_version' => $snapshot_version,
                    'is_complete' => $is_complete,
                ];

                return array(
                    'tombstoned_clusters' => 0,
                    'tombstoned_members' => 0,
                    'preserved_curated' => 0,
                );
            }
        };

        $repository = new ClustersRepository(
            'wp_acx_clusters',
            null,
            null,
            null,
            $merger
        );

        $clusters = array(
            array(
                'cluster_uuid' => 'cluster-keep',
                'identity_count' => 1,
            ),
        );
        $repository->merge_snapshot_for_tenant('tenant-forward', $clusters, 9, true);

        $this->assertCount(1, $merger->mergeCalls);
        $this->assertSame('tenant-forward', $merger->mergeCalls[0]['tenant_id']);
        $this->assertSame($clusters, $merger->mergeCalls[0]['clusters']);
        $this->assertSame(9, $merger->mergeCalls[0]['snapshot_version']);
        $this->assertTrue($merger->mergeCalls[0]['is_complete']);
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
