<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\IdentityMembersReadRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\IdentityMembersReadRepository
 */
class IdentityMembersReadRepositoryTest extends TestCase
{
    private IdentityMembersReadRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new IdentityMembersReadRepository('wp_acx_identity_members', 'wp_acx_clusters');
    }

    public function testListForClusterJoinsPersonsTable(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'identity_uuid' => 'id-read',
                'cluster_uuid' => 'cluster-read',
                'total_count' => 2,
            ],
        ];

        $rows = $this->repository->list_for_cluster('cluster-read', 10, 0, self::currentTenantId());

        $this->assertCount(1, $rows);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('LEFT JOIN `wp_acx_persons` p', $sql);
        $this->assertStringContainsString('INNER JOIN `wp_acx_clusters` c', $sql);
    }

    public function testFindByIdentityUuidReturnsRow(): void
    {
        global $wpdb;
        $wpdb->mockRow = [
            'identity_uuid' => 'identity-find-read',
            'cluster_uuid' => 'cluster-find-read',
        ];

        $row = $this->repository->find_by_identity_uuid('identity-find-read');

        $this->assertIsArray($row);
        $this->assertStringContainsString('LIMIT 1', $wpdb->queries[0]);
    }
}
