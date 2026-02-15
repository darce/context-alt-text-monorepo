<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\SyncStatusController;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\SyncStatusController
 */
class SyncStatusControllerTest extends TestCase
{
    public function testGetSyncStatusReturnsSnapshotMetadata(): void
    {
        $syncRepo = new class() implements SyncStateRepositoryInterface {
            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void {}
            public function get_snapshot_version(string $tenant_id): int {
				return 12; }
            public function get_last_updated(string $tenant_id): ?string {
				return '2026-02-14 00:00:00'; }
        };

        $controller = new SyncStatusController($syncRepo);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/sync-status');
        $response = $controller->get_sync_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame(12, $data['last_snapshot_version']);
        $this->assertSame('2026-02-14 00:00:00', $data['last_synced_at']);
    }

    public function testGetSyncStatusReturnsStaleTrueWhenOld(): void
    {
        // Mock a timestamp older than 1 hour (default threshold)
        $oldTimestamp = gmdate('Y-m-d H:i:s', time() - 7200); // 2 hours ago

        $syncRepo = new class($oldTimestamp) implements SyncStateRepositoryInterface {
            private string $timestamp;
            public function __construct(string $timestamp) {
				$this->timestamp = $timestamp; }
            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void {}
            public function get_snapshot_version(string $tenant_id): int {
				return 5; }
            public function get_last_updated(string $tenant_id): ?string {
				return $this->timestamp; }
        };

        $controller = new SyncStatusController($syncRepo);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/sync-status');
        $response = $controller->get_sync_status($request);

        $data = $response->get_data();
        $this->assertTrue($data['is_stale'], 'Projection should be stale when updated_at is older than threshold');
    }

    public function testGetSyncStatusReturnsStaleFalseWhenRecent(): void
    {
        // Mock a recent timestamp within the 1-hour threshold
        $recentTimestamp = gmdate('Y-m-d H:i:s', time() - 300); // 5 minutes ago

        $syncRepo = new class($recentTimestamp) implements SyncStateRepositoryInterface {
            private string $timestamp;
            public function __construct(string $timestamp) {
				$this->timestamp = $timestamp; }
            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void {}
            public function get_snapshot_version(string $tenant_id): int {
				return 5; }
            public function get_last_updated(string $tenant_id): ?string {
				return $this->timestamp; }
        };

        $controller = new SyncStatusController($syncRepo);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/sync-status');
        $response = $controller->get_sync_status($request);

        $data = $response->get_data();
        $this->assertFalse($data['is_stale'], 'Projection should not be stale when updated_at is recent');
    }

    public function testGetSyncStatusReturnsStaleTrueWhenNullTimestamp(): void
    {
        $syncRepo = new class() implements SyncStateRepositoryInterface {
            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void {}
            public function get_snapshot_version(string $tenant_id): int {
				return 0; }
            public function get_last_updated(string $tenant_id): ?string {
				return null; }
        };

        $controller = new SyncStatusController($syncRepo);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/sync-status');
        $response = $controller->get_sync_status($request);

        $data = $response->get_data();
        $this->assertTrue($data['is_stale'], 'Projection should be stale when updated_at is null');
    }
}
