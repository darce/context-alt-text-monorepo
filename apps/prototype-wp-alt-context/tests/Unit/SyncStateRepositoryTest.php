<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\SyncStateRepository
 */
class SyncStateRepositoryTest extends TestCase
{
    private SyncStateRepository $repository;

    protected function setUp(): void
    {
        parent::setUp();
        $this->repository = new SyncStateRepository();
    }

    public function testUpsertSnapshotVersionUsesMonotonicQuery(): void
    {
        $this->repository->upsert_snapshot_version('tenant-sync', 42);

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);

        $this->assertStringContainsString('INSERT INTO `wp_acx_sync_state`', $sql);
        $this->assertStringContainsString('tenant:tenant-sync:clusters', $sql);
        $this->assertStringContainsString('GREATEST(last_snapshot_version, VALUES(last_snapshot_version))', $sql);
    }

    public function testGetSnapshotVersionReadsStoredValue(): void
    {
        global $wpdb;
        $wpdb->mockVar = '21';

        $value = $this->repository->get_snapshot_version('tenant-sync');

        $this->assertSame(21, $value);
    }

    public function testGetLastUpdatedReturnsTimestampString(): void
    {
        global $wpdb;
        $wpdb->mockVar = '2026-02-14 01:02:03';

        $value = $this->repository->get_last_updated('tenant-sync');

        $this->assertSame('2026-02-14 01:02:03', $value);
    }

    public function testGetLastUpdatedReturnsNullForEpochSentinel(): void
    {
        global $wpdb;
        $wpdb->mockVar = '1970-01-01 00:00:00';

        $value = $this->repository->get_last_updated('tenant-sync');

        $this->assertNull($value);
    }

    public function testGetLastSyncResultDefaultsToOkWhenMissing(): void
    {
        global $wpdb;
        $wpdb->mockVar = '';

        $value = $this->repository->get_last_sync_result('tenant-sync');

        $this->assertSame('ok', $value);
    }

    public function testSetLastSyncResultPersistsAttemptMetadata(): void
    {
        $this->repository->set_last_sync_result('tenant-sync', 'unreachable');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);

        $this->assertStringContainsString('INSERT INTO `wp_acx_sync_state` (stream_name, last_snapshot_version, last_sync_result, last_sync_attempted_at)', $sql);
        $this->assertStringContainsString("'tenant:tenant-sync:clusters'", $sql);
        $this->assertStringContainsString("'unreachable'", $sql);
        $this->assertStringContainsString('last_sync_attempted_at = VALUES(last_sync_attempted_at)', $sql);
        $this->assertStringNotContainsString('updated_at = VALUES(updated_at)', $sql);
    }

    public function testSetLastSyncResultPersistsUpdatedAtForSuccessfulSyncs(): void
    {
        $this->repository->set_last_sync_result('tenant-sync', 'ok');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);

        $this->assertStringContainsString('INSERT INTO `wp_acx_sync_state` (stream_name, last_snapshot_version, last_sync_result, last_sync_attempted_at, updated_at)', $sql);
        $this->assertStringContainsString("'tenant:tenant-sync:clusters'", $sql);
        $this->assertStringContainsString("'ok'", $sql);
        $this->assertStringContainsString('updated_at = VALUES(updated_at)', $sql);
    }

    public function testTouchLocalCurationMarkerBackdatesUpdatedAtToEpoch(): void
    {
        $this->repository->touch_local_curation_marker('tenant-sync');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);

        $this->assertStringContainsString('INSERT INTO `wp_acx_sync_state` (stream_name, last_snapshot_version, updated_at)', $sql);
        $this->assertStringContainsString("'tenant:tenant-sync:clusters'", $sql);
        $this->assertStringContainsString("'1970-01-01 00:00:00'", $sql);
        $this->assertStringContainsString('ON DUPLICATE KEY UPDATE updated_at = VALUES(updated_at)', $sql);
    }

    public function testRefreshCurationMetricsUpsertsCountersFromOutboxAndConflicts(): void
    {
        global $wpdb;
        $wpdb->mockVar = '3';

        $this->repository->refresh_curation_metrics('tenant-sync');

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('SELECT COUNT(*) FROM `wp_acx_sync_outbox`', $sql);
        $this->assertStringContainsString('SELECT COUNT(*) FROM `wp_acx_sync_conflicts`', $sql);
        $this->assertStringContainsString('INSERT INTO wp_acx_sync_state', $sql);
        $this->assertStringContainsString('pending_curation_operations', $sql);
        $this->assertStringContainsString('failed_curation_operations', $sql);
        $this->assertStringContainsString('conflict_count', $sql);
    }

    public function testRefreshCurationMetricsKeepsReplayPlaneCountsSeparateFromTopologyPlane(): void
    {
        global $wpdb;
        $wpdb->mockVar = '4';

        $this->repository->refresh_curation_metrics('tenant-sync');

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringNotContainsString('wp_acx_topology_commands', $sql);
    }

    public function testRefreshCurationMetricsPersistsMixedPendingFailedAndConflictTallies(): void
    {
        global $wpdb;
        $wpdb->mockRow = [
            'last_curation_acknowledged_at' => null,
            'last_curation_conflict_at' => null,
            'last_curation_failed_at' => null,
        ];

        $wpdb->queryResults[$wpdb->prepare(
            'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
            'wp_acx_sync_outbox',
            'tenant-sync',
            'pending'
        )] = 3;
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
            'wp_acx_sync_outbox',
            'tenant-sync',
            'failed'
        )] = 2;
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND resolution_status = %s',
            'wp_acx_sync_conflicts',
            'tenant-sync',
            'open'
        )] = 1;
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT MAX(acknowledged_at) FROM %i WHERE tenant_id = %s AND status = %s',
            'wp_acx_sync_outbox',
            'tenant-sync',
            'acknowledged'
        )] = '2026-03-10 09:00:00';
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT MAX(created_at) FROM %i WHERE tenant_id = %s AND resolution_status = %s',
            'wp_acx_sync_conflicts',
            'tenant-sync',
            'open'
        )] = '2026-03-10 09:05:00';
        $wpdb->queryResults[$wpdb->prepare(
            'SELECT MAX(last_attempted_at) FROM %i WHERE tenant_id = %s AND status = %s',
            'wp_acx_sync_outbox',
            'tenant-sync',
            'failed'
        )] = '2026-03-10 09:10:00';

        $this->repository->refresh_curation_metrics('tenant-sync');

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('UPDATE wp_acx_sync_state SET pending_curation_operations = 3', $sql);
        $this->assertStringContainsString('failed_curation_operations = 2', $sql);
        $this->assertStringContainsString('conflict_count = 1', $sql);
        $this->assertStringContainsString("last_curation_acknowledged_at = '2026-03-10 09:00:00'", $sql);
        $this->assertStringContainsString("last_curation_conflict_at = '2026-03-10 09:05:00'", $sql);
        $this->assertStringContainsString("last_curation_failed_at = '2026-03-10 09:10:00'", $sql);
    }

    public function testGetPendingCurationOperationsReadsStoredValue(): void
    {
        global $wpdb;
        $wpdb->mockVar = '7';

        $value = $this->repository->get_pending_curation_operations('tenant-sync');

        $this->assertSame(7, $value);
    }

    public function testGetConflictCountReadsStoredValue(): void
    {
        global $wpdb;
        $wpdb->mockVar = '2';

        $value = $this->repository->get_conflict_count('tenant-sync');

        $this->assertSame(2, $value);
    }

    public function testGetFailedCurationOperationsReadsStoredValue(): void
    {
        global $wpdb;
        $wpdb->mockVar = '5';

        $value = $this->repository->get_failed_curation_operations('tenant-sync');

        $this->assertSame(5, $value);
    }

    public function testGetLastCurationAcknowledgedAtReturnsTimestamp(): void
    {
        global $wpdb;
        $wpdb->mockVar = '2026-03-07 02:00:00';

        $value = $this->repository->get_last_curation_acknowledged_at('tenant-sync');

        $this->assertSame('2026-03-07 02:00:00', $value);
    }

    public function testGetLastCurationConflictAtReturnsNullWhenMissing(): void
    {
        global $wpdb;
        $wpdb->mockVar = '';

        $value = $this->repository->get_last_curation_conflict_at('tenant-sync');

        $this->assertNull($value);
    }

    public function testGetLastCurationFailedAtReturnsTimestamp(): void
    {
        global $wpdb;
        $wpdb->mockVar = '2026-03-07 03:00:00';

        $value = $this->repository->get_last_curation_failed_at('tenant-sync');

        $this->assertSame('2026-03-07 03:00:00', $value);
    }

    public function testTopologyCommandStatusReadersQueryTopologyTable(): void
    {
        global $wpdb;
        $wpdb->mockVar = '6';

        $this->assertSame(6, $this->repository->get_pending_topology_commands('tenant-sync'));
        $this->assertSame(6, $this->repository->get_applied_topology_commands('tenant-sync'));
        $this->assertSame(6, $this->repository->get_failed_topology_commands('tenant-sync'));
        $this->assertSame(6, $this->repository->get_conflicted_topology_commands('tenant-sync'));

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString("FROM `wp_acx_topology_commands` WHERE tenant_id = 'tenant-sync' AND status IN ('pending', 'dispatched')", $sql);
        $this->assertStringContainsString("FROM `wp_acx_topology_commands` WHERE tenant_id = 'tenant-sync' AND status IN ('applied')", $sql);
        $this->assertStringContainsString("FROM `wp_acx_topology_commands` WHERE tenant_id = 'tenant-sync' AND status IN ('failed')", $sql);
        $this->assertStringContainsString("FROM `wp_acx_topology_commands` WHERE tenant_id = 'tenant-sync' AND status IN ('conflict')", $sql);
    }

    public function testGetLastTopologyReconciledAtReturnsTimestamp(): void
    {
        global $wpdb;
        $wpdb->mockVar = '2026-03-07 04:00:00';

        $value = $this->repository->get_last_topology_reconciled_at('tenant-sync');

        $this->assertSame('2026-03-07 04:00:00', $value);
    }

    /**
     * R23-BR-23 [TEST-15]: a durable last_sync_result write error (query === false)
     * must throw naming the field — not silently leave the SPA on a green stale
     * value. Distinct from the 0/no-op leg below.
     *
     * Uses expectException (not try/catch RuntimeException): PHPUnit's fail() is
     * itself a RuntimeException subclass, so a try/catch pin would swallow the
     * fail() and pass tautologically when the throw is removed.
     */
    public function testSetLastSyncResultThrowsOnWriteError(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = false;

        $this->expectException(\RuntimeException::class);
        $this->expectExceptionMessage('Could not persist last_sync_result (write error).');
        $this->repository->set_last_sync_result('tenant-sync', 'ok');
    }

    /**
     * R23-BR-23 false-failure pin: identical re-apply of last_sync_result
     * (query returns 0, not false) must still succeed. A check that treats
     * 0 as failure would false-fail every no-op re-apply.
     */
    public function testSetLastSyncResultSucceedsOnNoOpZeroRowsAffected(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 0;

        $this->repository->set_last_sync_result('tenant-sync', 'ok');

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString("'ok'", $sql);
        $this->assertStringContainsString('last_sync_result', $sql);
    }

    /**
     * R23-BR-23: resync_required written by rekey must not be normalized to ok.
     * A mutation that restores the old default-to-ok path reds this pin.
     */
    public function testGetLastSyncResultPreservesResyncRequired(): void
    {
        global $wpdb;
        $wpdb->mockVar = 'resync_required';

        $value = $this->repository->get_last_sync_result('tenant-sync');

        $this->assertSame('resync_required', $value);
    }

    /**
     * R23-BR-23: unknown non-empty status fails closed to failed (does not invent ok).
     */
    public function testGetLastSyncResultFailsClosedOnUnknownStatus(): void
    {
        global $wpdb;
        $wpdb->mockVar = 'not-a-real-status';

        $value = $this->repository->get_last_sync_result('tenant-sync');

        $this->assertSame('failed', $value);
    }

    /**
     * R23-BR-23 [TEST-15]: metrics update write error (false) throws and names
     * the counter fields. Distinct from the 0/no-op leg.
     * expectException — not try/catch RuntimeException (fail() is RuntimeException).
     */
    public function testRefreshCurationMetricsThrowsOnUpdateWriteError(): void
    {
        global $wpdb;
        $wpdb->mockRow = [
            'last_curation_acknowledged_at' => null,
            'last_curation_conflict_at' => null,
            'last_curation_failed_at' => null,
        ];
        $wpdb->defaultUpdateResult = false;

        $this->expectException(\RuntimeException::class);
        $this->expectExceptionMessage('update write error on pending_curation_operations');
        $this->repository->refresh_curation_metrics('tenant-sync');
    }

    /**
     * R23-BR-23 [TEST-15]: metrics update returning 0 (no-op / identical values)
     * must still succeed. A mutation that treats 0 like false reds this pin
     * without needing the false-leg pin above to fail first.
     */
    public function testRefreshCurationMetricsSucceedsOnUpdateZeroRowsAffected(): void
    {
        global $wpdb;
        $wpdb->mockRow = [
            'last_curation_acknowledged_at' => null,
            'last_curation_conflict_at' => null,
            'last_curation_failed_at' => null,
        ];
        $wpdb->defaultUpdateResult = 0;

        $this->repository->refresh_curation_metrics('tenant-sync');

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('UPDATE wp_acx_sync_state SET pending_curation_operations', $sql);
    }

    /**
     * R23-BR-23 [TEST-15]: metrics insert write error throws naming the fields.
     * expectException — not try/catch RuntimeException (fail() is RuntimeException).
     */
    public function testRefreshCurationMetricsThrowsOnInsertWriteError(): void
    {
        global $wpdb;
        $wpdb->mockRow = null;
        $wpdb->defaultInsertResult = false;

        $this->expectException(\RuntimeException::class);
        $this->expectExceptionMessage('insert write error on pending_curation_operations');
        $this->repository->refresh_curation_metrics('tenant-sync');
    }
}
