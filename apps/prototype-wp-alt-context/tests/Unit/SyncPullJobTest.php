<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\SyncPullJob;
use AltContext\Api\SyncStatusController;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SnapshotProjector;
use AltContext\Sovereign\Sync\SnapshotProjectorInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Response;
use WP_REST_Request;

/**
 * @covers \AltContext\Sovereign\Sync\SyncPullJob
 */
class SyncPullJobTest extends TestCase
{
    public function testSyncPullProjectsSnapshot(): void
    {
        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 12,
            'source_job_id' => 'job-12',
            'clusters' => [['cluster_uuid' => 'cluster-1']],
            'members' => [],
        ]);
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);

        $result = $job->perform('tenant-1');

        $this->assertSame(SyncPullResult::OK, $result->status());
        $this->assertSame('tenant-1', $projector->tenantId);
        $this->assertSame(12, $projector->snapshotVersion);
        $this->assertSame('job-12', $client->acknowledgedJobId);
        $this->assertSame(12, $client->acknowledgedSnapshotVersion);
        $this->assertNull($client->acknowledgedSnapshotGenerationId);
        $this->assertSame('ok', $syncRepo->get_last_sync_result('tenant-1'));
    }

    public function testSyncPullReturnsFalseOnSnapshotError(): void
    {
        $client = new SyncPullJobSnapshotClient(new WP_Error('snapshot_failed', 'Failed.', ['status' => 400]));
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);

        $result = $job->perform('tenant-2');

        $this->assertSame(SyncPullResult::UNREACHABLE, $result->status());
        $this->assertSame('', $projector->tenantId);
        $this->assertSame('unreachable', $syncRepo->get_last_sync_result('tenant-2'));
    }

    public function testSyncPullReturnsFalseWhenProjectorThrows(): void
    {
        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 12,
            'clusters' => [['cluster_uuid' => 'cluster-1']],
            'members' => [],
        ]);
        $projector = new SyncPullJobThrowingProjector();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);

        $result = $job->perform('tenant-throw');

        $this->assertSame(SyncPullResult::FAILED, $result->status());
        $this->assertSame('failed', $syncRepo->get_last_sync_result('tenant-throw'));
    }

    public function testSyncPullReturnsFalseOnNonArrayPayload(): void
    {
        // Client returns a string instead of an array — SyncPullJob must guard with is_array().
        $client = new SyncPullJobNonArrayClient();
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);

        $result = $job->perform('tenant-3');

        $this->assertSame(SyncPullResult::UNREACHABLE, $result->status());
        $this->assertSame('', $projector->tenantId, 'Projector must NOT be called when payload is non-array');
    }

    public function testSyncPullWithEmptyTenantIdPassesThroughToClient(): void
    {
        // SyncPullJob delegates validation to the collaborators (client/projector).
        // With empty tenant_id, the client stub here returns WP_Error.
        $client = new SyncPullJobSnapshotClient(new WP_Error('invalid_tenant_id', 'Tenant ID is required.'));
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);

        $result = $job->perform('');

        $this->assertSame(SyncPullResult::UNREACHABLE, $result->status());
        $this->assertSame('', $projector->tenantId, 'Projector must NOT be called on empty tenant_id failure');
    }

    public function testSyncPullSkipsFetchWhenCooldownTransientIsSet(): void
    {
        set_transient('acx_sync_cooldown_' . md5('tenant-cooldown'), 1, 30);
        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 1,
            'clusters' => [],
            'members' => [],
        ]);
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $syncRepo->set_last_sync_result('tenant-cooldown', 'failed');
        $job = new SyncPullJob($client, $projector, $syncRepo);
        $result = $job->perform('tenant-cooldown');

        $this->assertSame(SyncPullResult::SKIPPED, $result->status());
        $this->assertSame('', $projector->tenantId);
        $this->assertSame('failed', $syncRepo->get_last_sync_result('tenant-cooldown'));
    }

    public function testSyncPullRetriesAfterTransientDeletion(): void
    {
        $key = 'acx_sync_cooldown_' . md5('tenant-retry');
        set_transient($key, 1, 30);
        delete_transient($key);

        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 2,
            'clusters' => [['cluster_uuid' => 'cluster-2']],
            'members' => [],
        ]);
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);
        $result = $job->perform('tenant-retry');

        $this->assertSame(SyncPullResult::OK, $result->status());
        $this->assertSame('tenant-retry', $projector->tenantId);
    }

    public function testPerformBypassCooldownRunsEvenWhenCooldownIsSet(): void
    {
        set_transient('acx_sync_cooldown_' . md5('tenant-bypass'), 1, 30);
        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 3,
            'clusters' => [['cluster_uuid' => 'cluster-3']],
            'members' => [],
        ]);
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);
        $result = $job->perform_bypass_cooldown('tenant-bypass');

        $this->assertSame(SyncPullResult::OK, $result->status());
        $this->assertSame('tenant-bypass', $projector->tenantId);
    }

    public function testSyncPullProjectsEmptySnapshot(): void
    {
        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 0,
            'clusters' => [],
            'members' => [],
            'empty' => true,
        ]);
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);
        $result = $job->perform('tenant-empty');

        $this->assertSame(SyncPullResult::OK, $result->status(), 'Empty snapshot should be projected successfully');
        $this->assertSame('tenant-empty', $projector->tenantId);
        $this->assertSame(0, $projector->snapshotVersion);
    }

    public function testSyncPullDoesNotFailWhenProjectionAcknowledgementFails(): void
    {
        $received = null;
        add_action('acx_sync_pull_failed', static function (array $payload) use (&$received): void {
            $received = $payload;
        }, 10, 1);

        $client = new SyncPullJobSnapshotClient(
            [
                'snapshot_version' => 22,
                'source_job_id' => 'job-22',
                'clusters' => [['cluster_uuid' => 'cluster-22']],
                'members' => [],
            ],
            new WP_Error('ack_failed', 'failed')
        );
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);

        $result = $job->perform('tenant-ack');

        $this->assertSame(SyncPullResult::OK, $result->status());
        $this->assertSame('tenant-ack', $projector->tenantId);
        $this->assertSame('job-22', $client->acknowledgedJobId);
        $this->assertSame(22, $client->acknowledgedSnapshotVersion);
        $this->assertIsArray($received);
        $this->assertSame('tenant-ack', $received['tenant_id']);
        $this->assertSame('projection_acknowledgement_failed', $received['context']);
    }

    public function testSyncPullForwardsSnapshotGenerationIdWhenPresent(): void
    {
        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 23,
            'snapshot_generation_id' => 'generation-23',
            'source_job_id' => 'job-23',
            'clusters' => [['cluster_uuid' => 'cluster-23']],
            'members' => [],
        ]);
        $projector = new SyncPullJobProjectorSpy();

        $syncRepo = new SyncPullJobSyncStateSpy();
        $job = new SyncPullJob($client, $projector, $syncRepo);

        $result = $job->perform('tenant-generation');

        $this->assertSame(SyncPullResult::OK, $result->status());
        $this->assertSame('generation-23', $client->acknowledgedSnapshotGenerationId);
    }

    public function testTriggerSyncEndToEndReturnsConflictCountAfterProjection(): void
    {
        global $wpdb;
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-curated-local',
                'label' => 'Curated Local',
                'curation_state' => 'confirmed',
                'is_user_confirmed' => 1,
                'identity_uuid' => 'identity-curated-local',
                'is_curated' => 1,
                'projection_version' => 40,
            ],
        ];

        $syncRepo = new SyncPullJobSyncStateSpy();
        $projector = new SnapshotProjector(
            new ClustersRepository(),
            new IdentityMembersRepository(),
            $syncRepo
        );
        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 41,
            'source_job_id' => 'job-41',
            'clusters' => [
                [
                    'cluster_uuid' => 'cluster-curated-local',
                    'label' => 'Curated Local',
                    'curation_state' => 'confirmed',
                    'is_user_confirmed' => true,
                    'identity_count' => 1,
                    'representative_media_id' => 701,
                ],
                [
                    'cluster_uuid' => 'cluster-machine-target',
                    'label' => 'Machine Target',
                    'curation_state' => 'auto',
                    'is_user_confirmed' => false,
                    'identity_count' => 2,
                    'representative_media_id' => 703,
                ],
            ],
            'members' => [
                [
                    'identity_uuid' => 'identity-curated-local',
                    'cluster_uuid' => 'cluster-machine-target',
                    'attachment_id' => 701,
                ],
                [
                    'identity_uuid' => 'identity-new',
                    'cluster_uuid' => 'cluster-machine-target',
                    'attachment_id' => 703,
                ],
            ],
        ]);
        $syncJob = new SyncPullJob($client, $projector, $syncRepo);
        $controller = new SyncStatusController($syncRepo, $syncJob);

        $response = $controller->trigger_sync(new WP_REST_Request('POST', '/acx/v1/recognition/sync/trigger'));
        $data = $response->get_data();

        $this->assertTrue($data['synced']);
        $this->assertSame('ok', $data['reason']);
        $this->assertSame(1, $data['conflict_count']);
        $this->assertSame(41, $data['last_snapshot_version']);
        $this->assertSame('job-41', $client->acknowledgedJobId);
        $this->assertSame(41, $client->acknowledgedSnapshotVersion);

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString("'member_cluster_reassignment'", $sql);
    }
}

