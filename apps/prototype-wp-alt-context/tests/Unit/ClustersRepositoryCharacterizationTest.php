<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Tests\TestCase;

/**
 * Characterization safety net for repository methods not covered by
 * ClustersRepositoryTest / ClustersRepositoryMutationTest.
 *
 * Collaborator boundary matrix (Slice 1 lock):
 * - ClustersReadRepository: has_projection_rows_for_tenant, get_curated_clusters_for_tenant
 * - ClusterCurationWriter: update_identity_count, update_representative_state, reset_curation
 * - ClusterProjectionWriter: create_local_cluster, upsert_projection_cluster, update_projection_cluster
 * - ClusterSnapshotMerger: merge_snapshot_* (facade characterization via ClustersRepositoryTest)
 * - ClusterDeletionService: delete_cluster_with_members
 *
 * @covers \AltContext\Sovereign\Repositories\ClustersRepository
 */
class ClustersRepositoryCharacterizationTest extends TestCase
{
    private ClustersRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClustersRepository();
    }

    public function testHasProjectionRowsForTenantReturnsTrueWhenRowExists(): void
    {
        global $wpdb;
        $wpdb->mockVar = '1';

        $result = $this->repository->has_projection_rows_for_tenant(self::currentTenantId());

        $this->assertTrue($result);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('SELECT 1 FROM `wp_acx_clusters`', $query);
        $this->assertStringContainsString('tenant_id', $query);
        $this->assertStringContainsString('LIMIT 1', $query);
    }

    public function testHasProjectionRowsForTenantReturnsFalseForEmptyTenantId(): void
    {
        global $wpdb;

        $result = $this->repository->has_projection_rows_for_tenant('   ');

        $this->assertFalse($result);
        $this->assertSame([], $wpdb->queries);
    }

    public function testUpdateIdentityCountBumpsLocalRevision(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->update_identity_count('cluster-abc', 7);

        $this->assertSame(1, $result);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('UPDATE `wp_acx_clusters` SET identity_count = 7', $query);
        $this->assertStringContainsString('local_revision = local_revision + 1', $query);
        $this->assertStringContainsString("WHERE cluster_uuid = 'cluster-abc'", $query);
    }

    public function testAdjustIdentityCountAppliesAtomicRelativeDelta(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->adjust_identity_count('cluster-abc', -2);

        $this->assertSame(1, $result);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        // CON-1: an atomic relative delta so concurrent reassigns into one
        // cluster sum (+2) instead of clobbering each other (+1).
        $this->assertStringContainsString('UPDATE `wp_acx_clusters` SET identity_count = GREATEST(0, identity_count + -2)', $query);
        $this->assertStringContainsString('local_revision = local_revision + 1', $query);
        $this->assertStringContainsString("WHERE cluster_uuid = 'cluster-abc'", $query);
    }

    public function testUpdateRepresentativeStateSetsPinAndRevision(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->update_representative_state('cluster-abc', 'identity-77', true);

        $this->assertSame(1, $result);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('representative_id', $query);
        $this->assertStringContainsString('identity-77', $query);
        $this->assertStringContainsString('is_pinned = 1', $query);
        $this->assertStringContainsString('local_revision = local_revision + 1', $query);
        $this->assertStringContainsString("WHERE cluster_uuid = 'cluster-abc'", $query);
    }

    public function testCreateLocalClusterSetsUserConfirmedAndLocalRevision(): void
    {
        global $wpdb;
        $wpdb->defaultInsertResult = 1;

        $result = $this->repository->create_local_cluster(
            self::currentTenantId(),
            'cluster-new',
            'Curated Label',
            3
        );

        $this->assertSame(1, $result);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('INSERT INTO wp_acx_clusters', $query);
        $this->assertStringContainsString('cluster-new', $query);
        $this->assertStringContainsString('Curated Label', $query);
        $this->assertStringContainsString('is_user_confirmed', $query);
        $this->assertStringContainsString('local_revision', $query);
        $this->assertStringContainsString('snapshot_version', $query);
        $this->assertStringContainsString('curation_state', $query);
    }

    public function testUpsertProjectionClusterUsesOnDuplicateKeyUpdate(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->upsert_projection_cluster(
            self::currentTenantId(),
            'cluster-proj',
            'Projection Label',
            4,
            12,
            '/thumb.jpg',
            'identity-9',
            true
        );

        $this->assertSame(1, $result);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('INSERT INTO `wp_acx_clusters`', $query);
        $this->assertStringContainsString('ON DUPLICATE KEY UPDATE', $query);
        $this->assertStringContainsString('snapshot_version = GREATEST(snapshot_version', $query);
        $this->assertStringContainsString('is_user_confirmed', $query);
        $this->assertStringContainsString('cluster-proj', $query);
    }

    public function testUpdateProjectionClusterWithoutThumbPath(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->update_projection_cluster(
            'cluster-proj',
            5,
            18,
            null,
            'identity-9',
            false
        );

        $this->assertSame(1, $result);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('UPDATE `wp_acx_clusters`', $query);
        $this->assertStringContainsString('identity_count = 5', $query);
        $this->assertStringContainsString('snapshot_version = GREATEST(snapshot_version, 18)', $query);
        $this->assertStringNotContainsString('representative_thumb_path', $query);
        $this->assertStringContainsString("WHERE cluster_uuid = 'cluster-proj'", $query);
    }

    public function testUpdateProjectionClusterWithThumbPath(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->update_projection_cluster(
            'cluster-proj',
            5,
            18,
            '/thumb.jpg',
            'identity-9',
            true
        );

        $this->assertSame(1, $result);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('representative_thumb_path', $query);
        $this->assertStringContainsString('/thumb.jpg', $query);
        $this->assertStringContainsString('is_pinned = 1', $query);
    }

    public function testGetCuratedClustersForTenantIndexesByClusterUuid(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-a',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Alice',
                'is_user_confirmed' => 1,
            ],
            [
                'cluster_uuid' => 'cluster-b',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Bob',
                'is_user_confirmed' => 1,
            ],
        ];

        $result = $this->repository->get_curated_clusters_for_tenant(self::currentTenantId());

        $this->assertCount(2, $result);
        $this->assertArrayHasKey('cluster-a', $result);
        $this->assertArrayHasKey('cluster-b', $result);
        $this->assertSame('Alice', $result['cluster-a']['label']);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('SELECT * FROM `wp_acx_clusters`', $query);
        $this->assertStringContainsString('is_user_confirmed = 1', $query);
    }

    public function testResetCurationClearsLabelAndPerson(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->reset_curation('cluster-reset', self::currentTenantId());

        $this->assertSame(1, $result);
        $joined = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('label = NULL', $joined);
        $this->assertStringContainsString('person_id = NULL', $joined);
        $this->assertStringContainsString("curation_state = 'uncurated'", $joined);
        $this->assertStringContainsString('is_user_confirmed = 0', $joined);
        $this->assertStringContainsString('local_revision = local_revision + 1', $joined);
        $this->assertStringContainsString("cluster_uuid = 'cluster-reset'", $joined);
    }

    public function testDeleteClusterWithMembersDeletesMembersThenCluster(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->repository->delete_cluster_with_members('cluster-del', self::currentTenantId());

        $this->assertSame(1, $result);
        $this->assertCount(2, $wpdb->queries);
        $membersDelete = $wpdb->queries[0];
        $clusterDelete = $wpdb->queries[1];
        $this->assertStringContainsString('DELETE m FROM `wp_acx_identity_members`', $membersDelete);
        $this->assertStringContainsString('INNER JOIN `wp_acx_clusters`', $membersDelete);
        $this->assertStringContainsString("cluster_uuid = 'cluster-del'", $membersDelete);
        $this->assertStringContainsString('DELETE FROM `wp_acx_clusters`', $clusterDelete);
        $this->assertStringContainsString("tenant_id = '" . self::currentTenantId() . "'", $clusterDelete);
    }
}
