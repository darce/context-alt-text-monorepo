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
        $this->assertStringContainsString('acx://identity/identity-1/attachment/123', $sql);
        $this->assertStringContainsString('\\"coordinate_space\\":\\"original_image\\"', $sql);
        $this->assertStringContainsString('\\"normalized\\":{\\"x\\":0.1875', $sql);
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
            ],
        ];

        $rows = $this->repository->list_for_cluster('cluster-list');

        $this->assertCount(1, $rows);
        $this->assertSame('id-list', $rows[0]['identity_uuid']);
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
        return '';
    }
}