class SyncPullJobSyncStateSpy extends NullSyncStateRepository implements SyncStateRepositoryInterface
{
    private int $snapshotVersion = 0;
    private ?string $lastUpdated = null;
    private int $conflictCount = 0;
    private string $lastSyncResult = 'ok';

    public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void
    {
        $this->snapshotVersion = $snapshot_version;
        $this->lastUpdated = gmdate('Y-m-d H:i:s');
    }

    public function get_snapshot_version(string $tenant_id): int
    {
        return $this->snapshotVersion;
    }

    public function get_last_updated(string $tenant_id): ?string
    {
        return $this->lastUpdated;
    }

    public function refresh_curation_metrics(string $tenant_id): void
    {
        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->conflictCount = str_contains($sql, "'member_cluster_reassignment'") ? 1 : 0;
    }

    public function get_last_sync_result(string $tenant_id): string
    {
        return $this->lastSyncResult;
    }

    public function set_last_sync_result(string $tenant_id, string $result): void
    {
        $this->lastSyncResult = $result;
    }

    public function get_conflict_count(string $tenant_id): int
    {
        return $this->conflictCount;
    }
}

class SyncPullJobSnapshotClient extends SnapshotClient
{
    /** @var array<string,mixed>|WP_Error */
    private array|WP_Error $payload;
    private WP_Error|WP_REST_Response|null $acknowledgeResponse;
    public string $acknowledgedJobId = '';
    public int $acknowledgedSnapshotVersion = 0;
    public ?string $acknowledgedSnapshotGenerationId = null;

