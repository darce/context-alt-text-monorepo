<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersHostInterface;
use AltContext\Api\Services\ClusterProjectionSyncService;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\TestCase;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterProjectionSyncService
 */
class ClusterProjectionSyncServiceTest extends TestCase
{
    private const BOOTSTRAP_HOOK = 'acx_bootstrap_sync_test';

    public function testClusterRowShouldHaveMembersRequiresPositiveIdentityCount(): void
    {
        $service = $this->makeService();

        $this->assertFalse($service->cluster_row_should_have_members([]));
        $this->assertFalse($service->cluster_row_should_have_members(['identity_count' => 0]));
        $this->assertTrue($service->cluster_row_should_have_members(['identity_count' => 2]));
    }

    public function testMaybeBootstrapAfterProxyReadSchedulesCronWhenInlineSyncFails(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $syncJob = new class() implements SyncPullJobInterface {
            public function perform(string $tenant_id): SyncPullResult
            {
                return SyncPullResult::ok();
            }

            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
            {
                return SyncPullResult::failed();
            }

            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
            {
                return SyncPullResult::ok();
            }
        };

        $service = $this->makeService(sync_pull_job: $syncJob);
        $response = new WP_REST_Response(['clusters' => []], 200);

        $result = $service->maybe_bootstrap_after_proxy_read('tenant-1', $response);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
        $scheduled_key = array_key_first($GLOBALS['__ac_scheduled']);
        $this->assertIsString($scheduled_key);
        $this->assertStringStartsWith(self::BOOTSTRAP_HOOK . '::', $scheduled_key);
        $this->assertSame(['tenant-1'], $GLOBALS['__ac_scheduled'][$scheduled_key]['args']);
    }

    public function testPerformBootstrapSyncInvokesBypassCooldown(): void
    {
        $calls = [];
        $syncJob = new class($calls) implements SyncPullJobInterface {
            /** @var list<string> */
            private array $calls;

            /** @param list<string> $calls */
            public function __construct(array &$calls)
            {
                $this->calls = &$calls;
            }

            public function perform(string $tenant_id): SyncPullResult
            {
                return SyncPullResult::ok();
            }

            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
            {
                $this->calls[] = $tenant_id;
                return SyncPullResult::ok();
            }

            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
            {
                return SyncPullResult::ok();
            }
        };

        $service = $this->makeService(sync_pull_job: $syncJob);
        $service->perform_bootstrap_sync('tenant-abc');

        $this->assertSame(['tenant-abc'], $calls);
    }

    private function makeService(?SyncPullJobInterface $sync_pull_job = null): ClusterProjectionSyncService
    {
        $host = new class() implements ClustersHostInterface {
            public function get_tenant_id(): string
            {
                return 'tenant-1';
            }

            public function proxy_recognition_request(
                string $method,
                string $path,
                array $body = [],
                array $query = [],
                string $request_class = 'auto',
                string $body_kind = 'json',
                ?int $max_body_bytes = null
            ): \WP_REST_Response|\WP_Error {
                return new WP_REST_Response([], 200);
            }

            public function host_should_use_local_projection_gate(
                \AltContext\Sovereign\Repositories\SyncStateRepositoryInterface $sync_state_repository,
                string $tenant_id
            ): bool {
                return true;
            }

            public function host_is_projection_stale(?string $updated_at): bool
            {
                return false;
            }
        };

        return new ClusterProjectionSyncService(
            $host,
            self::BOOTSTRAP_HOOK,
            new ClustersRepository(),
            new IdentityMembersRepository(),
            new NullSyncStateRepository(),
            $sync_pull_job,
            null
        );
    }
}
