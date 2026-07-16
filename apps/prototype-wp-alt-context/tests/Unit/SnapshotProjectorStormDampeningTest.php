<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\SnapshotProjector;
use AltContext\Tests\TestCase;

/**
 * E15-35 Slice 3: conflict-storm dampening.
 *
 * A single mass-divergence snapshot must raise ONE aggregate
 * backend_roster_regressed conflict and suppress the per-entity curated_*
 * storm across both recording surfaces (projector cluster conflicts and the
 * member-merge conflict recorder).
 *
 * @covers \AltContext\Sovereign\Sync\SnapshotProjector
 */
class SnapshotProjectorStormDampeningTest extends TestCase
{
    /**
     * @param array<string,array<string,mixed>> $curatedClusters
     * @return array{0:SnapshotProjector,1:StormConflictRepositorySpy,2:SnapshotProjectorMembersSpy}
     */
    private function buildProjector(array $curatedClusters, array $curatedMembers = []): array
    {
        $conflictRepository = new StormConflictRepositorySpy();
        $membersRepo = new SnapshotProjectorMembersSpy();
        $membersRepo->curatedMembers = $curatedMembers;
        $projector = new SnapshotProjector(
            new SnapshotProjectorClustersSpy($curatedClusters),
            $membersRepo,
            new SnapshotProjectorSyncStateSpy(),
            $conflictRepository
        );

        return [$projector, $conflictRepository, $membersRepo];
    }

    /**
     * @return array<string,array<string,mixed>>
     */
    private function buildCuratedClusters(int $count, string $prefix = 'cluster-gone-'): array
    {
        $curated = [];
        for ($index = 1; $index <= $count; $index++) {
            $uuid = $prefix . $index;
            $curated[$uuid] = [
                'cluster_uuid' => $uuid,
                'label' => 'Curated ' . $index,
                'snapshot_version' => 5,
                'local_revision' => 2,
            ];
        }

        return $curated;
    }

    public function testMassDivergenceRecordsOneAggregateAndSuppressesBothPerEntitySurfaces(): void
    {
        $curatedMembers = [
            'identity-del-1' => ['identity_uuid' => 'identity-del-1', 'cluster_uuid' => 'cluster-m1'],
            'identity-del-2' => ['identity_uuid' => 'identity-del-2', 'cluster_uuid' => 'cluster-m1'],
            'identity-moved' => ['identity_uuid' => 'identity-moved', 'cluster_uuid' => 'cluster-m2'],
        ];
        [$projector, $conflictRepository, $membersRepo] = $this->buildProjector(
            $this->buildCuratedClusters(25),
            $curatedMembers
        );

        $projector->project(
            'tenant-storm',
            [
                'snapshot_version' => 41,
                'clusters' => [['cluster_uuid' => 'cluster-fresh', 'identity_count' => 1]],
                'members' => [['identity_uuid' => 'identity-moved', 'cluster_uuid' => 'cluster-remote']],
            ]
        );

        $this->assertCount(1, $conflictRepository->recorded, 'exactly one conflict row (the aggregate) must be recorded');
        $aggregate = $conflictRepository->recorded[0];
        $this->assertSame(ConflictRepository::CONFLICT_CODE_BACKEND_ROSTER_REGRESSED, $aggregate['conflict_code']);
        $this->assertSame(41, $aggregate['backend_version']);

        $machinePayload = $aggregate['machine_payload'];
        $this->assertSame(41, $machinePayload['backend_version']);
        $this->assertSame(
            ['curated_cluster_deleted' => 25, 'curated_member_deleted' => 2, 'member_cluster_reassignment' => 1],
            $machinePayload['counts']
        );
        $this->assertCount(25, $machinePayload['entities']['curated_cluster_deleted']);
        $this->assertSame(['identity-del-1', 'identity-del-2'], $machinePayload['entities']['curated_member_deleted']);
        $this->assertSame(['identity-moved'], $machinePayload['entities']['member_cluster_reassignment']);
        $this->assertSame(['identity-moved' => 'cluster-remote'], $machinePayload['reassignment_targets']);
        $this->assertFalse($machinePayload['entity_set_truncated']);
        $this->assertSame(['curated_clusters' => 25, 'curated_members' => 3], $aggregate['local_payload']);

        $this->assertSame([true], $membersRepo->suppressionFlags, 'member merge must run with storm suppression threaded through');
    }

