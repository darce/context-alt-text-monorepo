<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Tests\TestCase;

class OutboxQueryRepositoryTest extends TestCase
{
    public function testFindFailedOperationsReturnsDecodedRowsOrderedByDate(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $rows = [
            [
                'id' => 12,
                'tenant_id' => $tenantId,
                'operation_type' => 'cluster_label_updated',
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-2',
                'status' => 'failed',
                'attempts' => 5,
                'expected_base_version' => 8,
                'local_revision' => 3,
                'last_error_code' => 'dispatch_failed',
                'last_error_message' => 'newer failure',
                'payload' => '{"cluster_uuid":"cluster-2"}',
                'created_at' => '2026-03-10 12:05:00',
                'last_attempted_at' => '2026-03-10 12:06:00',
                'acknowledged_at' => null,
            ],
            [
                'id' => 11,
                'tenant_id' => $tenantId,
                'operation_type' => 'cluster_dismissed',
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-1',
                'status' => 'failed',
                'attempts' => 4,
                'expected_base_version' => 7,
                'local_revision' => 2,
                'last_error_code' => 'remote_error',
                'last_error_message' => 'older failure',
                'payload' => '{"cluster_uuid":"cluster-1"}',
                'created_at' => '2026-03-10 12:00:00',
                'last_attempted_at' => '2026-03-10 12:01:00',
                'acknowledged_at' => null,
            ],
        ];

        $wpdb->mockResults = $rows;

        $repository = new OutboxQueryRepository();
        $result = $repository->find_operations_by_status($tenantId, 'failed', 50, 0);

        $this->assertSame([12, 11], array_column($result, 'id'));
        $this->assertSame(['cluster_uuid' => 'cluster-2'], $result[0]['payload']);
        $this->assertSame('dispatch_failed', $result[0]['last_error_code']);
    }

    public function testReclaimStaleInFlightOperationsResetsLeaseExpiredRowsToPending(): void
    {
        // CON-3-FU-1: a drain that dies between claim_operation (pending->in_flight) and
        // apply_result orphans the row in_flight forever — load_pending_operations only sees
        // 'pending', so the stuck row is never reprocessed. A lease-expiry reclaim returns
        // in_flight rows whose claim is older than the lease back to 'pending'. Mirrors the
        // topology drain's claimed_at lease-reclaim; a freshly-claimed row (claimed_at = NOW)
        // is excluded by the lease window so a peer drain mid-flight is not disturbed.
        global $wpdb;
        $wpdb->defaultQueryResult = 2;

        $repository = new OutboxQueryRepository('wp_acx_sync_outbox');
        $reclaimed = $repository->reclaim_stale_in_flight_operations(300);

        $this->assertSame(2, $reclaimed);

        $matched = array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_contains($query, 'acx_sync_outbox')
                && str_contains($query, "SET status = 'pending', claimed_at = NULL")
                && str_contains($query, "WHERE status = 'in_flight'")
                && str_contains($query, 'DATE_SUB( NOW(), INTERVAL 300 SECOND )')
        );
        $this->assertNotEmpty($matched, 'Expected a lease-gated reclaim UPDATE returning stale in_flight rows to pending.');
    }
}
