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
        $sql = $wpdb->queries[0];
        $this->assertStringContainsString($this->expectedTopUnlabeledMemberCountPredicate(), $this->normalizeSql($sql));
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

        $matched = [];
        foreach ($clusters as $cluster) {
            if (! $this->matchesUnlabeledBase($cluster)) {
                continue;
            }
            $observed = $member_counts[$cluster['cluster_uuid']] ?? 0;
            if ($uses_column_min && (int) $cluster['identity_count'] < 2) {
                continue;
            }
            if ($uses_member_min && ! $or_bypass && $observed < 2) {
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

    private function normalizeSql(string $sql): string
    {
        return trim((string) preg_replace('/\s+/', ' ', $sql));
    }
}
