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

    /**
     * CON-11/CON-12: members list order must match recognition source-of-truth
     * (assigned_at ASC, identity_uuid). Rows sharing an identical assigned_at
     * must page deterministically — without the PK tie-breaker, LIMIT/OFFSET
     * can overlap or skip rows across pages. Pin both query variants.
     */
    public function testListForClusterOrdersWithIdentityUuidTieBreakerInBothVariants(): void
    {
        global $wpdb;

        $this->repository->list_for_cluster('cluster-page', 2, 0, self::currentTenantId());
        $this->repository->list_for_cluster('cluster-page', 2, 2);

        $this->assertCount(2, $wpdb->queries);
        foreach ($wpdb->queries as $sql) {
            $this->assertStringContainsString('ORDER BY m.assigned_at ASC, m.identity_uuid LIMIT', $sql);
        }
    }

    public function testCountForClusterScopesToTenantWhenProvided(): void
    {
        global $wpdb;
        $wpdb->mockVar = '2';

        $count = $this->repository->count_for_cluster('cluster-count-scoped', self::currentTenantId());

        $this->assertSame(2, $count);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('INNER JOIN `wp_acx_clusters` c ON c.cluster_uuid = m.cluster_uuid', $sql);
        $this->assertStringContainsString('c.tenant_id =', $sql);
        $this->assertStringContainsString("'cluster-count-scoped'", $sql);
    }

    public function testCountForClusterWithoutTenantStaysUnscoped(): void
    {
        global $wpdb;
        $wpdb->mockVar = '3';

        $count = $this->repository->count_for_cluster('cluster-count-open');

        $this->assertSame(3, $count);
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('SELECT COUNT(*) FROM `wp_acx_identity_members`', $sql);
        $this->assertStringNotContainsString('tenant_id', $sql);
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
