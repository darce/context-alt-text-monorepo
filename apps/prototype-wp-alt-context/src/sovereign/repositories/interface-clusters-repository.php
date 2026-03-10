<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

interface ClustersRepositoryInterface {
	/**
	 * Merge a snapshot payload into tenant-scoped cluster projection rows.
	 *
	 * @param array<int,array<string,mixed>> $clusters
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $clusters, int $snapshot_version ): void;

	/**
	 * Return tenant-scoped projected clusters.
	 *
	 * @param array<string,mixed> $filters
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_tenant( string $tenant_id, int $limit = 50, int $offset = 0, array $filters = array() ): array;

	/**
	 * Return labels present in projected clusters for a tenant.
	 *
	 * @return string[]
	 */
	public function list_labels( string $tenant_id ): array;

	/**
	 * Return top unlabeled clusters for a tenant.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function list_top_unlabeled( string $tenant_id, int $limit = 10 ): array;

	/**
	 * Return one projected cluster row when present.
	 *
	 * @return array<string,mixed>|null
	 */
	public function find_by_uuid( string $cluster_uuid ): ?array;

	/**
	 * Update the label for a single cluster and mark it as user confirmed.
	 */
	public function update_label( string $cluster_uuid, string $label ): int;

	/**
	 * Mark a cluster as dismissed and user confirmed.
	 */
	public function dismiss( string $cluster_uuid ): int;

	/**
	 * Clear dismissal on a cluster and return it to uncurated state.
	 */
	public function undismiss( string $cluster_uuid ): int;

	/**
	 * Return curated tenant-scoped projected clusters keyed by cluster_uuid.
	 *
	 * @return array<string,array<string,mixed>>
	 */
	public function get_curated_clusters_for_tenant( string $tenant_id ): array;
}
