<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\OutboxDispatcher;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\OutboxMaintenanceService;
use AltContext\Tests\TestCase;

class OutboxMaintenanceServiceTest extends TestCase
{
    public function testRetryFailedOperationResetsStateRefreshesMetricsAndSchedulesDrain(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 1,
            'failed' => 0,
            'conflicts' => 0,
        ]);

        $service = new OutboxMaintenanceService();
        $result = $service->retry_failed_operation(9, $tenantId);

        $this->assertTrue($result);
        $updateQuery = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_outbox SET');
        $this->assertStringContainsString("status = 'pending'", $updateQuery);
        $this->assertStringContainsString('attempts = 0', $updateQuery);
        $this->assertStringContainsString('last_error_code = NULL', $updateQuery);

        $syncStateUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_state SET');
        $this->assertStringContainsString('pending_curation_operations = 1', $syncStateUpdate);
        $this->assertStringContainsString('failed_curation_operations = 0', $syncStateUpdate);
        $this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
    }

    public function testBulkRetryRequeuesOnlyFailedRowsForTenantWithCasGuard(): void
    {
        // E15-35 Slice 2: one guarded action requeues every failed push for the tenant —
        // failed rows for other tenants and non-failed rows for this tenant are untouched,
        // and every per-row UPDATE re-checks status='failed' (CAS) so a concurrent status
        // transition is never double-applied.
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 2,
            'failed' => 0,
            'conflicts' => 0,
        ]);
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildOutboxRow(1, $tenantId, 'failed'),
            $this->buildOutboxRow(2, $tenantId, 'failed'),
            $this->buildOutboxRow(3, 'tenant-other', 'failed'),
            $this->buildOutboxRow(4, $tenantId, 'pending', 1),
            $this->buildOutboxRow(5, $tenantId, 'conflict', 2),
        ];

        $service = new OutboxMaintenanceService();
        $this->assertSame(2, $service->retry_failed_operations_bulk($tenantId));

        $rowsById = array_column($wpdb->tableRows['wp_acx_sync_outbox'], null, 'id');
        foreach ([1, 2] as $requeuedId) {
            $this->assertSame('pending', $rowsById[$requeuedId]['status']);
            $this->assertSame(0, $rowsById[$requeuedId]['attempts']);
            $this->assertNull($rowsById[$requeuedId]['last_error_code']);
            $this->assertNull($rowsById[$requeuedId]['last_error_message']);
            $this->assertNull($rowsById[$requeuedId]['last_attempted_at']);
            $this->assertNull($rowsById[$requeuedId]['first_failed_at']);
        }

        $this->assertSame('failed', $rowsById[3]['status']);
        $this->assertSame('pending', $rowsById[4]['status']);
        $this->assertSame(1, $rowsById[4]['attempts']);
        $this->assertSame('conflict', $rowsById[5]['status']);

        $updates = array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_starts_with($query, 'UPDATE wp_acx_sync_outbox SET')
        ));
        $this->assertCount(2, $updates);
        foreach ($updates as $update) {
            $this->assertStringContainsString("AND status = 'failed'", $update);
        }

        $syncStateUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_sync_state SET');
        $this->assertStringContainsString('pending_curation_operations = 2', $syncStateUpdate);
        $this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
    }

    public function testBulkRetryPacesRequeueSoOneDrainCycleClaimsFewerThanAllRows(): void
    {
        // E15-35 Slice 2 (PA-05): the incident's thundering herd must not recur — a bulk
        // requeue of N rows seeds a spread next_attempt_at so only the first drain-batch-sized
        // chunk is claimable immediately (claim gate: next_attempt_at IS NULL OR <= now);
        // each later chunk is deferred by one further pacing stride.
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 5,
            'failed' => 0,
            'conflicts' => 0,
        ]);
        add_filter('acx_outbox_drain_batch_size', static fn (): int => 2);

        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildOutboxRow(1, $tenantId, 'failed'),
            $this->buildOutboxRow(2, $tenantId, 'failed'),
            $this->buildOutboxRow(3, $tenantId, 'failed'),
            $this->buildOutboxRow(4, $tenantId, 'failed'),
            $this->buildOutboxRow(5, $tenantId, 'failed'),
        ];

        $service = new OutboxMaintenanceService();
        $before = (int) current_time('timestamp');
        $this->assertSame(5, $service->retry_failed_operations_bulk($tenantId));

        $rowsById = array_column($wpdb->tableRows['wp_acx_sync_outbox'], null, 'id');

        // First chunk (drain batch size 2) is due immediately.
        $this->assertNull($rowsById[1]['next_attempt_at']);
        $this->assertNull($rowsById[2]['next_attempt_at']);

        // Later chunks are strictly in the future — a single drain cycle claims < N.
        $chunkTwo = $this->parseWpTimestamp((string) $rowsById[3]['next_attempt_at']);
        $chunkThree = $this->parseWpTimestamp((string) $rowsById[5]['next_attempt_at']);
        $this->assertSame($rowsById[3]['next_attempt_at'], $rowsById[4]['next_attempt_at']);
        $this->assertGreaterThan($before, $chunkTwo);
        $this->assertGreaterThanOrEqual($before + 60, $chunkTwo);
        $this->assertLessThanOrEqual($before + 62, $chunkTwo);
        $this->assertSame(60, $chunkThree - $chunkTwo);
    }

    public function testBulkRetryReturnsZeroAndSkipsSideEffectsWhenNothingFailed(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildOutboxRow(1, $tenantId, 'pending', 1),
        ];

        $service = new OutboxMaintenanceService();
        $this->assertSame(0, $service->retry_failed_operations_bulk($tenantId));

        $updates = array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_starts_with($query, 'UPDATE')
        ));
        $this->assertSame([], $updates);
        $this->assertFalse($this->isHookScheduled('acx_sync_drain_curation_outbox'));
    }

    public function testBulkRetryReturnsFalseForBlankTenant(): void
    {
        $service = new OutboxMaintenanceService();
        $this->assertFalse($service->retry_failed_operations_bulk('   '));
    }

    /**
     * @return array<string,mixed>
     */
    private function buildOutboxRow(int $id, string $tenantId, string $status, int $attempts = 5): array
    {
        return [
            'id' => $id,
            'tenant_id' => $tenantId,
            'status' => $status,
            'attempts' => $attempts,
            'last_error_code' => 'failed' === $status ? 'remote_error' : null,
            'last_error_message' => 'failed' === $status ? 'Remote curation replay failed.' : null,
            'last_attempted_at' => '2026-07-16 01:00:00',
            'first_failed_at' => 'failed' === $status ? '2026-07-16 00:00:00' : null,
            'next_attempt_at' => null,
        ];
    }

    private function parseWpTimestamp(string $value): int
    {
        $parsed = \DateTimeImmutable::createFromFormat('Y-m-d H:i:s', $value, new \DateTimeZone('UTC'));
        $this->assertNotFalse($parsed, sprintf('Expected WP-clock datetime, got "%s".', $value));

        return $parsed->getTimestamp();
    }

    /**
     * @param array<string,int|string|null> $overrides
     */
    private function configureSyncMetricQueries(string $tenantId, array $overrides = []): void
    {
        global $wpdb;

        $wpdb->mockRow = [
            'last_curation_acknowledged_at' => null,
            'last_curation_conflict_at' => null,
            'last_curation_failed_at' => null,
        ];

        $pending = (int) ($overrides['pending'] ?? 0);
        $failed = (int) ($overrides['failed'] ?? 0);
        $conflicts = (int) ($overrides['conflicts'] ?? 0);

        $wpdb->queryResults[$wpdb->prepare(
            'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
            'wp_acx_sync_outbox',
            $tenantId,
            'pending'
        )] = $pending;
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
            'wp_acx_sync_outbox',
            $tenantId,
            'failed'
        )] = $failed;
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND resolution_status = %s',
            'wp_acx_sync_conflicts',
            $tenantId,
            'open'
        )] = $conflicts;
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
    }

    private function isHookScheduled(string $hook): bool
    {
        foreach (array_keys($GLOBALS['__ac_scheduled']) as $key) {
            if (str_starts_with($key, $hook . '::')) {
                return true;
            }
        }

        foreach (array_keys($GLOBALS['__ac_action_scheduler'] ?? []) as $key) {
            if (str_starts_with($key, $hook . '::')) {
                return true;
            }
        }

        return false;
    }
}