    public function testBelowThresholdKeepsPerEntityConflictsOnBothSurfaces(): void
    {
        // 3 diverging of 10 curated clusters: under 20 absolute and under 50%.
        $curated = $this->buildCuratedClusters(3);
        $incoming = [];
        for ($index = 1; $index <= 7; $index++) {
            $uuid = 'cluster-kept-' . $index;
            $curated[$uuid] = [
                'cluster_uuid' => $uuid,
                'label' => 'Curated kept ' . $index,
                'snapshot_version' => 5,
                'local_revision' => 2,
            ];
            $incoming[] = ['cluster_uuid' => $uuid, 'label' => 'Curated kept ' . $index, 'identity_count' => 1];
        }

        [$projector, $conflictRepository, $membersRepo] = $this->buildProjector($curated);

        $projector->project(
            'tenant-calm',
            [
                'snapshot_version' => 42,
                'clusters' => $incoming,
                'members' => [],
            ]
        );

        $codes = array_column($conflictRepository->recorded, 'conflict_code');
        $this->assertSame(
            ['curated_cluster_deleted', 'curated_cluster_deleted', 'curated_cluster_deleted'],
            $codes,
            'below-threshold divergence must keep per-entity conflicts'
        );
        $this->assertSame([false], $membersRepo->suppressionFlags);
    }

    public function testOpenAggregateShortCircuitsSecondDivergentCycle(): void
    {
        [$projector, $conflictRepository, $membersRepo] = $this->buildProjector($this->buildCuratedClusters(25));
        $conflictRepository->openAggregate = [
            'id' => 7,
            'backend_version' => 43,
            'resolution_status' => 'open',
        ];

        $projector->project(
            'tenant-storm-repeat',
            [
                'snapshot_version' => 43,
                'clusters' => [['cluster_uuid' => 'cluster-fresh', 'identity_count' => 1]],
                'members' => [],
            ]
        );

        $this->assertSame([], $conflictRepository->recorded, 'no new aggregate and no per-entity rows while one is open for the same backend_version');
        $this->assertSame([true], $membersRepo->suppressionFlags, 'per-entity recording stays suppressed while degraded');
    }

    public function testAggregateEntityMapIsCappedWithTruncationFlag(): void
    {
        add_filter('acx_projection_conflict_storm_entity_cap', static fn(): int => 5);

        $curatedMembers = [
            'identity-del-1' => ['identity_uuid' => 'identity-del-1', 'cluster_uuid' => 'cluster-m1'],
            'identity-del-2' => ['identity_uuid' => 'identity-del-2', 'cluster_uuid' => 'cluster-m1'],
        ];
        [$projector, $conflictRepository] = $this->buildProjector($this->buildCuratedClusters(25), $curatedMembers);

        $projector->project(
            'tenant-truncated',
            [
                'snapshot_version' => 44,
                'clusters' => [['cluster_uuid' => 'cluster-fresh', 'identity_count' => 1]],
                'members' => [],
            ]
        );

        $this->assertCount(1, $conflictRepository->recorded);
        $machinePayload = $conflictRepository->recorded[0]['machine_payload'];
        $persistedKeyCount = count($machinePayload['entities']['curated_cluster_deleted'])
            + count($machinePayload['entities']['curated_member_deleted'])
            + count($machinePayload['entities']['member_cluster_reassignment']);
        $this->assertSame(5, $persistedKeyCount, 'persisted entity keys must be capped at the filtered max');
        $this->assertTrue($machinePayload['entity_set_truncated']);
        $this->assertSame(
            ['curated_cluster_deleted' => 25, 'curated_member_deleted' => 2, 'member_cluster_reassignment' => 0],
            $machinePayload['counts'],
            'counts must reflect the full divergence, not the truncated set'
        );
    }

