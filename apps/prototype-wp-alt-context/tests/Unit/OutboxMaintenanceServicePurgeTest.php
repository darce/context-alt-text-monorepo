<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\ConflictResolutionStatus;
use AltContext\Sovereign\Sync\OutboxMaintenanceService;
use AltContext\Sovereign\Sync\OutboxStatus;
use AltContext\Tests\TestCase;

class OutboxMaintenanceServicePurgeTest extends TestCase
{
    public function testPurgeTerminalRowsDeletesAcknowledgedOutboxOlderThanRetentionWindow(): void
    {
        global $wpdb;

        $tenantId = 'tenant-purge-1';
        $wpdb->defaultQueryResult = 0;
        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');

        $purged = $service->purge_terminal_rows($tenantId);

        $deleteQuery = $this->findQueryContaining($wpdb->queries, 'DELETE FROM `wp_acx_sync_outbox`');
        $this->assertStringContainsString("status = '" . OutboxStatus::ACKNOWLEDGED . "'", $deleteQuery);
        $this->assertMatchesRegularExpression(
            "/acknowledged_at < '20\\d{2}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}'/",
            $deleteQuery
        );
        $expectedCutoff = gmdate('Y-m-d H:i:s', current_time('timestamp') - (14 * 86400));
        $this->assertStringContainsString(substr($expectedCutoff, 0, 10), $deleteQuery);
        $this->assertSame(0, $purged['outbox']);
        $this->assertSame(0, $purged['purged_failed']);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testPurgeTerminalRowsDeletesResolvedConflictsOlderThanRetentionWindow(): void
    {
        global $wpdb;

        $tenantId = 'tenant-purge-2';
        $wpdb->defaultQueryResult = 0;
        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', 'wp_custom_conflicts');

        $purged = $service->purge_terminal_rows($tenantId);

        $deleteQuery = $this->findQueryContaining($wpdb->queries, 'DELETE FROM `wp_custom_conflicts`');
        $this->assertStringContainsString(
            "resolution_status <> '" . ConflictResolutionStatus::OPEN . "'",
            $deleteQuery
        );
        $this->assertMatchesRegularExpression(
            "/resolved_at < '20\\d{2}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}'/",
            $deleteQuery
        );
        $this->assertSame(0, $purged['conflicts']);
        $this->assertSame(0, $purged['purged_failed']);
    }

    public function testPurgeTerminalRowsDeletesOldNonRetryableFailedRows(): void
    {
        global $wpdb;

        $tenantId = 'tenant-purge-failed';
        $now = (int) current_time('timestamp');
        $oldStamp = gmdate('Y-m-d H:i:s', $now - (8 * 86400));
        $recentStamp = gmdate('Y-m-d H:i:s', $now - (2 * 86400));
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildFailedOutboxRow(41, $tenantId, 'invalid_payload', $oldStamp),
            $this->buildFailedOutboxRow(42, $tenantId, 'unauthorized', $recentStamp),
            $this->buildFailedOutboxRow(43, $tenantId, 'auto_retry_exhausted', $oldStamp),
        ];

        $syncState = $this->trackingSyncStateRepository();
        $service = new OutboxMaintenanceService(null, $syncState, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertIsArray($purged);
        $this->assertSame(0, $purged['retried']);
        $this->assertSame(0, $purged['dead_lettered']);
        $this->assertSame(1, $purged['purged_failed']);
        $this->assertSame(1, $purged['outbox']);
        $this->assertSame(1, $syncState->refreshCount);

        $selectQuery = $this->findQueryContaining($wpdb->queries, 'last_error_code IN');
        $this->assertStringContainsString('SELECT id, first_failed_at, last_attempted_at, created_at, last_error_code FROM `wp_acx_sync_outbox`', $selectQuery);
        $this->assertStringContainsString("status = '" . OutboxStatus::FAILED . "'", $selectQuery);
        $this->assertStringContainsString("'invalid_payload'", $selectQuery);
        $this->assertStringContainsString("'unauthorized'", $selectQuery);

        $remaining = array_column($wpdb->tableRows['wp_acx_sync_outbox'], null, 'id');
        $this->assertArrayNotHasKey(41, $remaining);
        $this->assertArrayHasKey(42, $remaining);
        $this->assertArrayHasKey(43, $remaining);
        $this->assertSame(OutboxStatus::FAILED, $remaining[42]['status']);
        $this->assertSame(OutboxStatus::FAILED, $remaining[43]['status']);
    }

    public function testPurgeRefreshesMetricsWhenOnlyOldNonRetryableFailedRowsArePurged(): void
    {
        global $wpdb;

        $tenantId = 'tenant-purge-failed-refresh';
        $oldStamp = gmdate('Y-m-d H:i:s', (int) current_time('timestamp') - (10 * 86400));
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildFailedOutboxRow(51, $tenantId, 'forbidden', $oldStamp),
        ];

        $syncState = $this->trackingSyncStateRepository();
        $service = new OutboxMaintenanceService(null, $syncState, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(0, $purged['retried']);
        $this->assertSame(0, $purged['dead_lettered']);
        $this->assertSame(1, $purged['purged_failed']);
        $this->assertSame(1, $purged['outbox']);
        $this->assertSame(1, $syncState->refreshCount);
        $this->assertSame($tenantId, $syncState->lastTenantId);
        $this->assertSame([], $wpdb->tableRows['wp_acx_sync_outbox']);
    }

    public function testPurgeAutoRetriesRetryableFailedRowsWithExponentialBackoff(): void
    {
        global $wpdb;

        $tenantId = 'tenant-retry-failed';
        $wpdb->defaultQueryResult = 0;
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 1,
            'failed' => 0,
            'conflicts' => 0,
        ]);
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildFailedOutboxRow(11, $tenantId, 'remote_error'),
            $this->buildFailedOutboxRow(12, $tenantId, 'invalid_payload'),
        ];

        $before = (int) current_time('timestamp');
        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(1, $purged['retried']);
        $this->assertSame(0, $purged['dead_lettered']);
        $this->assertSame(0, $purged['skipped_concurrent']);

        $rowsById = array_column($wpdb->tableRows['wp_acx_sync_outbox'], null, 'id');
        $this->assertSame(OutboxStatus::PENDING, $rowsById[11]['status']);
        $this->assertSame(0, $rowsById[11]['attempts']);
        $this->assertNull($rowsById[11]['first_failed_at']);
        $this->assertNotNull($rowsById[11]['next_attempt_at']);
        $due = \DateTimeImmutable::createFromFormat(
            'Y-m-d H:i:s',
            (string) $rowsById[11]['next_attempt_at'],
            new \DateTimeZone('UTC')
        );
        $this->assertNotFalse($due);
        $this->assertSame($before + 60, $due->getTimestamp());
        $payload = json_decode((string) $rowsById[11]['payload'], true);
        $this->assertIsArray($payload);
        $this->assertSame(1, $payload['acx_auto_attempts']);
        $this->assertSame(OutboxStatus::FAILED, $rowsById[12]['status']);
        $this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
    }

    public function testPurgeDeadLettersRetryableFailedRowsAfterMaxAutoAttempts(): void
    {
        global $wpdb;

        $tenantId = 'tenant-dead-letter';
        $wpdb->defaultQueryResult = 0;
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 0,
            'failed' => 0,
            'conflicts' => 0,
        ]);
        $row = $this->buildFailedOutboxRow(21, $tenantId, 'transport_error');
        $row['payload'] = wp_json_encode(['acx_auto_attempts' => 3]);
        $row['first_failed_at'] = gmdate('Y-m-d H:i:s', current_time('timestamp') - 3600);
        $wpdb->tableRows['wp_acx_sync_outbox'] = [$row];

        $before = (int) current_time('timestamp');
        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(0, $purged['retried']);
        $this->assertSame(1, $purged['dead_lettered']);
        $this->assertSame(0, $purged['skipped_concurrent']);
        $updated = $wpdb->tableRows['wp_acx_sync_outbox'][0];
        $this->assertSame(OutboxStatus::FAILED, $updated['status']);
        $this->assertSame('auto_retry_exhausted', $updated['last_error_code']);
        $this->assertSame(3, $updated['attempts']);
        $this->assertSame(gmdate('Y-m-d H:i:s', $before), $updated['last_attempted_at']);
        $this->assertNull($updated['next_attempt_at']);
        $this->assertStringContainsString('age 3600 seconds', (string) $updated['last_error_message']);
    }

    public function testOperatorRetryClearsAutoAttemptMarkerBeforeNextMaintenanceFailure(): void
    {
        global $wpdb;

        $tenantId = 'tenant-operator-retry';
        $wpdb->defaultQueryResult = 0;
        $row = $this->buildFailedOutboxRow(81, $tenantId, 'transport_error');
        $row['payload'] = wp_json_encode([
            'cluster_uuid' => 'cluster-81',
            'acx_auto_attempts' => 3,
        ]);
        $wpdb->tableRows['wp_acx_sync_outbox'] = [$row];
        $syncState = $this->trackingSyncStateRepository();
        $service = new OutboxMaintenanceService(null, $syncState, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');

        $this->assertTrue($service->retry_failed_operation(81, $tenantId));
        $requeued = $wpdb->tableRows['wp_acx_sync_outbox'][0];
        $payload = json_decode((string) $requeued['payload'], true);
        $this->assertSame(OutboxStatus::PENDING, $requeued['status']);
        $this->assertIsArray($payload);
        $this->assertSame('cluster-81', $payload['cluster_uuid']);
        $this->assertArrayNotHasKey('acx_auto_attempts', $payload);

        // Model the next dispatch failure after the operator's clean requeue.
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['status'] = OutboxStatus::FAILED;
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['attempts'] = 1;
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['last_error_code'] = 'transport_error';
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['first_failed_at'] = gmdate('Y-m-d H:i:s', current_time('timestamp'));
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['payload'] = wp_json_encode($payload);

        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(1, $purged['retried']);
        $this->assertSame(0, $purged['dead_lettered']);
        $this->assertSame(OutboxStatus::PENDING, $wpdb->tableRows['wp_acx_sync_outbox'][0]['status']);
        $nextPayload = json_decode((string) $wpdb->tableRows['wp_acx_sync_outbox'][0]['payload'], true);
        $this->assertIsArray($nextPayload);
        $this->assertSame(1, $nextPayload['acx_auto_attempts']);
    }

    public function testBulkOperatorRetryUsesJsonRemoveAndResetsFutureAutoRetryWindow(): void
    {
        global $wpdb;

        $tenantId = 'tenant-bulk-operator-retry';
        $wpdb->defaultQueryResult = 0;
        $row = $this->buildFailedOutboxRow(91, $tenantId, 'transport_error');
        $row['payload'] = wp_json_encode([
            'cluster_uuid' => 'cluster-91',
            'acx_auto_attempts' => 3,
        ]);
        $wpdb->tableRows['wp_acx_sync_outbox'] = [$row];
        $syncState = $this->trackingSyncStateRepository();
        $service = new OutboxMaintenanceService(null, $syncState, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');

        $this->assertSame(1, $service->retry_failed_operations_bulk($tenantId));
        $bulkUpdate = $this->findQueryContaining($wpdb->queries, 'JSON_REMOVE(payload');
        $this->assertStringContainsString("payload = JSON_REMOVE(payload, '$.acx_auto_attempts')", $bulkUpdate);
        $this->assertSame(OutboxStatus::PENDING, $wpdb->tableRows['wp_acx_sync_outbox'][0]['status']);

        // Model the next dispatch failure with the marker removed by the SQL update.
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['status'] = OutboxStatus::FAILED;
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['attempts'] = 1;
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['last_error_code'] = 'transport_error';
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['first_failed_at'] = gmdate('Y-m-d H:i:s', current_time('timestamp'));
        $wpdb->tableRows['wp_acx_sync_outbox'][0]['payload'] = '{}';

        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(1, $purged['retried']);
        $this->assertSame(0, $purged['dead_lettered']);
        $this->assertSame(OutboxStatus::PENDING, $wpdb->tableRows['wp_acx_sync_outbox'][0]['status']);
    }

    public function testPurgeCountsZeroRowCasMissOnRetryAsSkippedConcurrent(): void
    {
        global $wpdb;

        $tenantId = 'tenant-cas-retry';
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildFailedOutboxRow(61, $tenantId, 'remote_error'),
        ];
        $wpdb->updateResultsByTable['wp_acx_sync_outbox'] = 0;

        $syncState = $this->trackingSyncStateRepository();
        $service = new OutboxMaintenanceService(null, $syncState, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(0, $purged['retried']);
        $this->assertSame(0, $purged['dead_lettered']);
        $this->assertSame(1, $purged['skipped_concurrent']);
        $this->assertSame(0, $syncState->refreshCount);
    }

    public function testPurgeCountsZeroRowCasMissOnExhaustionAsSkippedConcurrent(): void
    {
        global $wpdb;

        $tenantId = 'tenant-cas-exhaust';
        $row = $this->buildFailedOutboxRow(71, $tenantId, 'transport_error');
        $row['payload'] = wp_json_encode(['acx_auto_attempts' => 3]);
        $wpdb->tableRows['wp_acx_sync_outbox'] = [$row];
        $wpdb->updateResultsByTable['wp_acx_sync_outbox'] = 0;

        $syncState = $this->trackingSyncStateRepository();
        $service = new OutboxMaintenanceService(null, $syncState, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(0, $purged['retried']);
        $this->assertSame(0, $purged['dead_lettered']);
        $this->assertSame(1, $purged['skipped_concurrent']);
        $this->assertSame(0, $syncState->refreshCount);
    }

    public function testPurgeDoesNotCountCasSqlErrorAsTransition(): void
    {
        global $wpdb;

        $tenantId = 'tenant-cas-error';
        $wpdb->defaultQueryResult = 0;
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildFailedOutboxRow(72, $tenantId, 'transport_error'),
        ];
        $wpdb->updateResultsByTable['wp_acx_sync_outbox'] = false;

        $syncState = $this->trackingSyncStateRepository();
        $service = new OutboxMaintenanceService(null, $syncState, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(0, $purged['retried']);
        $this->assertSame(0, $purged['dead_lettered']);
        $this->assertSame(0, $purged['skipped_concurrent']);
        $this->assertSame(OutboxStatus::FAILED, $wpdb->tableRows['wp_acx_sync_outbox'][0]['status']);
        $this->assertSame(0, $syncState->refreshCount);
    }

    public function testHealthCountersExposePendingFailedDeadLetteredAndOldestAge(): void
    {
        global $wpdb;

        $tenantId = 'tenant-health-counters';
        $oldestCreated = gmdate('Y-m-d H:i:s', current_time('timestamp') - 7200);
        $wpdb->mockResults = [
            [
                'pending' => '1',
                'failed' => '1',
                'dead_lettered' => '2',
                'oldest_created_at' => $oldestCreated,
            ],
        ];

        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $counters = $service->get_health_counters($tenantId);

        $this->assertIsArray($counters);
        $this->assertSame(1, $counters['pending']);
        $this->assertSame(1, $counters['failed']);
        $this->assertSame(2, $counters['dead_lettered']);
        $this->assertSame(7200, $counters['oldest_age_seconds']);
        $healthQuery = $this->findQueryContaining($wpdb->queries, 'SUM(CASE');
        $this->assertStringContainsString('MIN(created_at)', $healthQuery);
        $this->assertStringNotContainsString('ORDER BY', $healthQuery);
    }

    public function testHealthCountersReturnFalseWhenQueryFails(): void
    {
        global $wpdb;

        $wpdb->get_results_returns_null = true;
        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');

        $this->assertFalse($service->get_health_counters('tenant-health-unavailable'));
    }

    /**
     * @return SyncStateRepository&object{refreshCount:int,lastTenantId:?string}
     */
    private function trackingSyncStateRepository(): SyncStateRepository
    {
        return new class() extends SyncStateRepository {
            public int $refreshCount = 0;
            public ?string $lastTenantId = null;

            public function refresh_curation_metrics(string $tenant_id): void
            {
                ++$this->refreshCount;
                $this->lastTenantId = $tenant_id;
            }
        };
    }

    /**
     * @return array<string,mixed>
     */
    private function buildFailedOutboxRow(int $id, string $tenantId, string $errorCode, ?string $failedAt = null): array
    {
        $stamp = $failedAt ?? '2026-09-16 00:00:00';

        return [
            'id' => $id,
            'tenant_id' => $tenantId,
            'status' => OutboxStatus::FAILED,
            'attempts' => 1,
            'last_error_code' => $errorCode,
            'last_error_message' => 'failed',
            'first_failed_at' => $stamp,
            'last_attempted_at' => $stamp,
            'created_at' => $stamp,
            'payload' => '{}',
            'next_attempt_at' => null,
        ];
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
}
