<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersHostInterface;
use AltContext\Api\Services\ClusterProjectionSyncService;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Sovereign\Sync\TargetedSyncPullJobInterface;
use AltContext\Tests\TestCase;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\Stubs\SpySyncPullJob;
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

    public function testRepairTargetedProjectionSchedulesClusterIdsAndDoesNotPullInline(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $syncJob = new SpySyncPullJob();
        $service = $this->makeService(sync_pull_job: $syncJob);

        $this->assertFalse(
            $service->repair_targeted_projection('tenant-1', ['cluster-a', '', 'cluster-a', 'cluster-b'])
        );
        $this->assertSame([], $syncJob->performCalls);
        $this->assertSame([], $syncJob->bypassCalls);
        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
        $scheduled = array_values($GLOBALS['__ac_scheduled'])[0];
        $this->assertSame(['tenant-1', ['cluster-a', 'cluster-b']], $scheduled['args']);
    }

    public function testRepairTargetedProjectionNoopsOnEmptyIds(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $service = $this->makeService();

        $this->assertFalse($service->repair_targeted_projection('tenant-1', []));
        $this->assertFalse($service->repair_targeted_projection('tenant-1', ['', ' ']));
        $this->assertCount(0, $GLOBALS['__ac_scheduled']);
    }

    public function testPerformBootstrapSyncWithClusterIdsRunsTargetedSnapshot(): void
    {
        $targeted = [];
        $syncJob = new class($targeted) implements TargetedSyncPullJobInterface {
            /** @var list<array{0:string,1:list<string>}> */
            private array $targeted;

            /** @param list<array{0:string,1:list<string>}> $targeted */
            public function __construct(array &$targeted)
            {
                $this->targeted = &$targeted;
            }

            public function perform(string $tenant_id): SyncPullResult
            {
                return SyncPullResult::ok();
            }

            public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
            {
                return SyncPullResult::ok();
            }

            public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
            {
                return SyncPullResult::ok();
            }

            public function perform_targeted_snapshot(string $tenant_id, array $cluster_ids): SyncPullResult
            {
                $this->targeted[] = [$tenant_id, $cluster_ids];
                return SyncPullResult::ok();
            }
        };

        $service = $this->makeService(sync_pull_job: $syncJob);
        $service->perform_bootstrap_sync('tenant-1', ['cluster-a', 'cluster-a']);

        $this->assertSame([['tenant-1', ['cluster-a']]], $targeted);
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

    public function testNewlyQualifyingRowsPresentServesLocalAndSchedulesOneDedupedHealEvent(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $GLOBALS['__ac_schedule_single_event_calls'] = [];
        $syncJob = new SpySyncPullJob();
        $rowsRepo = new class() extends NullClustersRepository {
            public function has_projection_rows_for_tenant(string $tenant_id): bool
            {
                return true;
            }
        };

        $service = $this->makeService(
            sync_pull_job: $syncJob,
            gate_passes: false,
            clusters_repository: $rowsRepo
        );

        $this->assertTrue($service->should_use_local_projection('tenant-1'));
        $this->assertSame([], $syncJob->performCalls, 'Newly-qualifying path must never run the inline pull.');
        $this->assertSame([], $syncJob->bypassCalls, 'Newly-qualifying path must never bypass-pull.');
        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
        $scheduled_key = array_key_first($GLOBALS['__ac_scheduled']);
        $this->assertIsString($scheduled_key);
        $this->assertStringStartsWith(self::BOOTSTRAP_HOOK . '::', $scheduled_key);
        $this->assertSame(['tenant-1'], $GLOBALS['__ac_scheduled'][$scheduled_key]['args']);
        $this->assertCount(
            1,
            $GLOBALS['__ac_schedule_single_event_calls'],
            'First read must invoke wp_schedule_single_event exactly once.'
        );

        // Second read: wp_next_scheduled now returns a live timestamp, so the
        // production dedup guard must short-circuit and NOT re-invoke
        // wp_schedule_single_event. The keyed __ac_scheduled map cannot prove
        // this (a second schedule overwrites the same key), so we assert on
        // the append-only invocation log — deleting the guard makes this RED.
        $this->assertTrue($service->should_use_local_projection('tenant-1'));
        $this->assertCount(1, $GLOBALS['__ac_scheduled'], 'Heal event must be deduped via wp_next_scheduled.');
        $this->assertCount(
            1,
            $GLOBALS['__ac_schedule_single_event_calls'],
            'Heal event must be deduped: wp_schedule_single_event must fire once across two reads.'
        );
    }

    public function testGateFailsNoRowsStaysRemoteAndSchedulesNothing(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $syncJob = new SpySyncPullJob();

        $service = $this->makeService(sync_pull_job: $syncJob, gate_passes: false);

        $this->assertFalse($service->should_use_local_projection('tenant-1'));
        $this->assertSame([], $syncJob->performCalls);
        $this->assertSame([], $syncJob->bypassCalls);
        $this->assertCount(0, $GLOBALS['__ac_scheduled']);
    }

    public function testPreviouslyQualifyingStaleSchedulesAsyncHealWithoutInlinePull(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $syncJob = new SpySyncPullJob();

        $service = $this->makeService(
            sync_pull_job: $syncJob,
            gate_passes: true,
            projection_stale: true
        );

        $this->assertTrue($service->should_use_local_projection('tenant-1'));
        // BR-03: the gate-pass+stale path heals async — no inline pull blocks the
        // read. Unlike the old ignored-result inline pull, it always leaves a
        // deduped cron fallback scheduled so the projection actually converges.
        $this->assertSame([], $syncJob->performCalls, 'Stale qualifying read must not pull inline.');
        $this->assertSame([], $syncJob->bypassCalls);
        $this->assertCount(1, $GLOBALS['__ac_scheduled']);
        $scheduled_key = array_key_first($GLOBALS['__ac_scheduled']);
        $this->assertIsString($scheduled_key);
        $this->assertStringStartsWith(self::BOOTSTRAP_HOOK . '::', $scheduled_key);
        $this->assertSame(['tenant-1'], $GLOBALS['__ac_scheduled'][$scheduled_key]['args']);
    }

    public function testPreviouslyQualifyingFreshSchedulesNothing(): void
    {
        $GLOBALS['__ac_scheduled'] = [];
        $syncJob = new SpySyncPullJob();

        $service = $this->makeService(sync_pull_job: $syncJob, gate_passes: true);

        $this->assertTrue($service->should_use_local_projection('tenant-1'));
        $this->assertSame([], $syncJob->performCalls);
        $this->assertSame([], $syncJob->bypassCalls);
        $this->assertCount(0, $GLOBALS['__ac_scheduled']);
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

    private function makeService(
        ?SyncPullJobInterface $sync_pull_job = null,
        bool $gate_passes = true,
        bool $projection_stale = false,
        ?NullClustersRepository $clusters_repository = null
    ): ClusterProjectionSyncService {
        $host = new class($gate_passes, $projection_stale) implements ClustersHostInterface {
            public function __construct(
                private bool $gate_passes,
                private bool $projection_stale
            ) {
            }

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
                return $this->gate_passes;
            }

            public function host_is_projection_stale(?string $updated_at): bool
            {
                return $this->projection_stale;
            }
        };

        return new ClusterProjectionSyncService(
            $host,
            self::BOOTSTRAP_HOOK,
            $clusters_repository ?? new NullClustersRepository(),
            new NullIdentityMembersRepository(),
            new NullSyncStateRepository(),
            $sync_pull_job,
            null
        );
    }
}
