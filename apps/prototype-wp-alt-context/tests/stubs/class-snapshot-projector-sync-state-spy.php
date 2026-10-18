<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

/**
 * Spy over the sync-state repository for SnapshotProjector tests.
 *
 * Tracks snapshot-version upserts and curation-metric refreshes so both
 * SnapshotProjectorTest and the storm-dampening test can assert projection
 * side effects without a live repository.
 */
class SnapshotProjectorSyncStateSpy extends NullSyncStateRepository
{
    public int $snapshotVersion = 0;
    public string $refreshedTenantId = '';
    public int $conflictCount = 0;
    public int $preRefreshConflictCount = 0;
    public int $postRefreshConflictCount = 0;
    public ?string $lastUpdated = null;

    public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void
    {
        $this->snapshotVersion = $snapshot_version;
        $this->lastUpdated = '2026-03-25 00:00:00';
    }

    public function get_snapshot_version(string $tenant_id): int
    {
        return $this->snapshotVersion;
    }

    public function get_last_updated(string $tenant_id): ?string
    {
        return $this->lastUpdated;
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