    public function __construct(array|WP_Error $payload, WP_Error|WP_REST_Response|null $acknowledgeResponse = null)
    {
        $this->payload = $payload;
        $this->acknowledgeResponse = $acknowledgeResponse;
    }

    public function fetch_snapshot(string $tenant_id): array|WP_Error
    {
        return $this->payload;
    }

    public function acknowledge_projection(
        string $job_id,
        int $snapshot_version,
        ?string $snapshot_generation_id = null
    ): WP_REST_Response|WP_Error
    {
        $this->acknowledgedJobId = $job_id;
        $this->acknowledgedSnapshotVersion = $snapshot_version;
        $this->acknowledgedSnapshotGenerationId = $snapshot_generation_id;
        if ($this->acknowledgeResponse instanceof WP_Error || $this->acknowledgeResponse instanceof WP_REST_Response) {
            return $this->acknowledgeResponse;
        }

        return new WP_REST_Response(['status' => 'acknowledged', 'snapshot_version' => $snapshot_version], 200);
    }
}

class SyncPullJobProjectorSpy implements SnapshotProjectorInterface
{
    public string $tenantId = '';
    public int $snapshotVersion = 0;

    public function project(string $tenant_id, array $snapshot): void
    {
        $this->tenantId = $tenant_id;
        $this->snapshotVersion = (int) ($snapshot['snapshot_version'] ?? 0);
    }
}

class SyncPullJobThrowingProjector implements SnapshotProjectorInterface
{
    public function project(string $tenant_id, array $snapshot): void
    {
        throw new \RuntimeException('projector failed');
    }
}

/**
 * Client stub that returns a non-array value to test the is_array() guard.
 *
 * PHP's actual SnapshotClient declares `array|WP_Error`, but a misbehaving
 * subclass or decode failure could produce a non-array. This stub simulates
 * that edge case by overriding fetch_snapshot to return a WP_Error wrapping
 * the "wrong type" scenario.
 */
class SyncPullJobNonArrayClient extends SnapshotClient
{
    public function __construct()
    {
        // No parent construction needed — we override the interactive method.
    }

    public function fetch_snapshot(string $tenant_id): array|WP_Error
    {
        // Simulate an invalid_snapshot_payload error (non-array decode result
        // is caught by SnapshotClient and converted to WP_Error).
        return new WP_Error('invalid_snapshot_payload', 'Snapshot payload must be an object.', ['status' => 502]);
    }
}
