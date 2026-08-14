<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClustersReadRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\ClustersReadRepository
 */
class ClustersReadRepositoryTest extends TestCase
{
    private ClustersReadRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new ClustersReadRepository('wp_acx_clusters');
    }

    public function testListForTenantJoinsPersonsTable(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-a',
                'label' => 'Alice',
                'total_count' => 1,
            ],
        ];

        $rows = $this->repository->list_for_tenant(self::currentTenantId(), 10, 0);

        $this->assertCount(1, $rows);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('FROM `wp_acx_clusters` c', $query);
        $this->assertStringContainsString('LEFT JOIN `wp_acx_persons` p', $query);
        $this->assertStringContainsString('p.person_uuid', $query);
        $this->assertStringContainsString('ORDER BY c.updated_at DESC', $query);
    }

    public function testFindByUuidReturnsRow(): void
    {
        global $wpdb;
        $wpdb->mockRow = [
            'cluster_uuid' => 'cluster-find',
            'label' => 'Found',
        ];

        $row = $this->repository->find_by_uuid('cluster-find');

        $this->assertIsArray($row);
        $this->assertSame('cluster-find', $row['cluster_uuid']);
        $this->assertStringContainsString('p.person_uuid', $wpdb->queries[0]);
        $this->assertStringContainsString("WHERE c.cluster_uuid = 'cluster-find'", $wpdb->queries[0]);
    }
}
