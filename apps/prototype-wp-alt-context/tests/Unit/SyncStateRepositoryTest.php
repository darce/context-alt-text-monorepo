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
}