    public function testInvalidThresholdFilterFallsBackToDefaultSoStormCapStaysEnforced(): void
    {
        add_filter('acx_projection_conflict_storm_absolute_threshold', static fn(): int => 0);

        // 19 diverging of 40 curated clusters: under the default 20 absolute and
        // under 50%; an unvalidated filter value of 0 would flip this to a storm.
        $curated = $this->buildCuratedClusters(19);
        $incoming = [];
        for ($index = 1; $index <= 21; $index++) {
            $uuid = 'cluster-kept-' . $index;
            $curated[$uuid] = [
                'cluster_uuid' => $uuid,
                'label' => 'Curated kept ' . $index,
                'snapshot_version' => 5,
                'local_revision' => 2,
            ];
            $incoming[] = ['cluster_uuid' => $uuid, 'label' => 'Curated kept ' . $index, 'identity_count' => 1];
        }

        [$projector, $conflictRepository, $membersRepo] = $this->buildProjector($curated);

        $projector->project(
            'tenant-bad-filter',
            [
                'snapshot_version' => 45,
                'clusters' => $incoming,
                'members' => [],
            ]
        );

        $codes = array_unique(array_column($conflictRepository->recorded, 'conflict_code'));
        $this->assertSame(['curated_cluster_deleted'], $codes, 'a bad filter must fall back to the default threshold');
        $this->assertCount(19, $conflictRepository->recorded);
        $this->assertSame([false], $membersRepo->suppressionFlags);
    }

    public function testValidThresholdFilterOverrideLowersStormTrigger(): void
    {
        add_filter('acx_projection_conflict_storm_absolute_threshold', static fn(): int => 10);

        $curated = $this->buildCuratedClusters(12);
        $incoming = [];
        for ($index = 1; $index <= 30; $index++) {
            $uuid = 'cluster-kept-' . $index;
            $curated[$uuid] = [
                'cluster_uuid' => $uuid,
                'label' => 'Curated kept ' . $index,
                'snapshot_version' => 5,
                'local_revision' => 2,
            ];
            $incoming[] = ['cluster_uuid' => $uuid, 'label' => 'Curated kept ' . $index, 'identity_count' => 1];
        }

        [$projector, $conflictRepository] = $this->buildProjector($curated);

        $projector->project(
            'tenant-filtered',
            [
                'snapshot_version' => 46,
                'clusters' => $incoming,
                'members' => [],
            ]
        );

        $this->assertCount(1, $conflictRepository->recorded);
        $this->assertSame(
            ConflictRepository::CONFLICT_CODE_BACKEND_ROSTER_REGRESSED,
            $conflictRepository->recorded[0]['conflict_code']
        );
    }
}

class StormConflictRepositorySpy extends ConflictRepository
{
    /** @var array<int,array<string,mixed>> */
    public array $recorded = [];
    /** @var array<string,mixed>|null */
    public ?array $openAggregate = null;

    public function record_projection_conflict(
        string $tenant_id,
        string $entity_type,
        string $entity_key,
        string $conflict_code,
        int $backend_version,
        int $expected_base_version,
        int $local_revision,
        array $machine_payload,
        array $local_payload
    ): int|false {
        $this->recorded[] = [
            'tenant_id' => $tenant_id,
            'entity_type' => $entity_type,
            'entity_key' => $entity_key,
            'conflict_code' => $conflict_code,
            'backend_version' => $backend_version,
            'machine_payload' => $machine_payload,
            'local_payload' => $local_payload,
        ];

        return count($this->recorded);
    }

    public function find_open_backend_roster_regression(string $tenant_id): ?array
    {
        return $this->openAggregate;
    }
}
