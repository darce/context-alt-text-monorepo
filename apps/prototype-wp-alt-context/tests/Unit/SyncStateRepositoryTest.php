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
        $this->assertStringContainsString('conflict_count', $sql);
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
}
