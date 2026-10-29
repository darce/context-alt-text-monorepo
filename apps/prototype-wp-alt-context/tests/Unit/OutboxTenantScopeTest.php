<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\TenantIdentity;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Tests\TestCase;

final class OutboxTenantScopeTest extends TestCase
{
    private const A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
    private const B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
    private const TABLE = 'wp_acx_sync_outbox';
    private mixed $originalDb;

    protected function setUp(): void
    {
        parent::setUp();
        $this->originalDb = $GLOBALS['wpdb'];
        $GLOBALS['wpdb'] = new TenantScopeDb();
        $GLOBALS['__ac_current_time'] = strtotime('2026-10-28 12:00:00 UTC');
        $this->setOption(TenantIdentity::OPTION_KEY, self::B);
        $this->setOption('acx_recognition_url', 'https://api.example.test');
    }

    protected function tearDown(): void
    {
        $GLOBALS['wpdb'] = $this->originalDb;
        parent::tearDown();
    }

    public function testSelectionScopesBeforeOrderingAndLimitAndStillHonorsBackoff(): void
    {
        global $wpdb;
        $wpdb->tableRows[self::TABLE] = [
            $this->row(1, self::A),
            $this->row(2, self::B, ['next_attempt_at' => '2026-10-28 13:00:00']),
            $this->row(3, self::B),
            $this->row(4, self::B),
        ];
        $before = $wpdb->tableRows[self::TABLE];
        $rows = (new OutboxQueryRepository())->load_pending_operations(1);
        $this->assertSame([3], array_column($rows, 'id'));
        $this->assertSame(['cluster_uuid' => $this->cluster(3), 'label' => 'Label 3'], $rows[0]['payload']);
        $this->assertSame($before, $wpdb->tableRows[self::TABLE]);
    }

    public function testDirectOldTenantClaimFailsWithoutMutationAndCurrentClaimKeepsTokenFence(): void
    {
        global $wpdb;
        $old = $this->row(1, self::A);
        $wpdb->tableRows[self::TABLE] = [$old, $this->row(2, self::B)];
        $repository = new OutboxQueryRepository();
        $this->assertFalse($repository->claim_operation(1));
        $this->assertSame($old, $wpdb->tableRows[self::TABLE][0]);
        $claim = $repository->claim_operation(2);
        $this->assertIsArray($claim);
        $this->assertSame(self::B, $claim['tenant_id']);
        $this->assertSame('in_flight', $claim['status']);
        $this->assertMatchesRegularExpression('/^[a-f0-9]{64}$/', $claim['claim_token']);
        $this->assertFalse($repository->claim_operation(2));
    }

    public function testClaimResolvesIdentityAgainAfterSelection(): void
    {
        global $wpdb;
        $wpdb->tableRows[self::TABLE] = [$this->row(1, self::A), $this->row(2, self::B)];
        $repository = new OutboxQueryRepository();
        $this->assertSame([2], array_column($repository->load_pending_operations(10), 'id'));
        $this->setOption(TenantIdentity::OPTION_KEY, self::A);
        $this->assertFalse($repository->claim_operation(2));
        $this->assertSame([1], array_column($repository->load_pending_operations(10), 'id'));
    }

    public function testSchedulerReadsExcludeOldPendingAndInFlightRows(): void
    {
        global $wpdb;
        $wpdb->tableRows[self::TABLE] = [
            $this->row(1, self::A),
            $this->row(2, self::A, ['status' => 'in_flight', 'claimed_at' => null]),
            $this->row(3, self::B, ['next_attempt_at' => '2026-10-28 13:00:00']),
            $this->row(4, self::B, ['status' => 'in_flight', 'claimed_at' => '2026-10-28 11:59:00']),
        ];
        $repository = new OutboxQueryRepository();
        $this->assertTrue($repository->has_pending_operations());
        $this->assertSame('2026-10-28 13:00:00', $repository->earliest_pending_attempt_time());
        $this->assertSame('2026-10-28 12:04:00', $repository->earliest_in_flight_recovery_time(300));
        $wpdb->tableRows[self::TABLE] = array_slice($wpdb->tableRows[self::TABLE], 0, 2);
        $this->assertFalse($repository->has_pending_operations());
        $this->assertNull($repository->earliest_pending_attempt_time());
        $this->assertNull($repository->earliest_in_flight_recovery_time(300));
    }

    public function testRecoveryOnlyReclaimsExpiredCurrentTenantClaims(): void
    {
        global $wpdb;
        $old = $this->row(1, self::A, ['status' => 'in_flight', 'claimed_at' => null, 'claim_token' => 'old-token']);
        $wpdb->tableRows[self::TABLE] = [
            $old,
            $this->row(2, self::B, ['status' => 'in_flight', 'claimed_at' => null]),
            $this->row(3, self::B, ['status' => 'in_flight', 'claimed_at' => '2026-10-28 11:50:00', 'claim_token' => 'expired']),
            $this->row(4, self::B, ['status' => 'in_flight', 'claimed_at' => '2026-10-28 11:59:00', 'claim_token' => 'live']),
        ];
        $this->assertSame(2, (new OutboxQueryRepository())->reclaim_stale_in_flight_operations(300));
        $this->assertSame($old, $wpdb->tableRows[self::TABLE][0]);
        $this->assertSame(['in_flight', 'pending', 'pending', 'in_flight'], array_column($wpdb->tableRows[self::TABLE], 'status'));
        $this->assertNull($wpdb->tableRows[self::TABLE][2]['claim_token']);
        $this->assertSame('live', $wpdb->tableRows[self::TABLE][3]['claim_token']);
    }

