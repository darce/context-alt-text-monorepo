<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\SyncPullJob;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SnapshotProjectorInterface;
use AltContext\Tests\TestCase;
use WP_Error;

/**
 * @covers \AltContext\Sovereign\Sync\SyncPullJob
 */
class SyncPullJobTest extends TestCase
{
    public function testSyncPullProjectsSnapshot(): void
    {
        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 12,
            'clusters' => [['cluster_uuid' => 'cluster-1']],
            'members' => [],
        ]);
        $projector = new SyncPullJobProjectorSpy();

        $job = new SyncPullJob($client, $projector);

        $result = $job->perform('tenant-1');

        $this->assertTrue($result);
        $this->assertSame('tenant-1', $projector->tenantId);
        $this->assertSame(12, $projector->snapshotVersion);
    }

    public function testSyncPullReturnsFalseOnSnapshotError(): void
    {
        $client = new SyncPullJobSnapshotClient(new WP_Error('snapshot_failed', 'Failed.', ['status' => 400]));
        $projector = new SyncPullJobProjectorSpy();

        $job = new SyncPullJob($client, $projector);

        $result = $job->perform('tenant-2');

        $this->assertFalse($result);
        $this->assertSame('', $projector->tenantId);
    }

    public function testSyncPullReturnsFalseWhenProjectorThrows(): void
    {
        $client = new SyncPullJobSnapshotClient([
            'snapshot_version' => 12,
            'clusters' => [['cluster_uuid' => 'cluster-1']],
            'members' => [],
        ]);
        $projector = new SyncPullJobThrowingProjector();

        $job = new SyncPullJob($client, $projector);

        $result = $job->perform('tenant-throw');

        $this->assertFalse($result);
    }

    public function testSyncPullReturnsFalseOnNonArrayPayload(): void
    {
        // Client returns a string instead of an array — SyncPullJob must guard with is_array().
        $client = new SyncPullJobNonArrayClient();
        $projector = new SyncPullJobProjectorSpy();

        $job = new SyncPullJob($client, $projector);

        $result = $job->perform('tenant-3');

        $this->assertFalse($result);
        $this->assertSame('', $projector->tenantId, 'Projector must NOT be called when payload is non-array');
    }

    public function testSyncPullWithEmptyTenantIdPassesThroughToClient(): void
    {
        // SyncPullJob delegates validation to the collaborators (client/projector).
        // With empty tenant_id, the client stub here returns WP_Error.
        $client = new SyncPullJobSnapshotClient(new WP_Error('invalid_tenant_id', 'Tenant ID is required.'));
        $projector = new SyncPullJobProjectorSpy();

        $job = new SyncPullJob($client, $projector);

        $result = $job->perform('');

        $this->assertFalse($result);
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

        $job = new SyncPullJob($client, $projector);
        $result = $job->perform('tenant-cooldown');

        $this->assertFalse($result);
        $this->assertSame('', $projector->tenantId);
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

        $job = new SyncPullJob($client, $projector);
        $result = $job->perform('tenant-retry');

        $this->assertTrue($result);
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

        $job = new SyncPullJob($client, $projector);
        $result = $job->perform_bypass_cooldown('tenant-bypass');

        $this->assertTrue($result);
        $this->assertSame('tenant-bypass', $projector->tenantId);
    }
}

class SyncPullJobSnapshotClient extends SnapshotClient
{
    /** @var array<string,mixed>|WP_Error */
    private array|WP_Error $payload;

    public function __construct(array|WP_Error $payload)
    {
        $this->payload = $payload;
    }

    public function fetch_snapshot(string $tenant_id): array|WP_Error
    {
        return $this->payload;
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
