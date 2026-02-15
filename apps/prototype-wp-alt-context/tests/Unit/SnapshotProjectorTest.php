<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SnapshotProjector;
use AltContext\Tests\TestCase;
use RuntimeException;

/**
 * @covers \AltContext\Sovereign\Sync\SnapshotProjector
 */
class SnapshotProjectorTest extends TestCase
{
    public function testProjectUsesTransactionAndCommitsOnSuccess(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();

        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);
        $projector->project(
            'tenant-a',
            [
                'snapshot_version' => 7,
                'clusters' => [['cluster_uuid' => 'cluster-1']],
                'members' => [['identity_uuid' => 'identity-1', 'cluster_uuid' => 'cluster-1']],
            ]
        );

        global $wpdb;
        $this->assertContains('START TRANSACTION', $wpdb->queries);
        $this->assertContains('COMMIT', $wpdb->queries);
        $this->assertNotContains('ROLLBACK', $wpdb->queries);

        $this->assertSame('tenant-a', $clustersRepo->tenantId);
        $this->assertSame(7, $clustersRepo->snapshotVersion);
        $this->assertCount(1, $clustersRepo->clusters);
        $this->assertCount(1, $membersRepo->members);
        $this->assertSame(7, $syncRepo->snapshotVersion);
    }

    public function testProjectRollsBackWhenRepositoryThrows(): void
    {
        $clustersRepo = new SnapshotProjectorClustersSpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $syncRepo = new SnapshotProjectorSyncStateSpy();

        $clustersRepo->shouldThrow = true;
        $projector = new SnapshotProjector($clustersRepo, $membersRepo, $syncRepo);

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('clusters-failure');

        try {
            $projector->project(
                'tenant-b',
                [
                    'snapshot_version' => 8,
                    'clusters' => [['cluster_uuid' => 'cluster-2']],
                    'members' => [],
                ]
            );
        } finally {
            global $wpdb;
            $this->assertContains('START TRANSACTION', $wpdb->queries);
            $this->assertContains('ROLLBACK', $wpdb->queries);
        }
    }

    public function testProjectFailsClosedWhenTransactionCannotStart(): void
    {
        global $wpdb;
        $wpdb->queryResults['START TRANSACTION'] = false;

        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy(),
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('transaction support');

        $projector->project('tenant-c', ['snapshot_version' => 3, 'clusters' => [], 'members' => []]);
    }

    public function testProjectWithEmptyTenantIdDispatchesWarningAndSkipsDatabaseWork(): void
    {
        $warnings = [];
        add_action(
            'acx_sovereign_warning',
            static function (string $code, array $context) use (&$warnings): void {
                $warnings[] = [$code, $context['method'] ?? ''];
            },
            10,
            2
        );

        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy(),
            new SnapshotProjectorMembersSpy(),
            new SnapshotProjectorSyncStateSpy()
        );

        $projector->project('  ', ['snapshot_version' => 4, 'clusters' => [], 'members' => []]);

        global $wpdb;
        $this->assertSame([], $wpdb->queries);
        $this->assertCount(1, $warnings);
        $this->assertSame('empty_tenant_id', $warnings[0][0]);
    }
}

class SnapshotProjectorClustersSpy implements ClustersRepositoryInterface
{
    public string $tenantId = '';
    public int $snapshotVersion = 0;
    public array $clusters = [];
    public bool $shouldThrow = false;

    public function merge_snapshot_for_tenant(string $tenant_id, array $clusters, int $snapshot_version): void
    {
        if ($this->shouldThrow) {
            throw new RuntimeException('clusters-failure');
        }

        $this->tenantId = $tenant_id;
        $this->clusters = $clusters;
        $this->snapshotVersion = $snapshot_version;
    }

    public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = []): array
    {
        return [];
    }

    public function list_labels(string $tenant_id): array
    {
        return [];
    }

    public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
    {
        return [];
    }

    public function find_by_uuid(string $cluster_uuid): ?array
    {
        return null;
    }
}

class SnapshotProjectorMembersSpy implements IdentityMembersRepositoryInterface
{
    public array $members = [];

    public function merge_snapshot_for_tenant(string $tenant_id, array $members, int $snapshot_version): void
    {
        $this->members = $members;
    }

    public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
    {
        return [];
    }

    public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
    {
        return [];
    }

    public function list_for_media_ids(string $tenant_id, array $media_ids): array
    {
        return [];
    }
}

class SnapshotProjectorSyncStateSpy implements SyncStateRepositoryInterface
{
    public int $snapshotVersion = 0;

    public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void
    {
        $this->snapshotVersion = $snapshot_version;
    }

    public function get_snapshot_version(string $tenant_id): int
    {
        return $this->snapshotVersion;
    }

    public function get_last_updated(string $tenant_id): ?string
    {
        return null;
    }
}
