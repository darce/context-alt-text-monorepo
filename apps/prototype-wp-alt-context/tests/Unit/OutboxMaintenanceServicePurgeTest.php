<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

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
    }

    public function testPurgeTerminalRowsDeletesOldNonRetryableFailedRows(): void
    {
        global $wpdb;

        $tenantId = 'tenant-purge-failed';
        $wpdb->defaultQueryResult = 0;
        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');

        $purged = $service->purge_terminal_rows($tenantId);

        $deleteQuery = $this->findQueryContaining($wpdb->queries, 'last_error_code IN');
        $this->assertStringContainsString('DELETE FROM `wp_acx_sync_outbox`', $deleteQuery);
        $this->assertStringContainsString("status = '" . OutboxStatus::FAILED . "'", $deleteQuery);
        $this->assertStringContainsString("'invalid_payload'", $deleteQuery);
        $this->assertStringContainsString("'unauthorized'", $deleteQuery);
        $expectedCutoff = gmdate('Y-m-d H:i:s', current_time('timestamp') - (7 * 86400));
        $this->assertStringContainsString(substr($expectedCutoff, 0, 10), $deleteQuery);
        $this->assertIsArray($purged);
        $this->assertSame(0, $purged['retried']);
        $this->assertSame(0, $purged['dead_lettered']);
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

        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(0, $purged['retried']);
        $this->assertSame(1, $purged['dead_lettered']);
        $updated = $wpdb->tableRows['wp_acx_sync_outbox'][0];
        $this->assertSame(OutboxStatus::DISCARDED, $updated['status']);
        $this->assertSame('auto_retry_exhausted', $updated['last_error_code']);
        $this->assertStringContainsString('age 3600 seconds', (string) $updated['last_error_message']);
    }

    public function testHealthCountersExposePendingFailedDeadLetteredAndOldestAge(): void
    {
        global $wpdb;

        $tenantId = 'tenant-health-counters';
        $this->configureSyncMetricQueries($tenantId, [
            'pending' => 4,
            'failed' => 2,
            'conflicts' => 0,
        ]);
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
            'wp_acx_sync_outbox',
            $tenantId,
            OutboxStatus::DISCARDED
        )] = 3;
        $wpdb->mockRow = null;

        $oldestCreated = gmdate('Y-m-d H:i:s', current_time('timestamp') - 7200);
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            [
                'id' => 31,
                'tenant_id' => $tenantId,
                'status' => OutboxStatus::FAILED,
                'created_at' => $oldestCreated,
            ],
            [
                'id' => 32,
                'tenant_id' => $tenantId,
                'status' => OutboxStatus::PENDING,
                'created_at' => gmdate('Y-m-d H:i:s', current_time('timestamp') - 60),
            ],
        ];

        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', 'wp_acx_sync_conflicts');
        $counters = $service->get_health_counters($tenantId);

        $this->assertSame(4, $counters['pending']);
        $this->assertSame(2, $counters['failed']);
        $this->assertSame(3, $counters['dead_lettered']);
        $this->assertSame(7200, $counters['oldest_age_seconds']);
    }

    /**
     * @return array<string,mixed>
     */
    private function buildFailedOutboxRow(int $id, string $tenantId, string $errorCode): array
    {
        return [
            'id' => $id,
            'tenant_id' => $tenantId,
            'status' => OutboxStatus::FAILED,
            'attempts' => 1,
            'last_error_code' => $errorCode,
            'last_error_message' => 'failed',
            'first_failed_at' => '2026-09-16 00:00:00',
            'last_attempted_at' => '2026-09-16 00:00:00',
            'created_at' => '2026-09-16 00:00:00',
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
