<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\SyncStatusController;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\SyncStatusController
 */
class SyncStatusControllerTest extends TestCase
{
    public function testGetSyncStatusReturnsSnapshotMetadata(): void
    {
        $syncRepo = new class() extends NullSyncStateRepository {
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
        $this->assertSame(0, $data['pending_curation_operations']);
        $this->assertSame(0, $data['conflict_count']);
        $this->assertNull($data['last_curation_acknowledged_at']);
        $this->assertNull($data['last_curation_conflict_at']);
    }

    public function testGetSyncStatusIncludesCurationCountersWhenAvailable(): void
    {
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 9;
            }
            public function get_last_updated(string $tenant_id): ?string {
                return '2026-02-14 00:00:00';
            }
            public function get_pending_curation_operations(string $tenant_id): int {
                return 4;
            }
            public function get_conflict_count(string $tenant_id): int {
                return 2;
            }
            public function get_last_curation_acknowledged_at(string $tenant_id): ?string {
                return '2026-03-07 02:00:00';
            }
            public function get_last_curation_conflict_at(string $tenant_id): ?string {
                return '2026-03-07 02:30:00';
            }
        };

        $controller = new SyncStatusController($syncRepo);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/sync-status');
        $response = $controller->get_sync_status($request);

        $data = $response->get_data();
        $this->assertSame(4, $data['pending_curation_operations']);
        $this->assertSame(2, $data['conflict_count']);
        $this->assertSame('2026-03-07 02:00:00', $data['last_curation_acknowledged_at']);
        $this->assertSame('2026-03-07 02:30:00', $data['last_curation_conflict_at']);
    }

    public function testGetSyncStatusReturnsStaleTrueWhenOld(): void
    {
        // Mock a timestamp older than 1 hour (default threshold)
        $oldTimestamp = gmdate('Y-m-d H:i:s', time() - 7200); // 2 hours ago

        $syncRepo = new class($oldTimestamp) extends NullSyncStateRepository {
            private string $timestamp;
            public function __construct(string $timestamp) {
					$this->timestamp = $timestamp; }
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

        $syncRepo = new class($recentTimestamp) extends NullSyncStateRepository {
            private string $timestamp;
            public function __construct(string $timestamp) {
					$this->timestamp = $timestamp; }
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
        $syncRepo = new class() extends NullSyncStateRepository {
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

    public function testTriggerSyncBuildsLazySyncJobWhenNoSyncPullJobInjected(): void
    {
          $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
				return 0; }
            public function get_last_updated(string $tenant_id): ?string {
				return null; }
		  };

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '"invalid"',
        ]);

        $controller = new SyncStatusController($syncRepo, null);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertFalse($data['synced']);
        $this->assertSame('sync_failed', $data['reason']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/tenants/', $calls[0]['url']);
    }

    public function testTriggerSyncReturnsSyncedTrueOnSuccess(): void
    {
        $recentTimestamp = gmdate('Y-m-d H:i:s', time() - 10);

          $syncRepo = new class($recentTimestamp) extends NullSyncStateRepository {
            private string $timestamp;
            public function __construct(string $timestamp) {
				$this->timestamp = $timestamp; }
            public function get_snapshot_version(string $tenant_id): int {
				return 3; }
            public function get_last_updated(string $tenant_id): ?string {
				return $this->timestamp; }
		  };

        $syncJob = new class() implements SyncPullJobInterface {
            public function perform(string $tenant_id): bool {
				return true; }
            public function perform_bypass_cooldown(string $tenant_id): bool {
				return true; }
        };

        $controller = new SyncStatusController($syncRepo, $syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertTrue($data['synced']);
        $this->assertSame('ok', $data['reason']);
        $this->assertSame(3, $data['last_snapshot_version']);
        $this->assertSame($recentTimestamp, $data['last_synced_at']);
        $this->assertFalse($data['is_stale']);
    }

    public function testTriggerSyncReturnsSyncedFalseOnFailure(): void
    {
          $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
				return 0; }
            public function get_last_updated(string $tenant_id): ?string {
				return null; }
		  };

        $syncJob = new class() implements SyncPullJobInterface {
            public function perform(string $tenant_id): bool {
				return false; }
            public function perform_bypass_cooldown(string $tenant_id): bool {
				return false; }
        };

        $controller = new SyncStatusController($syncRepo, $syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertFalse($data['synced']);
        $this->assertSame('sync_failed', $data['reason']);
        $this->assertTrue($data['is_stale']);
    }

    public function testTriggerSyncHandlesExceptionGracefully(): void
    {
          $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
				return 0; }
            public function get_last_updated(string $tenant_id): ?string {
				return null; }
		  };

        $syncJob = new class() implements SyncPullJobInterface {
            public function perform(string $tenant_id): bool {
				return false; }
            public function perform_bypass_cooldown(string $tenant_id): bool {
                throw new \RuntimeException('Connection refused');
            }
        };

        $controller = new SyncStatusController($syncRepo, $syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertFalse($data['synced']);
        $this->assertSame('sync_failed', $data['reason']);
    }

    public function testTriggerSyncReturnsNoRemoteDataReasonOnEmptyTenant(): void
    {
          $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
				return 0; }
            public function get_last_updated(string $tenant_id): ?string {
				return null; }
		  };

        $syncJob = new class() implements SyncPullJobInterface {
            public function perform(string $tenant_id): bool {
				return true; }
            public function perform_bypass_cooldown(string $tenant_id): bool {
				return true; }
        };

        $controller = new SyncStatusController($syncRepo, $syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertTrue($data['synced']);
        $this->assertSame('no_remote_data', $data['reason']);
        $this->assertSame(0, $data['last_snapshot_version']);
    }
}
