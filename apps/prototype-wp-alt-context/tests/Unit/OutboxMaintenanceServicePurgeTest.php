<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\OutboxMaintenanceService;
use AltContext\Tests\TestCase;

class OutboxMaintenanceServicePurgeTest extends TestCase
{
    public function testPurgeTerminalRowsDeletesAcknowledgedOutboxOlderThanRetentionWindow(): void
    {
        global $wpdb;

        $tenantId = 'tenant-purge-1';
        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', new ConflictRepository('wp_acx_sync_conflicts'));

        $purged = $service->purge_terminal_rows($tenantId);

        $deleteQuery = $this->findQueryContaining($wpdb->queries, 'DELETE FROM wp_acx_sync_outbox');
        $this->assertStringContainsString("status = 'acknowledged'", $deleteQuery);
        $this->assertGreaterThanOrEqual(1, $purged['outbox']);
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
    }

    public function testPurgeTerminalRowsDeletesResolvedConflictsOlderThanRetentionWindow(): void
    {
        global $wpdb;

        $tenantId = 'tenant-purge-2';
        $service = new OutboxMaintenanceService(null, null, 'wp_acx_sync_outbox', new ConflictRepository('wp_acx_sync_conflicts'));

        $purged = $service->purge_terminal_rows($tenantId);

        $deleteQuery = $this->findQueryContaining($wpdb->queries, 'DELETE FROM wp_acx_sync_conflicts');
        $this->assertStringContainsString("resolution_status <> 'open'", $deleteQuery);
        $this->assertGreaterThanOrEqual(1, $purged['conflicts']);
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