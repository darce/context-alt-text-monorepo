<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

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
        $this->assertStringContainsString('DELETE FROM `wp_acx_clusters`', $mergedSql);
        $this->assertStringContainsString('is_user_confirmed = 0', $mergedSql);
        $this->assertStringContainsString('cluster_uuid NOT IN', $mergedSql);
        $this->assertStringNotContainsString('FIND_IN_SET(cluster_uuid', $mergedSql);

        $this->assertStringContainsString('INSERT INTO `wp_acx_clusters`', $mergedSql);
        $this->assertStringContainsString('label = IF(is_user_confirmed = 1, label, VALUES(label))', $mergedSql);
        $this->assertStringContainsString('curation_state = IF(is_user_confirmed = 1, curation_state, VALUES(curation_state))', $mergedSql);
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
        $this->assertStringContainsString("label IS NOT NULL", $sql);
        $this->assertStringContainsString("label LIKE", $sql);
    }

    public function testListLabelsReturnsDistinctLabels(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            ['label' => 'Alice'],
            ['label' => 'Bob'],
        ];

        $labels = $this->repository->list_labels('tenant-labels');

        $this->assertSame(['Alice', 'Bob'], $labels);
    }

    public function testListTopUnlabeledQueriesByIdentityCount(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $this->repository->list_top_unlabeled('tenant-top', 7);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString("identity_count DESC", $sql);
        $this->assertStringContainsString("label IS NULL", $sql);
        $this->assertStringContainsString("curation_state <> 'dismissed'", $sql);
    }

    public function testFindByUuidReturnsNullWhenRowMissing(): void
    {
        global $wpdb;
        $wpdb->mockRow = null;

        $row = $this->repository->find_by_uuid('cluster-missing');

        $this->assertNull($row);
    }
}