    public function testRealDrainDispatchesOnlyCurrentRowsAndLeavesNoOldTenantWakeup(): void
    {
        global $wpdb;
        $old = [$this->row(1, self::A), $this->row(2, self::A, ['status' => 'in_flight', 'claimed_at' => null])];
        $wpdb->tableRows[self::TABLE] = [...$old, $this->row(3, self::B)];
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode(['status' => 'acknowledged', 'backend_version' => 61]),
        ]);
        $drain = new OutboxDrain();
        $drain->drain();
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame(self::B, $calls[0]['args']['headers']['X-Tenant-ID']);
        $body = json_decode($calls[0]['body'], true);
        $this->assertSame($this->cluster(3), $body['payload']['cluster_uuid'] ?? null);
        $this->assertArrayNotHasKey('operations', $body);
        $this->assertSame($old, array_slice($wpdb->tableRows[self::TABLE], 0, 2));
        $this->assertSame('acknowledged', $wpdb->tableRows[self::TABLE][2]['status']);
        $this->assertNoDrainScheduled();
        $drain->drain();
        $this->assertCount(1, $this->getHttpCalls());
        $this->assertNoDrainScheduled();
    }

    public function testOldDueRowsCannotTurnCurrentBackoffIntoAnImmediateDrain(): void
    {
        global $wpdb;
        $wpdb->tableRows[self::TABLE] = [$this->row(1, self::A), $this->row(2, self::B, ['next_attempt_at' => '2026-10-28 13:00:00'])];
        (new OutboxDrain())->drain();
        $this->assertSame([], $this->getHttpCalls());
        $scheduled = as_next_scheduled_action('acx_sync_drain_curation_outbox', [], 'acx-sync');
        $this->assertIsInt($scheduled);
        $this->assertEqualsWithDelta(time() + 3600, $scheduled, 2);
    }

    /** @dataProvider unresolvedConfiguration */
    public function testMissingOrInvalidConfiguredIdentityNeverOpensAllTenantScope(?string $configured): void
    {
        global $wpdb;
        if ($configured === null) {
            unset($GLOBALS['__ac_options'][TenantIdentity::OPTION_KEY]);
        } else {
            $this->setOption(TenantIdentity::OPTION_KEY, $configured);
        }
        $identity = TenantIdentity::resolve();
        $this->assertSame('derived', $identity['source']);
        $wpdb->tableRows[self::TABLE] = [$this->row(1, self::A), $this->row(2, self::B)];
        $before = $wpdb->tableRows[self::TABLE];
        $repository = new OutboxQueryRepository();
        $this->assertSame([], $repository->load_pending_operations(25));
        $this->assertFalse($repository->claim_operation(1));
        $this->assertFalse($repository->claim_operation(2));
        $this->assertFalse($repository->has_pending_operations());
        $this->assertNull($repository->earliest_pending_attempt_time());
        $this->assertNull($repository->earliest_in_flight_recovery_time(300));
        (new OutboxDrain())->drain();
        $this->assertSame([], $this->getHttpCalls());
        $this->assertSame($before, $wpdb->tableRows[self::TABLE]);
        $this->assertNoDrainScheduled();
    }

    public static function unresolvedConfiguration(): array
    {
        return ['missing' => [null], 'empty' => [''], 'invalid' => ['not-a-tenant-uuid']];
    }

    public function testExplicitOldTenantReportingRemainsAvailableAndBounded(): void
    {
        global $wpdb;
        $wpdb->tableRows[self::TABLE] = [
            $this->row(1, self::A, ['status' => 'failed']),
            $this->row(2, self::A, ['status' => 'failed']),
            $this->row(3, self::B, ['status' => 'failed']),
        ];
        $repository = new OutboxQueryRepository();
        $this->assertSame([1], $repository->find_failed_operation_ids(self::A, 1));
        $this->assertSame(2, $repository->count_operations_by_status(self::A, 'failed'));
        $this->assertSame(self::A, $repository->find_operation_by_id(1, self::A)['tenant_id']);
        $this->assertNull($repository->find_operation_by_id(1, self::B));
    }

    private function assertNoDrainScheduled(): void
    {
        $this->assertFalse(as_next_scheduled_action('acx_sync_drain_curation_outbox', [], 'acx-sync'));
        $this->assertFalse(wp_next_scheduled('acx_sync_drain_curation_outbox', []));
    }

    private function cluster(int $id): string
    {
        return sprintf('cccccccc-cccc-4ccc-8ccc-%012d', $id);
    }

    private function row(int $id, string $tenant, array $overrides = []): array
    {
        return array_replace([
            'id' => $id, 'tenant_id' => $tenant, 'status' => 'pending',
            'operation_type' => 'cluster_label_updated', 'entity_type' => 'cluster',
            'entity_key' => $this->cluster($id), 'idempotency_key' => 'tenant-scope-' . $id,
            'expected_base_version' => 1, 'local_revision' => 1, 'attempts' => 0,
            'payload' => wp_json_encode(['cluster_uuid' => $this->cluster($id), 'label' => 'Label ' . $id]),
            'created_at' => '2026-10-27 12:00:00', 'next_attempt_at' => null,
            'first_failed_at' => null, 'claimed_at' => null, 'claim_token' => null,
        ], $overrides);
    }
}

