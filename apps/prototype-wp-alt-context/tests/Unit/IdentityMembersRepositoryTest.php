<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Tests\TestCase;

/**
 * Characterization safety net for identity-members repository methods.
 *
 * Collaborator boundary matrix (Slice 1 lock):
 * - IdentityMembersReadRepository: list_for_cluster*, has_projection_rows_for_tenant,
 *   count_for_cluster, find_by_identity_uuid, get_curated_members_for_tenant
 * - IdentityMemberCurationWriter: mark_as_curated, reassign_to_cluster,
 *   reassign_cluster_members, reset_curation, accept_machine_cluster_assignment
 * - IdentityMemberSnapshotMerger: merge_snapshot_for_tenant, assign_to_cluster_for_projection,
 *   delete_stale_non_curated_rows, delete_orphan_rows
 * - IdentityMemberDeletionService: delete_member (YAGNI — deletes owned by merger per matrix)
 * - MemberConflictRecorder: is_member_cluster_conflict,
 *   record_member_cluster_reassignment_conflict, record_missing_curated_member_conflicts
 * - MemberRowNormalizer: 7 normalize/sanitize privates shared across read + write paths
 *
 * Deferred perf (debt #11, unchanged): merge per-member loop + delete_orphan_rows LEFT JOIN.
 *
 * @covers \AltContext\Sovereign\Repositories\IdentityMembersRepository
 */
