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

    public function testListTopUnlabeledResolvesMembersTableFromWpdbPrefix(): void
    {
        global $wpdb;
        $wpdb->prefix = 'wp_';
        $wpdb->mockResults = [];

        $repository = new ClustersReadRepository('custom_cluster_projection');
        $repository->list_top_unlabeled(self::currentTenantId(), 10);

        $sql = $wpdb->queries[0];
        $this->assertStringContainsString('`wp_acx_identity_members`', $sql);
        $this->assertStringContainsString('`custom_cluster_projection`', $sql);
        $this->assertStringNotContainsString('custom_identity_members', $sql);
    }

    public function testListUnlabeledIdentityCountDriftUsesMemberCountNotProjectedColumn(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $this->repository->list_unlabeled_identity_count_drift(self::currentTenantId(), 50);

        $sql = $wpdb->queries[0];
        $this->assertStringContainsString('`wp_acx_identity_members`', $sql);
        $this->assertStringContainsString('c.identity_count <>', $sql);
        $this->assertStringNotContainsString('c.identity_count >= 2', $sql);
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
     * E21-14-R3 / B5: queue predicate must be backed by acx_identity_members
     * rows so a stale identity_count=3 with 0 members cannot be served.
     */
    public function testListTopUnlabeledRequiresObservedMemberRows(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $this->repository->list_top_unlabeled(self::currentTenantId(), 10);

        $this->assertCount(1, $wpdb->queries);
        $sql = $wpdb->queries[0];
        $this->assertStringContainsString('`wp_acx_identity_members`', $sql);
        $this->assertStringContainsString('m.cluster_uuid = c.cluster_uuid', $sql);
        $this->assertMatchesRegularExpression('/COUNT\(\*\)\s*FROM\s*`wp_acx_identity_members`/i', $sql);
        $this->assertStringContainsString(') >= 2', $sql);
        $this->assertStringNotContainsString('c.identity_count >= 2', $sql);
        $this->assertDoesNotMatchRegularExpression('/OR\s+1\s*=\s*1/i', $sql);
    }

    /**
     * R1-01 / TEST-15: memberless + 2-member seed. SQL-substring tests survive
     * an `OR 1=1` mutant; this evaluates the predicates present in the SQL.
     */
    public function testListTopUnlabeledExcludesMemberlessClusterWhenSeeded(): void
    {
        global $wpdb;

        $clusters = [
            [
                'cluster_uuid' => 'cluster-memberless',
                'tenant_id' => self::currentTenantId(),
                'label' => '',
                'identity_count' => 5,
                'is_user_confirmed' => 0,
                'curation_state' => 'active',
            ],
            [
                'cluster_uuid' => 'cluster-two-members',
                'tenant_id' => self::currentTenantId(),
                'label' => '',
                'identity_count' => 2,
                'is_user_confirmed' => 0,
                'curation_state' => 'active',
            ],
        ];
        $member_counts = [
            'cluster-memberless' => 0,
            'cluster-two-members' => 2,
        ];

        $wpdb->onGetResults = function (string $sql) use ($clusters, $member_counts): array {
            return $this->filterTopUnlabeledBySql($sql, $clusters, $member_counts);
        };

        $rows = $this->repository->list_top_unlabeled(self::currentTenantId(), 10);

        $this->assertSame(['cluster-two-members'], array_column($rows, 'cluster_uuid'));
        $sql = $this->normalizeSql($wpdb->queries[0]);
        $this->assertSame($this->expectedTopUnlabeledWhereClause(self::currentTenantId()), $this->extractWhereClause($sql));
    }

    /**
     * R1-05a: 3 real members + stale identity_count=1 must be in the queue,
     * not counted as a singleton.
     */
    public function testStaleLowIdentityCountWithThreeMembersIsQueuedNotSingleton(): void
    {
        global $wpdb;

        $clusters = [
            [
                'cluster_uuid' => 'cluster-stale-low',
                'tenant_id' => self::currentTenantId(),
                'label' => '',
                'identity_count' => 1,
                'is_user_confirmed' => 0,
                'curation_state' => 'active',
            ],
        ];
        $member_counts = ['cluster-stale-low' => 3];

        $wpdb->onGetResults = function (string $sql) use ($clusters, $member_counts): array {
            return $this->filterTopUnlabeledBySql($sql, $clusters, $member_counts);
        };
        $wpdb->onGetVar = function (string $sql) use ($clusters, $member_counts): void {
            global $wpdb;
            $wpdb->mockVar = $this->countSingletonsBySql($sql, $clusters, $member_counts);
        };

        $queued = $this->repository->list_top_unlabeled(self::currentTenantId(), 10);
        $singletons = $this->repository->count_top_unlabeled_singletons(self::currentTenantId());

        $this->assertSame(['cluster-stale-low'], array_column($queued, 'cluster_uuid'));
        $this->assertSame(0, $singletons);
    }

    /**
     * R1-05b: stale identity_count=3 + 1 member is a singleton, not queue.
     */
    public function testStaleHighIdentityCountWithOneMemberIsSingletonNotQueued(): void
    {
        global $wpdb;

        $clusters = [
            [
                'cluster_uuid' => 'cluster-stale-high',
                'tenant_id' => self::currentTenantId(),
                'label' => '',
                'identity_count' => 3,
                'is_user_confirmed' => 0,
                'curation_state' => 'active',
            ],
        ];
        $member_counts = ['cluster-stale-high' => 1];

        $wpdb->onGetResults = function (string $sql) use ($clusters, $member_counts): array {
            return $this->filterTopUnlabeledBySql($sql, $clusters, $member_counts);
        };
        $wpdb->onGetVar = function (string $sql) use ($clusters, $member_counts): void {
            global $wpdb;
            $wpdb->mockVar = $this->countSingletonsBySql($sql, $clusters, $member_counts);
        };

        $queued = $this->repository->list_top_unlabeled(self::currentTenantId(), 10);
        $singletons = $this->repository->count_top_unlabeled_singletons(self::currentTenantId());

        $this->assertSame([], $queued);
        $this->assertSame(1, $singletons);
    }

    /**
     * R1-07: pre-filter drift scan compares identity_count to member COUNT.
     */
    public function testListUnlabeledIdentityCountDriftSelectsMismatchedRows(): void
    {
        global $wpdb;
        $wpdb->mockResults = [];

        $ids = $this->repository->list_unlabeled_identity_count_drift(self::currentTenantId(), 25);

        $this->assertSame([], $ids);
        $sql = preg_replace('/\s+/', ' ', $wpdb->queries[0] ?? '');
        $this->assertIsString($sql);
        $this->assertStringContainsString('c.identity_count <> ( SELECT COUNT(*) FROM `wp_acx_identity_members` m WHERE m.cluster_uuid = c.cluster_uuid )', $sql);
        $this->assertStringNotContainsString('identity_count >= 2', $sql);
        $this->assertStringContainsString('LIMIT 25', $sql);
    }

    /**
     * @param array<int,array<string,mixed>> $clusters
     * @param array<string,int> $member_counts
     * @return array<int,array<string,mixed>>
     */
    private function filterTopUnlabeledBySql(string $sql, array $clusters, array $member_counts): array
    {
        $uses_column_min = (bool) preg_match('/c\.identity_count\s*>=\s*2/', $sql);
        $uses_member_min = str_contains($sql, 'acx_identity_members')
            && (bool) preg_match('/\)\s*>=\s*2/', $sql);
        $or_bypass = (bool) preg_match('/OR\s+1\s*=\s*1/i', $sql);
        $or_column = (bool) preg_match('/\)\s*>=\s*2\s+OR\s+c\.identity_count/i', $sql);

        $matched = [];
        foreach ($clusters as $cluster) {
            if (! $this->matchesUnlabeledBase($cluster)) {
                continue;
            }
            $observed = $member_counts[$cluster['cluster_uuid']] ?? 0;
            if ($uses_column_min && ! $or_column && (int) $cluster['identity_count'] < 2) {
                continue;
            }
            $member_ok = $observed >= 2;
            if ($or_column) {
                $member_ok = $member_ok || (int) $cluster['identity_count'] >= 2;
            }
            if ($uses_member_min && ! $or_bypass && ! $member_ok) {
                continue;
            }
            $matched[] = $cluster;
        }

        return $matched;
    }

    /**
     * @param array<int,array<string,mixed>> $clusters
     * @param array<string,int> $member_counts
     */
    private function countSingletonsBySql(string $sql, array $clusters, array $member_counts): int
    {
        $uses_column = (bool) preg_match('/c\.identity_count\s*<=\s*1/', $sql);
        $uses_member = str_contains($sql, 'acx_identity_members')
            && (bool) preg_match('/\)\s*<=\s*1/', $sql);

        $count = 0;
        foreach ($clusters as $cluster) {
            if (! $this->matchesUnlabeledBase($cluster)) {
                continue;
            }
            $observed = $member_counts[$cluster['cluster_uuid']] ?? 0;
            if ($uses_column && (int) $cluster['identity_count'] > 1) {
                continue;
            }
            if ($uses_member && $observed > 1) {
                continue;
            }
            ++$count;
        }

        return $count;
    }

    /**
     * @param array<string,mixed> $cluster
     */
    private function matchesUnlabeledBase(array $cluster): bool
    {
        if ((int) ($cluster['is_user_confirmed'] ?? 0) !== 0) {
            return false;
        }
        $label = (string) ($cluster['label'] ?? '');
        $synthetic = $label === '' || str_starts_with($label, 'cluster-');
        if (! $synthetic) {
            return false;
        }
        $state = (string) ($cluster['curation_state'] ?? '');
        return $state !== 'dismissed';
    }

    private function expectedTopUnlabeledMemberCountPredicate(): string
    {
        return $this->normalizeSql(
            "( SELECT COUNT(*) FROM `wp_acx_identity_members` m WHERE m.cluster_uuid = c.cluster_uuid ) >= 2"
        );
    }

    private function expectedTopUnlabeledWhereClause(string $tenant_id): string
    {
        return $this->normalizeSql(
            "c.tenant_id = '{$tenant_id}' AND c.is_user_confirmed = 0 AND (c.label IS NULL OR c.label = '' OR (LOWER(c.label) LIKE 'cluster-%%' OR LOWER(c.label) LIKE 'cluster\\_%%')) AND ( SELECT COUNT(*) FROM `wp_acx_identity_members` m WHERE m.cluster_uuid = c.cluster_uuid ) >= 2 AND (c.curation_state IS NULL OR c.curation_state <> 'dismissed')"
        );
    }

    private function extractWhereClause(string $normalized_sql): string
    {
        if (! preg_match('/WHERE (.+) ORDER BY/i', $normalized_sql, $matches)) {
            $this->fail('top-unlabeled SQL must have a WHERE ... ORDER BY clause');
        }

        return $this->normalizeSql($matches[1]);
    }

    private function normalizeSql(string $sql): string
    {
        return trim((string) preg_replace('/\s+/', ' ', $sql));
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
