<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\SyncStatusController;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
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
					return gmdate('Y-m-d H:i:s', time() - 60); }
        };

        $controller = new SyncStatusController($syncRepo);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/sync-status');
        $response = $controller->get_sync_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame(12, $data['last_snapshot_version']);
        $this->assertIsString($data['last_synced_at']);
        $this->assertSame('delta', $data['sync_mode']);
        $this->assertSame('healthy', $data['sync_health']);
        $this->assertSame('ok', $data['last_sync_result']);
        $this->assertSame(0, $data['pending_curation_operations']);
        $this->assertSame(0, $data['failed_curation_operations']);
        $this->assertSame(0, $data['conflict_count']);
        $this->assertNull($data['last_curation_acknowledged_at']);
        $this->assertNull($data['last_curation_conflict_at']);
        $this->assertNull($data['last_curation_failed_at']);
        $this->assertSame(
            [
                'pending' => 0,
                'applied' => 0,
                'failed' => 0,
                'conflict' => 0,
                'last_reconciled_at' => null,
            ],
            $data['topology_commands']
        );
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
            public function get_failed_curation_operations(string $tenant_id): int {
                return 1;
            }
            public function get_last_curation_acknowledged_at(string $tenant_id): ?string {
                return '2026-03-07 02:00:00';
            }
            public function get_last_curation_conflict_at(string $tenant_id): ?string {
                return '2026-03-07 02:30:00';
            }
            public function get_last_curation_failed_at(string $tenant_id): ?string {
                return '2026-03-07 03:00:00';
            }
            public function get_pending_topology_commands(string $tenant_id): int {
                return 2;
            }
            public function get_applied_topology_commands(string $tenant_id): int {
                return 1;
            }
            public function get_failed_topology_commands(string $tenant_id): int {
                return 1;
            }
            public function get_conflicted_topology_commands(string $tenant_id): int {
                return 1;
            }
            public function get_last_topology_reconciled_at(string $tenant_id): ?string {
                return '2026-03-07 04:00:00';
            }
        };

        $controller = new SyncStatusController($syncRepo);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/sync-status');
        $response = $controller->get_sync_status($request);

        $data = $response->get_data();
        $this->assertSame('failures', $data['sync_health']);
        $this->assertSame('ok', $data['last_sync_result']);
        $this->assertSame(4, $data['pending_curation_operations']);
        $this->assertSame(1, $data['failed_curation_operations']);
        $this->assertSame(2, $data['conflict_count']);
        $this->assertSame('2026-03-07 02:00:00', $data['last_curation_acknowledged_at']);
        $this->assertSame('2026-03-07 02:30:00', $data['last_curation_conflict_at']);
        $this->assertSame('2026-03-07 03:00:00', $data['last_curation_failed_at']);
        $this->assertSame(
            [
                'pending' => 2,
                'applied' => 1,
                'failed' => 1,
                'conflict' => 1,
                'last_reconciled_at' => '2026-03-07 04:00:00',
            ],
            $data['topology_commands']
        );
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
        $this->assertSame('stale', $data['sync_health']);
        $this->assertTrue($data['is_stale'], 'Projection should be stale when updated_at is older than threshold');
        $this->assertSame('delta', $data['sync_mode']);
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
        $this->assertSame('healthy', $data['sync_health']);
        $this->assertFalse($data['is_stale'], 'Projection should not be stale when updated_at is recent');
        $this->assertSame('delta', $data['sync_mode']);
    }

    public function testGetSyncStatusReturnsQueuedWhenPendingOperationsExist(): void
    {
        $recentTimestamp = gmdate('Y-m-d H:i:s', time() - 300);

        $syncRepo = new class($recentTimestamp) extends NullSyncStateRepository {
            private string $timestamp;

            public function __construct(string $timestamp) {
                $this->timestamp = $timestamp;
            }

            public function get_snapshot_version(string $tenant_id): int {
                return 6;
            }

            public function get_last_updated(string $tenant_id): ?string {
                return $this->timestamp;
            }

            public function get_pending_curation_operations(string $tenant_id): int {
                return 3;
            }
        };

        $controller = new SyncStatusController($syncRepo);
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/sync-status');
        $response = $controller->get_sync_status($request);

        $data = $response->get_data();
        $this->assertSame('queued', $data['sync_health']);
        $this->assertFalse($data['is_stale']);
        $this->assertSame(3, $data['pending_curation_operations']);
        $this->assertSame(0, $data['failed_curation_operations']);
        $this->assertSame(0, $data['conflict_count']);
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
        $this->assertSame('stale', $data['sync_health']);
        $this->assertTrue($data['is_stale'], 'Projection should be stale when updated_at is null');
        $this->assertSame('full', $data['sync_mode']);
    }

    public function testTriggerSyncBuildsLazySyncJobWhenNoSyncPullJobInjected(): void
    {
          $syncRepo = new class() extends NullSyncStateRepository {
            private string $lastSyncResult = 'ok';

            public function get_snapshot_version(string $tenant_id): int {
				return 0; }
            public function get_last_updated(string $tenant_id): ?string {
				return null; }
            public function get_last_sync_result(string $tenant_id): string {
                return $this->lastSyncResult;
            }
            public function set_last_sync_result(string $tenant_id, string $result): void {
                $this->lastSyncResult = $result;
            }
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
        $this->assertSame('offline', $data['sync_health']);
        $this->assertSame('unreachable', $data['last_sync_result']);

        $calls = $this->getHttpCalls();
        $this->assertCount(2, $calls);
        $this->assertStringContainsString('/recognition/tenants/', $calls[0]['url']);
        $this->assertStringContainsString('/clusters/delta', $calls[0]['url']);
        $this->assertStringContainsString('/clusters/snapshot', $calls[1]['url']);
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
            public function perform(string $tenant_id): SyncPullResult {
				return SyncPullResult::ok(); }
            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult {
				return SyncPullResult::ok(); }
            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult {
				return SyncPullResult::ok(); }
        };

        $controller = new SyncStatusController($syncRepo, $syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertTrue($data['synced']);
        $this->assertSame('ok', $data['reason']);
        $this->assertSame('healthy', $data['sync_health']);
        $this->assertSame('ok', $data['last_sync_result']);
        $this->assertSame('delta', $data['sync_mode']);
        $this->assertSame(3, $data['last_snapshot_version']);
        $this->assertSame($recentTimestamp, $data['last_synced_at']);
        $this->assertFalse($data['is_stale']);
    }

    public function testTriggerSyncReturnsUpdatedConflictCountAfterProjection(): void
    {
        $recentTimestamp = gmdate('Y-m-d H:i:s', time() - 10);

        $syncRepo = new class($recentTimestamp) extends NullSyncStateRepository {
            private string $timestamp;
            private int $conflictCount = 0;

            public function __construct(string $timestamp) {
                $this->timestamp = $timestamp;
            }

            public function get_snapshot_version(string $tenant_id): int {
                return 7;
            }

            public function get_last_updated(string $tenant_id): ?string {
                return $this->timestamp;
            }

            public function get_conflict_count(string $tenant_id): int {
                return $this->conflictCount;
            }

            public function setConflictCount(int $conflictCount): void {
                $this->conflictCount = $conflictCount;
            }
        };

        $syncJob = new class($syncRepo) implements SyncPullJobInterface {
            private object $syncRepo;

            public function __construct(object $syncRepo) {
                $this->syncRepo = $syncRepo;
            }

            public function perform(string $tenant_id): SyncPullResult {
                return $this->perform_bypass_cooldown($tenant_id);
            }

            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult {
                $this->syncRepo->setConflictCount(3);
                return SyncPullResult::ok();
            }

            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult {
                return $this->perform_bypass_cooldown($tenant_id);
            }
        };

        $controller = new SyncStatusController($syncRepo, $syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertTrue($data['synced']);
        $this->assertSame('conflicts', $data['sync_health']);
        $this->assertSame(3, $data['conflict_count']);
        $this->assertSame($recentTimestamp, $data['last_synced_at']);
        $this->assertSame(0, $data['topology_commands']['pending']);
    }

    public function testTriggerSyncReturnsSyncedFalseOnFailure(): void
    {
          $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
				return 0; }
            public function get_last_updated(string $tenant_id): ?string {
				return null; }
            public function get_last_sync_result(string $tenant_id): string {
                return 'failed';
            }
		  };

        $syncJob = new class() implements SyncPullJobInterface {
            public function perform(string $tenant_id): SyncPullResult {
				return SyncPullResult::failed(); }
            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult {
				return SyncPullResult::failed(); }
            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult {
				return SyncPullResult::failed(); }
        };

        $controller = new SyncStatusController($syncRepo, $syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertFalse($data['synced']);
        $this->assertSame('sync_failed', $data['reason']);
        $this->assertSame('stale', $data['sync_health']);
        $this->assertSame('failed', $data['last_sync_result']);
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
            public function perform(string $tenant_id): SyncPullResult {
				return SyncPullResult::failed(); }
            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult {
                throw new \RuntimeException('Connection refused');
            }
            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult {
                throw new \RuntimeException('Connection refused');
            }
        };

        $controller = new SyncStatusController($syncRepo, $syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertFalse($data['synced']);
        $this->assertSame('sync_failed', $data['reason']);
        $this->assertSame('stale', $data['sync_health']);
    }

    public function testTriggerSyncReturnsFullShapeWhenSyncJobCannotBeBuilt(): void
    {
        $syncRepo = new class() extends NullSyncStateRepository {
            public function get_snapshot_version(string $tenant_id): int {
                return 11;
            }
            public function get_last_updated(string $tenant_id): ?string {
                return '2026-03-08 01:00:00';
            }
            public function get_pending_curation_operations(string $tenant_id): int {
                return 2;
            }
            public function get_failed_curation_operations(string $tenant_id): int {
                return 1;
            }
            public function get_conflict_count(string $tenant_id): int {
                return 3;
            }
            public function get_pending_topology_commands(string $tenant_id): int {
                return 4;
            }
            public function get_applied_topology_commands(string $tenant_id): int {
                return 1;
            }
            public function get_failed_topology_commands(string $tenant_id): int {
                return 1;
            }
            public function get_conflicted_topology_commands(string $tenant_id): int {
                return 1;
            }
            public function get_last_topology_reconciled_at(string $tenant_id): ?string {
                return '2026-03-08 01:05:00';
            }
            public function get_last_sync_result(string $tenant_id): string {
                return 'ok';
            }
        };

        $controller = new class($syncRepo) extends SyncStatusController {
            protected function build_sync_pull_job(): SyncPullJobInterface
            {
                throw new \RuntimeException('composition failed');
            }
        };

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertFalse($data['synced']);
        $this->assertSame('sync_unavailable', $data['reason']);
        $this->assertSame('composition failed', $data['error']);
        $this->assertSame('failures', $data['sync_health']);
        $this->assertSame('ok', $data['last_sync_result']);
        $this->assertSame(11, $data['last_snapshot_version']);
        $this->assertSame('2026-03-08 01:00:00', $data['last_synced_at']);
        $this->assertSame(2, $data['pending_curation_operations']);
        $this->assertSame(1, $data['failed_curation_operations']);
        $this->assertSame(3, $data['conflict_count']);
        $this->assertSame(4, $data['topology_commands']['pending']);
        $this->assertSame('2026-03-08 01:05:00', $data['topology_commands']['last_reconciled_at']);
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
            public function perform(string $tenant_id): SyncPullResult {
				return SyncPullResult::ok(); }
            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult {
				return SyncPullResult::ok(); }
            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult {
				return SyncPullResult::ok(); }
        };

        $controller = new SyncStatusController($syncRepo, $syncJob);
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger');
        $response = $controller->trigger_sync($request);

        $data = $response->get_data();
        $this->assertTrue($data['synced']);
        $this->assertSame('no_remote_data', $data['reason']);
        $this->assertSame('stale', $data['sync_health']);
        $this->assertSame(0, $data['last_snapshot_version']);
        $this->assertSame('full', $data['sync_mode']);
    }
}
