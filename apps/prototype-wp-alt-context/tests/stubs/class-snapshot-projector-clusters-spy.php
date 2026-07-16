<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

use RuntimeException;

/**
 * Spy over the clusters repository for SnapshotProjector tests.
 *
 * Captures merged snapshot batches and serves curated clusters so both
 * SnapshotProjectorTest and the storm-dampening test can drive projection
 * without a live repository.
 */
class SnapshotProjectorClustersSpy extends NullClustersRepository
{
    public string $tenantId = '';
    public int $snapshotVersion = 0;
    public array $clusters = [];
    public array $mergedClusters = [];
    public array $mergedClusterBatches = [];
    public bool $shouldThrow = false;
    public int $tenantPageSize = 0;
    /** @var array<int,array<string,mixed>> */
    public array $topUnlabeledRows = [];
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
        $this->mergedClusters = $clusters;
        $this->mergedClusterBatches[] = $clusters;
        $this->snapshotVersion = $snapshot_version;
        $this->topUnlabeledRows = array_values(
            array_filter(
                $clusters,
                static function ($cluster): bool {
                    if (!is_array($cluster)) {
                        return false;
                    }

                    $label = trim((string) ($cluster['label'] ?? ''));
                    $curationState = trim((string) ($cluster['curation_state'] ?? ''));
                    return '' === $label && 'dismissed' !== $curationState;
                }
            )
        );
        usort(
            $this->topUnlabeledRows,
            static function (array $left, array $right): int {
                $countCompare = (int) ($right['identity_count'] ?? 0) <=> (int) ($left['identity_count'] ?? 0);
                if (0 !== $countCompare) {
                    return $countCompare;
                }

                return strcmp((string) ($right['updated_at'] ?? ''), (string) ($left['updated_at'] ?? ''));
            }
        );
    }

    public function prepare_snapshot_merge_for_tenant(string $tenant_id, array $incoming_cluster_ids): void
    {
        $this->tenantId = $tenant_id;
    }

    public function merge_snapshot_batch_for_tenant(string $tenant_id, array $clusters, int $snapshot_version): void
    {
        $this->merge_snapshot_for_tenant($tenant_id, $clusters, $snapshot_version);
    }

    public function list_top_unlabeled(string $tenant_id, int $limit = 10): array
    {
        return array_slice($this->topUnlabeledRows, 0, max(1, $limit));
    }

    public function list_for_tenant(string $tenant_id, int $limit = 50, int $offset = 0, array $filters = array()): array
    {
        $clusters = array_values($this->curatedClusters);
        if ($this->tenantPageSize > 0) {
            return array_slice($clusters, $offset, min($limit, $this->tenantPageSize));
        }

        return $clusters;
    }

    public function get_curated_clusters_for_tenant(string $tenant_id): array
    {
        return $this->curatedClusters;
    }
}
