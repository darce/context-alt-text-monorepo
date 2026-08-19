<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClustersReadRepository;
use AltContext\Sovereign\Repositories\IdentityMembersReadRepository;
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

    public function testListLabelsExcludesReservedAndUnboundLabels(): void
    {
        global $wpdb;

        $tenant = self::currentTenantId();
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'c-auto-dash',
                'tenant_id' => $tenant,
                'label' => 'cluster-abcdef01',
                'person_id' => 1,
            ],
            [
                'cluster_uuid' => 'c-auto-under',
                'tenant_id' => $tenant,
                'label' => 'cluster_x',
                'person_id' => 2,
            ],
            [
                'cluster_uuid' => 'c-unbound',
                'tenant_id' => $tenant,
                'label' => 'Tory Guzman',
                'person_id' => null,
            ],
            [
                'cluster_uuid' => 'c-bound',
                'tenant_id' => $tenant,
                'label' => 'Ada Lovelace',
                'person_id' => 9,
            ],
        ];

        $labels = $this->repository->list_labels($tenant);
        $names = array_map(static fn(array $row): string => (string) ($row['label'] ?? ''), $labels);

        $this->assertSame(['Ada Lovelace'], $names);
    }

    public function testListLabelsDedupsBeforeLimitAndCountsDistinctLabels(): void
    {
        global $wpdb;

        $tenant = self::currentTenantId();
        $wpdb->tableRows['wp_acx_clusters'] = [
            ['cluster_uuid' => 'c-alice-1', 'tenant_id' => $tenant, 'label' => 'Alice', 'person_id' => 1],
            ['cluster_uuid' => 'c-alice-2', 'tenant_id' => $tenant, 'label' => 'Alice', 'person_id' => 2],
            ['cluster_uuid' => 'c-alice-3', 'tenant_id' => $tenant, 'label' => 'Alice', 'person_id' => 3],
            ['cluster_uuid' => 'c-bob', 'tenant_id' => $tenant, 'label' => 'Bob', 'person_id' => 4],
            ['cluster_uuid' => 'c-carol', 'tenant_id' => $tenant, 'label' => 'Carol', 'person_id' => 5],
            ['cluster_uuid' => 'c-dana', 'tenant_id' => $tenant, 'label' => 'Dana', 'person_id' => 6],
        ];

        $labels = $this->repository->list_labels($tenant, '', 3);
        $names = array_map(static fn(array $row): string => (string) ($row['label'] ?? ''), $labels);

        $this->assertSame(['Alice', 'Bob', 'Carol'], $names, 'LIMIT 3 must apply after DISTINCT, not to duplicate rows');
        $this->assertCount(3, $labels);
        $this->assertSame(4, (int) ($labels[0]['total_count'] ?? 0), 'total_count must be the distinct-label set, not the page size');
        $this->assertSame(4, (int) ($labels[1]['total_count'] ?? 0));
        $this->assertSame(4, (int) ($labels[2]['total_count'] ?? 0));
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

    public function testListForTenantIssuedSqlUsesSharedReservedLabelPredicate(): void
    {
        global $wpdb;

        $detector = new class() {
            use \AltContext\Support\DetectsSystemDefinedLabels;

            public function fragment(): string
            {
                return $this->projected_cluster_label_sql();
            }

            public function reserved(): string
            {
                return $this->reserved_label_sql_predicate('c.label');
            }
        };
        $fragment = $detector->fragment();
        $reserved = $detector->reserved();

        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-reserved-x',
                'tenant_id' => self::currentTenantId(),
                'label' => 'cluster_x',
            ],
            [
                'cluster_uuid' => 'cluster-reserved-upper',
                'tenant_id' => self::currentTenantId(),
                'label' => 'CLUSTER-1',
            ],
        ];

        $this->repository->list_for_tenant(self::currentTenantId(), 10, 0);

        $this->assertNotSame('', $fragment);
        $this->assertStringContainsString($fragment, $wpdb->queries[0]);
        $this->assertStringContainsString($reserved, $wpdb->queries[0]);
        $this->assertStringContainsString('LOWER(c.label)', $reserved);
        $this->assertTrue((new class() {
            use \AltContext\Support\DetectsSystemDefinedLabels;

            public function check(string $label): bool
            {
                return $this->is_reserved_label_shape($label);
            }
        })->check('cluster_x'));
        $this->assertTrue((new class() {
            use \AltContext\Support\DetectsSystemDefinedLabels;

            public function check(string $label): bool
            {
                return $this->is_reserved_label_shape($label);
            }
        })->check('CLUSTER-1'));
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
        $this->assertStringContainsString('c.tenant_id =', $wpdb->queries[0]);
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
        $this->assertStringContainsString('THEN p.name', $wpdb->queries[0]);
        $this->assertStringNotContainsString("c.label IS NOT NULL AND c.label != ''", $wpdb->queries[0]);
        $this->assertStringContainsString('THEN p.name', $wpdb->queries[0]);
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
        $this->assertStringContainsString('THEN p.name', $wpdb->queries[0]);
        $this->assertStringContainsString("c.label LIKE '%Alice%'", $wpdb->queries[0]);
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

    /**
     * M3: both cluster and identity-members read paths emit AS label_state
     * with the same three-valued CASE. Reverting the clusters-read SELECT
     * change fails this. Labeled-only WHERE still interpolates the label
     * value CASE (as label alias is not a faithful swap of
     * projected_cluster_label_select_sql).
     */
    public function testClusterReadsAgreeWithIdentityMembersOnLabelStateShape(): void
    {
        global $wpdb;

        $this->repository->list_for_tenant(self::currentTenantId(), 10, 0);
        $this->repository->list_for_tenant(self::currentTenantId(), 10, 0, ['labeled_only' => true]);
        $this->repository->list_for_tenant(self::currentTenantId(), 10, 0, ['search' => 'Alice']);
        $this->repository->list_for_tenant(
            self::currentTenantId(),
            10,
            0,
            [
                'labeled_only' => true,
                'search' => 'Alice',
            ]
        );
        $this->repository->list_top_unlabeled(self::currentTenantId(), 10);
        $this->repository->find_by_uuid('cluster-find');

        $clusterSql = $wpdb->queries;
        $this->assertCount(6, $clusterSql, 'four list_for_tenant variants + top-unlabeled + find_by_uuid');

        $wpdb->queries = [];
        $members = new IdentityMembersReadRepository('wp_acx_identity_members', 'wp_acx_clusters');
        $members->list_for_cluster('cluster-ab12', 10, 0, self::currentTenantId());
        $members->list_for_cluster('cluster-ab12', 10, 0);
        $members->list_for_cluster_uuids(['cluster-ab12'], 3);
        $members->list_for_media_ids(self::currentTenantId(), [1]);
        $memberSql = $wpdb->queries;
        $this->assertCount(4, $memberSql, 'all four identity-members reads must be observed');

        foreach (array_merge($clusterSql, $memberSql) as $sql) {
            $this->assertStringContainsString('AS label_state', $sql, $sql);
            $this->assertStringContainsString("THEN 'person'", $sql, $sql);
            $this->assertStringContainsString("THEN 'unlabeled'", $sql, $sql);
            $this->assertStringContainsString("ELSE 'unbound'", $sql, $sql);
        }

        $labeledOnly = $clusterSql[1];
        $this->assertStringContainsString(' as label, ', $labeledOnly);
        $this->assertStringContainsString('AS label_state', $labeledOnly);
        $this->assertDoesNotMatchRegularExpression('/AS label_state\s+IS NOT NULL/', $labeledOnly);
        $this->assertStringContainsString('IS NOT NULL', $labeledOnly);
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