class IdentityMembersRepositoryTest extends TestCase
{
    private IdentityMembersRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new IdentityMembersRepository();
    }

    public function testMergeSnapshotForTenantWritesCurationAwareQueriesAndBboxContract(): void
    {
        $this->repository->merge_snapshot_for_tenant(
            'tenant-members',
            [
                [
                    'identity_uuid' => 'identity-1',
                    'cluster_uuid' => 'cluster-1',
                    'attachment_id' => 123,
                    'bbox' => [
                        'x' => 120,
                        'y' => 45,
                        'width' => 80,
                        'height' => 92,
                    ],
                    'image_width' => 640,
                    'image_height' => 480,
                    'similarity' => 0.88,
                ],
            ],
            9
        );

        global $wpdb;
        $queries = $wpdb->queries;
        $sql = implode("\n", $queries);

        $this->assertStringContainsString('DELETE m FROM `wp_acx_identity_members` m', $sql);
        $this->assertStringContainsString('INNER JOIN `wp_acx_clusters` c ON c.cluster_uuid = m.cluster_uuid', $sql);
        $this->assertStringContainsString('c.is_user_confirmed = 0', $sql);
        $this->assertStringContainsString('m.identity_uuid NOT IN', $sql);
        $this->assertStringNotContainsString('FIND_IN_SET(m.identity_uuid', $sql);
        $this->assertStringContainsString('LEFT JOIN `wp_acx_clusters` c ON c.cluster_uuid = m.cluster_uuid', $sql);
        $this->assertStringContainsString('WHERE c.cluster_uuid IS NULL', $sql);
        $this->assertStringContainsString('INSERT INTO `wp_acx_identity_members`', $sql);
        $insertSql = $this->findQueryContaining($queries, 'INSERT INTO `wp_acx_identity_members`');
        $this->assertStringContainsString('WHERE EXISTS (', $insertSql);
        $this->assertStringNotContainsString('AND c.is_user_confirmed = 0', $insertSql);
        $this->assertStringContainsString('is_curated', $insertSql);
        $this->assertStringContainsString('projection_version', $insertSql);
        $this->assertStringContainsString('cluster_uuid = IF(is_curated = 1, cluster_uuid, VALUES(cluster_uuid))', $insertSql);
        // COR-1: projection_version is monotonic (GREATEST) for non-curated members.
        $this->assertStringContainsString('projection_version = IF(is_curated = 1, projection_version, GREATEST(projection_version, VALUES(projection_version)))', $insertSql);
        $this->assertStringContainsString('acx://identity/identity-1/attachment/123', $sql);
        $this->assertStringContainsString('\\"coordinate_space\\":\\"original_image\\"', $sql);
        $this->assertStringContainsString('\\"normalized\\":{\\"x\\":0.1875', $sql);
    }

    /**
     * @dataProvider memberMergeGuardProvider
     * @param list<array<string,mixed>> $members
     */
    public function testMemberMergeGuardScenarios(string $tenantId, array $members, int $snapshotVersion, string $expectedSqlFragment): void
    {
        $this->repository->merge_snapshot_for_tenant($tenantId, $members, $snapshotVersion);

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);

        $this->assertStringContainsString($expectedSqlFragment, $sql);
    }

    public function testMergeSnapshotUsesProvidedNormalizedBboxWhenPresent(): void
    {
        $this->repository->merge_snapshot_for_tenant(
            'tenant-bbox',
            [
                [
                    'identity_uuid' => 'identity-2',
                    'cluster_uuid' => 'cluster-2',
                    'media_id' => 777,
                    'bbox' => [
                        'pixels' => [
                            'x' => 20,
                            'y' => 30,
                            'width' => 40,
                            'height' => 50,
                        ],
                        'normalized' => [
                            'x' => 0.1,
                            'y' => 0.2,
                            'width' => 0.3,
                            'height' => 0.4,
                        ],
                    ],
                    'match_similarity' => 0.41,
                    'similarity_threshold' => 0.85,
                ],
            ],
            10
        );

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);

        $this->assertStringContainsString('\\"normalized\\":{\\"x\\":0.1,\\"y\\":0.2,\\"width\\":0.3,\\"height\\":0.4}', $sql);
        $this->assertStringContainsString('0.41', $sql);
        $this->assertStringContainsString('0.85', $sql);
        $this->assertStringContainsString('similarity_threshold', $sql);
    }

    public function testMergeSnapshotStoresDatabaseNullSimilarityWhenMissing(): void
    {
        $this->repository->merge_snapshot_for_tenant(
            'tenant-null-similarity',
            [
                [
                    'identity_uuid' => 'identity-3',
                    'cluster_uuid' => 'cluster-3',
                    'attachment_id' => 12,
                    'bbox' => [
                        'x' => 1,
                        'y' => 2,
                        'width' => 3,
                        'height' => 4,
                    ],
                ],
            ],
            11
        );

        global $wpdb;
        $insertSql = $this->findQueryContaining($wpdb->queries, 'INSERT INTO `wp_acx_identity_members`');

        $this->assertStringContainsString("NULLIF('', '')", $insertSql);
        $this->assertStringNotContainsString("NULLIF('NULL', '')", $insertSql);
    }

    public function testListForClusterReturnsRowsFromDatabaseLayer(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'identity_uuid' => 'id-list',
                'cluster_uuid' => 'cluster-list',
                'attachment_id' => 33,
                'total_count' => 501,
            ],
        ];

        $rows = $this->repository->list_for_cluster('cluster-list');

        $this->assertCount(1, $rows);
        $this->assertSame('id-list', $rows[0]['identity_uuid']);
        $this->assertSame(501, $rows[0]['total_count']);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('COUNT(*) OVER() AS total_count', $sql);
        $this->assertStringContainsString('LEFT JOIN `wp_acx_persons` p', $sql);
        $this->assertStringNotContainsString('COALESCE(p.name, c.label) AS cluster_label', $sql);
        $this->assertStringContainsString('THEN p.name', $sql);
    }

    public function testListForMediaIdsScopesByTenantAndMediaIds(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'identity_uuid' => 'id-1',
                'cluster_uuid' => 'cluster-1',
                'attachment_id' => 55,
                'cluster_label' => 'Label',
            ],
        ];

        $rows = $this->repository->list_for_media_ids('tenant-media', [55, 56]);

        $this->assertCount(1, $rows);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('attachment_id IN (55, 56)', $sql);
        $this->assertStringContainsString('tenant-media', $sql);
        $this->assertStringContainsString('LEFT JOIN `wp_acx_persons` p', $sql);
        $this->assertStringNotContainsString('COALESCE(p.name, c.label) AS cluster_label', $sql);
        $this->assertStringContainsString('WHEN p.name IS NOT NULL AND p.name <> \'\' THEN p.name', $sql);
        $this->assertStringContainsString("c.label LIKE 'cluster-%%'", $sql);
        $this->assertStringContainsString("c.label LIKE 'cluster\\_%%'", $sql);
        $this->assertStringContainsString('ELSE NULL', $sql);
    }

    public function testListForMediaIdsDoesNotFallBackToRawHumanLabel(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'identity_uuid' => 'id-human',
                'cluster_uuid' => 'cluster-human',
                'attachment_id' => 6731,
                'cluster_label' => null,
            ],
        ];

        $this->repository->list_for_media_ids('tenant-media', [6731]);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringNotContainsString('COALESCE(p.name, c.label)', $sql);
        $this->assertStringContainsString('THEN p.name', $sql);
        $this->assertStringContainsString("c.label LIKE 'cluster-%%' OR c.label LIKE 'cluster\\_%%'", $sql);
    }

    public function testGetCuratedMembersForTenantIndexesRowsByIdentityUuid(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'identity_uuid' => 'identity-9',
                'cluster_uuid' => 'cluster-9',
                'is_curated' => 1,
            ],
        ];

        $rows = $this->repository->get_curated_members_for_tenant('tenant-curated');

        $this->assertArrayHasKey('identity-9', $rows);
        $this->assertSame('cluster-9', $rows['identity-9']['cluster_uuid']);
        $this->assertStringContainsString('m.is_curated = 1', implode("\n", $wpdb->queries));
    }

    public function testDeleteOrphanRowsPreservesCuratedMembers(): void
    {
        $this->repository->merge_snapshot_for_tenant('tenant-curated-orphans', [], 16);

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);

        $this->assertStringContainsString('WHERE c.cluster_uuid IS NULL', $sql);
        $this->assertStringContainsString('AND m.is_curated = 0', $sql);
    }

    public function testCuratedMemberReassignmentRecordsConflictAndSkipsOverwrite(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'identity_uuid' => 'identity-curated',
                'cluster_uuid' => 'cluster-local',
                'projection_version' => 22,
                'is_curated' => 1,
            ],
        ];

        $this->repository->merge_snapshot_for_tenant(
            'tenant-conflict',
            [
                [
                    'identity_uuid' => 'identity-curated',
                    'cluster_uuid' => 'cluster-remote',
                    'attachment_id' => 90,
                    'similarity' => 0.75,
                ],
            ],
            23
        );

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('INSERT INTO `wp_acx_sync_conflicts`', $sql);
        $this->assertStringContainsString("'member_cluster_reassignment'", $sql);
        $this->assertStringNotContainsString("SELECT 'identity-curated', 'cluster-remote', 90", $sql);
    }

    public function testMergeSnapshotPerMemberLoopIssuesOneInsertPerMember(): void
    {
        $this->repository->merge_snapshot_for_tenant(
            'tenant-n-plus-one',
            [
                [
                    'identity_uuid' => 'identity-loop-1',
                    'cluster_uuid' => 'cluster-loop',
                    'attachment_id' => 1,
                ],
                [
                    'identity_uuid' => 'identity-loop-2',
                    'cluster_uuid' => 'cluster-loop',
                    'attachment_id' => 2,
                ],
            ],
            12
        );

        global $wpdb;
        $insertCount = 0;
        foreach ($wpdb->queries as $query) {
            if (str_contains($query, 'INSERT INTO `wp_acx_identity_members`')) {
                ++$insertCount;
            }
        }

        $this->assertSame(2, $insertCount, 'merge_snapshot_for_tenant issues one INSERT per member (deferred perf debt #11)');
    }

    public function testDeleteOrphanRowsUsesLeftJoinScan(): void
    {
        $this->repository->merge_snapshot_for_tenant('tenant-orphan-scan', [], 13);

        global $wpdb;
        $orphanDelete = $this->findQueryContaining($wpdb->queries, 'WHERE c.cluster_uuid IS NULL');

        $this->assertStringContainsString('LEFT JOIN `wp_acx_clusters` c ON c.cluster_uuid = m.cluster_uuid', $orphanDelete);
        $this->assertStringContainsString('AND m.is_curated = 0', $orphanDelete);
    }

    public function testListForClusterUuidsGroupsRowsByClusterAndUsesWindowLimit(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'identity_uuid' => 'id-a',
                'cluster_uuid' => 'cluster-a',
                'attachment_id' => 10,
                'rn' => 1,
            ],
            [
                'identity_uuid' => 'id-b',
                'cluster_uuid' => 'cluster-b',
                'attachment_id' => 11,
                'rn' => 1,
            ],
        ];

        $rows = $this->repository->list_for_cluster_uuids(['cluster-a', 'cluster-b'], 5);

        $this->assertArrayHasKey('cluster-a', $rows);
        $this->assertArrayHasKey('cluster-b', $rows);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('ROW_NUMBER() OVER (PARTITION BY m.cluster_uuid', $sql);
        $this->assertStringContainsString("'cluster-a', 'cluster-b'", $sql);
    }

    public function testHasProjectionRowsForTenantUsesExistsProbe(): void
    {
        global $wpdb;
        $wpdb->mockVar = '1';

        $this->assertTrue($this->repository->has_projection_rows_for_tenant('tenant-probe'));

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('SELECT 1', $sql);
        $this->assertStringContainsString('tenant-probe', $sql);
        $this->assertStringContainsString('INNER JOIN `wp_acx_clusters` c ON c.cluster_uuid = m.cluster_uuid', $sql);
    }

    public function testReassignToClusterMarksCuratedAndUpdatesCluster(): void
    {
        $this->repository->reassign_to_cluster('identity-reassign', 'cluster-target');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('UPDATE `wp_acx_identity_members` SET cluster_uuid', $sql);
        $this->assertStringContainsString('is_curated = 1', $sql);
        $this->assertStringContainsString("'identity-reassign'", $sql);
        $this->assertStringContainsString("'cluster-target'", $sql);
    }

    public function testAssignToClusterForProjectionUsesGreatestProjectionVersion(): void
    {
        $this->repository->assign_to_cluster_for_projection('identity-proj', 'cluster-proj', 42);

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('projection_version = GREATEST(projection_version, 42)', $sql);
        $this->assertStringContainsString("'cluster-proj'", $sql);
    }

    public function testReassignClusterMembersBulkUpdatesSourceCluster(): void
    {
        $this->repository->reassign_cluster_members('cluster-source', 'cluster-target');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('UPDATE `wp_acx_identity_members` SET cluster_uuid', $sql);
        $this->assertStringContainsString('WHERE cluster_uuid', $sql);
        $this->assertStringContainsString("'cluster-source'", $sql);
        $this->assertStringContainsString("'cluster-target'", $sql);
    }

    public function testCountForClusterReturnsAggregate(): void
    {
        global $wpdb;
        $wpdb->mockVar = '3';

        $count = $this->repository->count_for_cluster('cluster-count');

        $this->assertSame(3, $count);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('SELECT COUNT(*) FROM `wp_acx_identity_members`', $sql);
        $this->assertStringContainsString("'cluster-count'", $sql);
    }

    public function testFindByIdentityUuidReturnsSingleRow(): void
    {
        global $wpdb;
        $wpdb->mockRow = [
            'identity_uuid' => 'identity-find',
            'cluster_uuid' => 'cluster-find',
        ];

        $row = $this->repository->find_by_identity_uuid('identity-find');

        $this->assertIsArray($row);
        $this->assertSame('identity-find', $row['identity_uuid']);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('WHERE identity_uuid', $sql);
        $this->assertStringContainsString('LIMIT 1', $sql);
    }

    public function testResetCurationClearsFlagWithinTenant(): void
    {
        $this->repository->reset_curation('identity-reset', 'tenant-reset');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('SET m.is_curated = 0', $sql);
        $this->assertStringContainsString("'identity-reset'", $sql);
        $this->assertStringContainsString("'tenant-reset'", $sql);
    }

    public function testDeleteMemberRemovesTenantScopedRow(): void
    {
        $this->repository->delete_member('identity-delete', 'tenant-delete');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('DELETE m FROM `wp_acx_identity_members` m', $sql);
        $this->assertStringContainsString("'identity-delete'", $sql);
        $this->assertStringContainsString("'tenant-delete'", $sql);
    }

    public function testAcceptMachineClusterAssignmentClearsCuration(): void
    {
        $this->repository->accept_machine_cluster_assignment('identity-accept', 'cluster-accept', 'tenant-accept');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('SET m.cluster_uuid', $sql);
        $this->assertStringContainsString('m.is_curated = 0', $sql);
        $this->assertStringContainsString("'identity-accept'", $sql);
        $this->assertStringContainsString("'cluster-accept'", $sql);
        $this->assertStringContainsString("'tenant-accept'", $sql);
    }

    public function testMissingCuratedMemberRecordsConflictBeforeCleanup(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'identity_uuid' => 'identity-curated',
                'cluster_uuid' => 'cluster-local',
                'projection_version' => 24,
                'is_curated' => 1,
            ],
        ];

        $this->repository->merge_snapshot_for_tenant('tenant-missing-curated', [], 25);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('INSERT INTO `wp_acx_sync_conflicts`', $sql);
        $this->assertStringContainsString("'curated_member_deleted'", $sql);
    }

    /**
     * @return array<string,array{0:string,1:list<array<string,mixed>>,2:int,3:string}>
     */
    public static function memberMergeGuardProvider(): array
    {
        return [
            'curated member survives stale cleanup and move overwrite is guarded' => [
                'tenant-curated-survives',
                [
                    [
                        'identity_uuid' => 'identity-curated',
                        'cluster_uuid' => 'cluster-new',
                        'attachment_id' => 77,
                    ],
                ],
                14,
                'AND m.is_curated = 0',
            ],
            'uncurated member updates still use VALUES(cluster_uuid)' => [
                'tenant-uncurated-overwrite',
                [
                    [
                        'identity_uuid' => 'identity-uncurated',
                        'cluster_uuid' => 'cluster-machine',
                        'attachment_id' => 88,
                    ],
                ],
                15,
                'cluster_uuid = IF(is_curated = 1, cluster_uuid, VALUES(cluster_uuid))',
            ],
        ];
    }

    /**
     * @param array<int,string> $queries
     */
    private function findQueryContaining(array $queries, string $needle): string
    {
        foreach ($queries as $query) {
            if (str_contains($query, $needle)) {
                return $query;
            }
        }

        $this->fail(sprintf('Unable to find query containing "%s".', $needle));
    }
}
