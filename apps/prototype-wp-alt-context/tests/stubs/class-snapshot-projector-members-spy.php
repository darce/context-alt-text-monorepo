<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

/**
 * Spy over the identity-members repository for SnapshotProjector tests.
 *
 * Records merge calls (including the storm-suppression flag) and serves
 * curated members so both SnapshotProjectorTest and the storm-dampening
 * test can drive projection without a live repository.
 */
class SnapshotProjectorMembersSpy extends NullIdentityMembersRepository
{
    public array $members = [];
    public array $mergedMembers = [];
    public array $mergedMemberBatches = [];
    public int $memberPageSize = 0;
    /** @var array<int,bool> Suppression flag received per merge call. */
    public array $suppressionFlags = [];
    /** @var array<string,array<string,mixed>> Curated members keyed by identity_uuid. */
    public array $curatedMembers = [];
    /** @var array<string,array<int,array<string,mixed>>> */
    private array $membersByCluster;

    /**
     * @param array<string,array<int,array<string,mixed>>> $membersByCluster
     */
    public function __construct(array $membersByCluster = [])
    {
        $this->membersByCluster = $membersByCluster;
    }

    public function merge_snapshot_for_tenant(string $tenant_id, array $members, int $snapshot_version, bool $suppress_conflict_storm = false): void
    {
        $this->members = $members;
        $this->mergedMembers = $members;
        $this->mergedMemberBatches[] = $members;
        $this->suppressionFlags[] = $suppress_conflict_storm;
        $groupedMembers = [];
        foreach ($members as $member) {
            if (!is_array($member)) {
                continue;
            }

            $clusterUuid = (string) ($member['cluster_uuid'] ?? '');
            if ('' === $clusterUuid) {
                continue;
            }

            if (!isset($groupedMembers[$clusterUuid])) {
                $groupedMembers[$clusterUuid] = [];
            }
            $groupedMembers[$clusterUuid][] = $member;
        }
        $this->membersByCluster = $groupedMembers;
    }

    public function list_for_cluster_uuids(array $cluster_uuids, int $limit_per_cluster): array
    {
        $result = [];
        foreach ($cluster_uuids as $clusterUuid) {
            $result[$clusterUuid] = $this->membersByCluster[$clusterUuid] ?? [];
        }
        return $result;
    }

    public function list_for_cluster(string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null): array
    {
        $members = $this->membersByCluster[$cluster_uuid] ?? [];
        if ($this->memberPageSize > 0) {
            return array_slice($members, $offset, min($limit, $this->memberPageSize));
        }

        return array_slice($members, $offset, $limit);
    }

    public function get_curated_members_for_tenant(string $tenant_id): array
    {
        return $this->curatedMembers;
    }
}
