<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\SnapshotProjector;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
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

    public function testProjectRecordsCuratedClusterDeletionConflictsAndRefreshesMetrics(): void
    {
        global $wpdb;

        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $syncRepo->postRefreshConflictCount = 1;
        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy([
                'cluster-missing' => [
                    'cluster_uuid' => 'cluster-missing',
                    'label' => 'Curated',
                    'person_id' => 22,
                    'curation_state' => 'dismissed',
                    'snapshot_version' => 12,
                    'local_revision' => 5,
                ],
            ]),
            new SnapshotProjectorMembersSpy(),
            $syncRepo,
            new ConflictRepository()
        );

        $hookCalls = [];
        add_action(
            'acx_projection_conflicts_detected',
            static function (int $count, string $tenantId) use (&$hookCalls): void {
                $hookCalls[] = [$count, $tenantId];
            },
            10,
            2
        );

        $projector->project(
            'tenant-conflicts',
            [
                'snapshot_version' => 19,
                'clusters' => [],
                'members' => [],
            ]
        );

        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('INSERT INTO `wp_acx_sync_conflicts`', $sql);
        $this->assertStringContainsString("'curated_cluster_deleted'", $sql);
        $this->assertSame('tenant-conflicts', $syncRepo->refreshedTenantId);
        $this->assertSame([[1, 'tenant-conflicts']], $hookCalls);
    }

    public function testProjectEmitsConflictHookForMemberConflictsAfterMetricsRefresh(): void
    {
        $syncRepo = new SnapshotProjectorSyncStateSpy();
        $syncRepo->postRefreshConflictCount = 2;

        $hookCalls = [];
        add_action(
            'acx_projection_conflicts_detected',
            static function (int $count, string $tenantId) use (&$hookCalls): void {
                $hookCalls[] = [$count, $tenantId];
            },
            10,
            2
        );

        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy(),
            new SnapshotProjectorMembersSpy(),
            $syncRepo,
            new ConflictRepository()
        );

        $projector->project(
            'tenant-member-conflicts',
            [
                'snapshot_version' => 21,
                'clusters' => [],
                'members' => [],
            ]
        );

        $this->assertSame([[2, 'tenant-member-conflicts']], $hookCalls);
    }
}

class SnapshotProjectorClustersSpy extends NullClustersRepository
{
    public string $tenantId = '';
    public int $snapshotVersion = 0;
    public array $clusters = [];
    public bool $shouldThrow = false;
    /** @var array<string,array<string,mixed>> */
    private array $curatedClusters;

    /**
     * @param array<string,array<string,mixed>> $curatedClusters
     */
    public function __construct(array $curatedClusters = [])
    {
        $this->curatedClusters = $curatedClusters;
    }

    public function merge_snapshot_for_tenant(string $tenant_id, array $clusters, int $snapshot_version): void
    {
        if ($this->shouldThrow) {
            throw new RuntimeException('clusters-failure');
        }

        $this->tenantId = $tenant_id;
        $this->clusters = $clusters;
        $this->snapshotVersion = $snapshot_version;
    }

    public function get_curated_clusters_for_tenant(string $tenant_id): array
    {
        return $this->curatedClusters;
    }
}

class SnapshotProjectorMembersSpy extends NullIdentityMembersRepository
{
    public array $members = [];

    public function merge_snapshot_for_tenant(string $tenant_id, array $members, int $snapshot_version): void
    {
        $this->members = $members;
    }
}

class SnapshotProjectorSyncStateSpy extends NullSyncStateRepository
{
    public int $snapshotVersion = 0;
    public string $refreshedTenantId = '';
    public int $conflictCount = 0;
    public int $preRefreshConflictCount = 0;
    public int $postRefreshConflictCount = 0;

    public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void
    {
        $this->snapshotVersion = $snapshot_version;
    }

    public function get_snapshot_version(string $tenant_id): int
    {
        return $this->snapshotVersion;
    }

    public function get_conflict_count(string $tenant_id): int
    {
        return $this->conflictCount;
    }

    public function refresh_curation_metrics(string $tenant_id): void
    {
        $this->refreshedTenantId = $tenant_id;
        $this->conflictCount = $this->postRefreshConflictCount;
    }
}