/**
 * Execute the repository's SQL predicates over all fixture rows. This adapter knows
 * nothing about the active identity: absent tenant predicates deliberately see A+B.
 * The shared stub cannot evaluate multiline/backoff/aggregate/lease expressions.
 */
final class TenantScopeDb extends \WPDBStub
{
    public function get_results($query, $output = OBJECT)
    {
        $sql = preg_replace('/\s+/', ' ', trim($query));
        if (!str_contains($sql, 'FROM `wp_acx_sync_outbox`')) {
            return parent::get_results($query, $output);
        }
        $this->queries[] = $query;
        $rows = $this->matchingRows($sql);
        if (str_contains($sql, 'ORDER BY created_at ASC')) {
            usort($rows, static fn ($a, $b) => [$a['created_at'], $a['id']] <=> [$b['created_at'], $b['id']]);
        } elseif (str_contains($sql, 'ORDER BY id ASC')) {
            usort($rows, static fn ($a, $b) => $a['id'] <=> $b['id']);
        }
        if (preg_match('/LIMIT (\d+)/', $sql, $limit)) {
            $rows = array_slice($rows, 0, (int) $limit[1]);
        }
        return $output === ARRAY_A ? $rows : array_map(static fn ($row) => (object) $row, $rows);
    }

    public function get_var($query, $x = 0, $y = 0)
    {
        $sql = preg_replace('/\s+/', ' ', trim($query));
        if (!str_contains($sql, 'FROM `wp_acx_sync_outbox`')) {
            return parent::get_var($query, $x, $y);
        }
        $this->queries[] = $query;
        $rows = $this->matchingRows($sql);
        if (str_starts_with($sql, 'SELECT COUNT(*)')) {
            return count($rows);
        }
        if (str_contains($sql, 'MIN(COALESCE(next_attempt_at, created_at))')) {
            $times = array_map(static fn ($row) => $row['next_attempt_at'] ?? $row['created_at'], $rows);
            return $times === [] ? null : min($times);
        }
        if (str_contains($sql, 'MIN(CASE WHEN claimed_at IS NULL')) {
            preg_match('/INTERVAL (\d+) SECOND/', $sql, $lease);
            $times = array_map(static fn ($row) => $row['claimed_at'] === null
                ? current_time('mysql')
                : gmdate('Y-m-d H:i:s', strtotime($row['claimed_at'] . ' UTC') + (int) $lease[1]), $rows);
            return $times === [] ? null : min($times);
        }
        return $rows[0]['id'] ?? null;
    }

    public function query($query)
    {
        if (!str_contains($query, 'SET status = \'pending\', claimed_at = NULL, claim_token = NULL')) {
            return parent::query($query);
        }
        $this->queries[] = $query;
        preg_match('/INTERVAL (\d+) SECOND/', $query, $lease);
        $cutoff = gmdate('Y-m-d H:i:s', strtotime(current_time('mysql') . ' UTC') - (int) $lease[1]);
        $ids = array_column($this->matchingRows($query), 'id');
        $count = 0;
        foreach ($this->tableRows['wp_acx_sync_outbox'] as &$row) {
            if (in_array($row['id'], $ids, true) && ($row['claimed_at'] === null || $row['claimed_at'] <= $cutoff)) {
                $row = array_replace($row, ['status' => 'pending', 'claimed_at' => null, 'claim_token' => null]);
                ++$count;
            }
        }
        return $count;
    }

    private function matchingRows(string $sql): array
    {
        $where = explode('WHERE ', $sql, 2)[1] ?? '';
        return array_values(array_filter($this->tableRows['wp_acx_sync_outbox'] ?? [], static function ($row) use ($where): bool {
            foreach (['tenant_id', 'status', 'id', 'claim_token'] as $column) {
                if (preg_match('/\b' . $column . ' = (?:\'([^\']*)\'|(\d+))/', $where, $match)
                    && (string) ($row[$column] ?? '') !== ($match[1] !== '' ? $match[1] : $match[2])) {
                    return false;
                }
            }
            if (preg_match('/next_attempt_at <= \'([^\']+)\'/', $where, $due)
                && $row['next_attempt_at'] !== null && $row['next_attempt_at'] > $due[1]) {
                return false;
            }
            return true;
        }));
    }
}
