<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Tests\TestCase;

/**
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
        $this->assertStringContainsString('projection_version = IF(is_curated = 1, projection_version, VALUES(projection_version))', $insertSql);
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
                ],
            ],
            10
        );

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);

        $this->assertStringContainsString('\\"normalized\\":{\\"x\\":0.1,\\"y\\":0.2,\\"width\\":0.3,\\"height\\":0.4}', $sql);
        $this->assertStringContainsString('0.41', $sql);
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
        $this->assertStringContainsString('COALESCE(p.name, c.label) AS cluster_label', $sql);
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
        $this->assertStringContainsString('COALESCE(p.name, c.label) AS cluster_label', $sql);
    }

    public function testMarkAsCuratedWritesUpdateQuery(): void
    {
        $affectedRows = $this->repository->mark_as_curated('identity-curated');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);

        $this->assertGreaterThanOrEqual(0, $affectedRows);
        $this->assertStringContainsString('UPDATE `wp_acx_identity_members` SET is_curated = 1', $sql);
        $this->assertStringContainsString("'identity-curated'", $sql);
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
