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

    public function testListForTenantLabeledOnlyIncludesPersonUuid(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-labeled',
                'label' => 'Labeled',
                'total_count' => 1,
            ],
        ];

        $this->repository->list_for_tenant(self::currentTenantId(), 10, 0, ['labeled_only' => true]);

        $this->assertCount(1, $wpdb->queries);
        $this->assertStringContainsString('p.person_uuid', $wpdb->queries[0]);
        $this->assertStringContainsString("c.label IS NOT NULL AND c.label != ''", $wpdb->queries[0]);
        $this->assertStringNotContainsString('LIKE', $wpdb->queries[0]);
    }

    public function testListForTenantSearchIncludesPersonUuid(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-search',
                'label' => 'Search Hit',
                'total_count' => 1,
            ],
        ];

        $this->repository->list_for_tenant(self::currentTenantId(), 10, 0, ['search' => 'Alice']);

        $this->assertCount(1, $wpdb->queries);
        $this->assertStringContainsString('p.person_uuid', $wpdb->queries[0]);
        $this->assertStringContainsString('c.label LIKE', $wpdb->queries[0]);
    }

    public function testListForTenantLabeledAndSearchIncludesPersonUuid(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-labeled-search',
                'label' => 'Labeled Search',
                'total_count' => 1,
            ],
        ];

        $this->repository->list_for_tenant(
            self::currentTenantId(),
            10,
            0,
            [
                'labeled_only' => true,
                'search' => 'Alice',
            ]
        );

        $this->assertCount(1, $wpdb->queries);
        $this->assertStringContainsString('p.person_uuid', $wpdb->queries[0]);
        $this->assertStringContainsString("c.label IS NOT NULL AND c.label != '' AND c.label LIKE", $wpdb->queries[0]);
    }

    public function testListTopUnlabeledIncludesPersonUuid(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-unlabeled',
                'label' => '',
                'total_count' => 1,
            ],
        ];

        $this->repository->list_top_unlabeled(self::currentTenantId(), 10);

        $this->assertCount(1, $wpdb->queries);
        $this->assertStringContainsString('p.person_uuid', $wpdb->queries[0]);
        $this->assertStringContainsString('c.is_user_confirmed = 0', $wpdb->queries[0]);
    }

    public function testLookupPersonIdsForClustersIsTenantScopedAndJoinsPersons(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'aaaaaaaa-bbbb-cccc-dddd-000000000111',
                'person_id' => 42,
                'name' => 'Ada Lovelace',
            ],
        ];

        $rows = $this->repository->lookup_person_ids_for_clusters(
            self::currentTenantId(),
            ['aaaaaaaa-bbbb-cccc-dddd-000000000111', 'bbbbbbbb-cccc-dddd-eeee-000000000222']
        );

        $this->assertCount(1, $rows);
        $this->assertSame('aaaaaaaa-bbbb-cccc-dddd-000000000111', $rows[0]['cluster_uuid']);
        $this->assertSame(42, $rows[0]['person_id']);
        $this->assertSame('Ada Lovelace', $rows[0]['name']);
        $this->assertCount(1, $wpdb->queries);
        $sql = $wpdb->queries[0];
        $this->assertStringContainsString('FROM `wp_acx_clusters`', $sql);
        $this->assertStringContainsString('LEFT JOIN `wp_acx_persons`', $sql);
        $this->assertStringContainsString('cluster_uuid', $sql);
        $this->assertStringContainsString('person_id', $sql);
        $this->assertStringContainsString('tenant_id', $sql);
        $this->assertStringContainsString("'" . self::currentTenantId() . "'", $sql);
        $this->assertStringContainsString("'aaaaaaaa-bbbb-cccc-dddd-000000000111'", $sql);
        $this->assertStringContainsString("'bbbbbbbb-cccc-dddd-eeee-000000000222'", $sql);
    }
}
