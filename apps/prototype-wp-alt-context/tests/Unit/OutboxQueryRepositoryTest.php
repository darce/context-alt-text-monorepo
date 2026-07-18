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

    public function testFindFailedOperationIdsReturnsTenantScopedFailedIdsOldestFirst(): void
    {
        // E15-35 Slice 2: bulk requeue reads its failed-id set through this query — it must
        // scope to the tenant, match only failed rows, and order oldest-first (id ASC) so the
        // paced next_attempt_at spread is deterministic.
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            ['id' => 5, 'tenant_id' => $tenantId, 'status' => 'failed'],
            ['id' => 2, 'tenant_id' => $tenantId, 'status' => 'failed'],
            ['id' => 3, 'tenant_id' => $tenantId, 'status' => 'pending'],
            ['id' => 4, 'tenant_id' => 'tenant-other', 'status' => 'failed'],
        ];

        $repository = new OutboxQueryRepository('wp_acx_sync_outbox');
        $this->assertSame([2, 5], $repository->find_failed_operation_ids($tenantId, 1000));
    }

    public function testFindFailedOperationIdsHonorsLimitAndRejectsBlankTenant(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            ['id' => 1, 'tenant_id' => $tenantId, 'status' => 'failed'],
            ['id' => 2, 'tenant_id' => $tenantId, 'status' => 'failed'],
            ['id' => 3, 'tenant_id' => $tenantId, 'status' => 'failed'],
        ];

        $repository = new OutboxQueryRepository('wp_acx_sync_outbox');
        $this->assertSame([1, 2], $repository->find_failed_operation_ids($tenantId, 2));
        $this->assertSame([], $repository->find_failed_operation_ids('   ', 1000));
    }

    public function testLoadPendingOperationsGatesClaimOnElapsedNextAttemptAndProjectsRetryColumns(): void
    {
        // E15-35 Slice 1 (PR-09): the claim SELECT must skip rows whose next_attempt_at has not
        // elapsed AND project first_failed_at/next_attempt_at — apply_result() operates only on
        // the row array this SELECT returns, so the window-age decision needs the values read out.
        global $wpdb;

        $repository = new OutboxQueryRepository('wp_acx_sync_outbox');
        $repository->load_pending_operations(25);

        $matched = array_values(array_filter(
            $wpdb->queries,
            static fn (string $query): bool => str_contains($query, 'acx_sync_outbox')
                && str_contains($query, "status = 'pending'")
        ));
        $this->assertNotEmpty($matched, 'Expected a pending-claim SELECT.');
        $select = $matched[0];
        $this->assertStringContainsString("( next_attempt_at IS NULL OR next_attempt_at <= '", $select);
        $this->assertStringContainsString('first_failed_at', $select);
        $this->assertStringContainsString('next_attempt_at', $select);
    }

    public function testEarliestPendingAttemptTimeReturnsMinCoalescedSchedule(): void
    {
        // E15-35 Slice 1: the drain reschedules itself for the earliest pending attempt; rows with
        // NULL next_attempt_at are due immediately (coalesce to created_at).
        global $wpdb;

        $earliest = '2026-07-16 10:00:00';
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT MIN(COALESCE(next_attempt_at, created_at)) FROM %i WHERE status = %s',
            'wp_acx_sync_outbox',
            'pending'
        )] = $earliest;

        $repository = new OutboxQueryRepository('wp_acx_sync_outbox');
        $this->assertSame($earliest, $repository->earliest_pending_attempt_time());
    }

    public function testReclaimStaleInFlightOperationsResetsLeaseExpiredRowsToPending(): void
    {
        // CON-3-FU-1: a drain that dies between claim_operation (pending->in_flight) and
        // apply_result orphans the row in_flight forever — load_pending_operations only sees
        // 'pending', so the stuck row is never reprocessed. A lease-expiry reclaim returns
        // in_flight rows whose claim is older than the lease back to 'pending'. A freshly-claimed
        // row is excluded by the lease window so a peer drain mid-flight is not disturbed.
        //
        // CON-3-FU-REV-A1 regression: the lease cutoff MUST use the WP clock current_time('mysql')
        // — the same clock claim_operation writes claimed_at with — not MySQL NOW(). A bound,
        // quoted timestamp cutoff (DATE_SUB( 'Y-m-d H:i:s', ... )) proves both sides share the WP
        // clock; a bare DATE_SUB( NOW(), ... ) would reintroduce the site-vs-DB tz mismatch that
        // silently no-ops or mis-fires the reclaim.
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
                && str_contains($query, "DATE_SUB( '")
                && str_contains($query, 'INTERVAL 300 SECOND )')
                && ! str_contains($query, 'DATE_SUB( NOW(')
        );
        $this->assertNotEmpty($matched, 'Expected a lease-gated reclaim UPDATE whose cutoff is the WP clock (current_time), not MySQL NOW().');
    }
}
