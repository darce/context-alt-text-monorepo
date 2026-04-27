<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

interface ClustersRepositoryInterface {
	public const DEFAULT_LIST_LIMIT = 50;

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
	public function list_for_tenant( string $tenant_id, int $limit = self::DEFAULT_LIST_LIMIT, int $offset = 0, array $filters = array() ): array;

	/**
	 * Return labels present in projected clusters for a tenant.
	 *
	 * @return string[]
	 */
	public function list_labels( string $tenant_id ): array;

	/**
	 * Return whether any projected cluster rows exist for a tenant.
	 */
	public function has_projection_rows_for_tenant( string $tenant_id ): bool;

	/**
	 * Return top unlabeled clusters for a tenant.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function list_top_unlabeled( string $tenant_id, int $limit = 10 ): array;

	/**
	 * Count tenant-scoped unlabeled singleton clusters hidden from the primary naming queue.
	 */
	public function count_top_unlabeled_singletons( string $tenant_id ): int;

	/**
	 * Return one projected cluster row when present.
	 *
	 * @return array<string,mixed>|null
	 */
	public function find_by_uuid( string $cluster_uuid ): ?array;

	/**
	 * Update the label for a single cluster.
	 *
	 * When `$mark_user_confirmed` is true, the update is treated as user curation.
	 */
	public function update_label( string $cluster_uuid, string $label, bool $mark_user_confirmed = true ): int;

	/**
	 * Mark a cluster as dismissed and user confirmed.
	 */
	public function dismiss( string $cluster_uuid ): int;

	/**
	 * Update the projected identity count for one cluster.
	 */
	public function update_identity_count( string $cluster_uuid, int $identity_count ): int;

	/**
	 * Persist representative pin state for one projected cluster.
	 */
	public function update_representative_state( string $cluster_uuid, ?string $representative_id, bool $is_pinned, bool $is_local_curation = true ): int;

	/**
	 * Create a projected local cluster row.
	 */
	public function create_local_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1 ): int;

	/**
	 * Create or update a projected cluster row from backend-authored topology state.
	 */
	public function upsert_projection_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int;

	/**
	 * Update projection-owned cluster metadata without marking the row locally curated.
	 */
	public function update_projection_cluster( string $cluster_uuid, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int;

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

	/**
	 * Clear all curated fields on a tenant-scoped cluster so projection may overwrite it.
	 */
	public function reset_curation( string $cluster_uuid, string $tenant_id ): int;

	/**
	 * Delete a tenant-scoped cluster and any member rows attached to it.
	 */
	public function delete_cluster_with_members( string $cluster_uuid, string $tenant_id ): int;
}
