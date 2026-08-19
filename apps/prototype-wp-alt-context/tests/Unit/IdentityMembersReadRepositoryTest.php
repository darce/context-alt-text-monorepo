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
     * rg-005: members list order must match recognition source-of-truth
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

    /**
     * S4-05 / rg-005: the show-all preview window must rank members by the SAME
     * key as the detail path (assigned_at ASC, identity_uuid) so the top-N card
     * preview is a prefix of the opened cluster's first page and of recognition
     * source-of-truth order. updated_at is projection-sync time (curation bumps it
     * without moving assignment order), so ranking the preview by updated_at DESC
     * showed a different, differently-ordered set than the detail list. The
     * identity_uuid tie-breaker keeps the top-N slice deterministic when rows share
     * an assigned_at.
     */
    public function testListForClusterUuidsPreviewWindowMatchesDetailOrder(): void
    {
        global $wpdb;

        $this->repository->list_for_cluster_uuids(['cluster-a', 'cluster-b'], 3);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString(
            'ROW_NUMBER() OVER (PARTITION BY m.cluster_uuid ORDER BY m.assigned_at ASC, m.identity_uuid)',
            $sql
        );
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

    public function testReadPathsEmitLabelStateAndSharedReservedPredicateIncludingUnderscore(): void
    {
        global $wpdb;

        $this->repository->list_for_cluster('cluster-ab12', 10, 0, self::currentTenantId());
        $this->repository->list_for_cluster('cluster-ab12', 10, 0);
        $this->repository->list_for_cluster_uuids(['cluster-ab12'], 3);
        $this->repository->list_for_media_ids(self::currentTenantId(), [1]);

        $this->assertCount(4, $wpdb->queries, 'all four identity-members reads must be observed');
        foreach ($wpdb->queries as $sql) {
            $this->assertStringContainsString("LIKE 'cluster\\_%%'", $sql, $sql);
            $this->assertStringContainsString('AS label_state', $sql, $sql);
            $this->assertStringContainsString("THEN 'person'", $sql, $sql);
            $this->assertStringContainsString("THEN 'unlabeled'", $sql, $sql);
            $this->assertStringContainsString("ELSE 'unbound'", $sql, $sql);
        }
    }
}
