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
