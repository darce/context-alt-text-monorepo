<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/interface-clusters-repository.php';
require_once __DIR__ . '/class-clusters-read-repository.php';
require_once __DIR__ . '/class-cluster-curation-writer.php';
require_once __DIR__ . '/class-cluster-projection-writer.php';
require_once __DIR__ . '/class-cluster-snapshot-merger.php';
require_once __DIR__ . '/class-cluster-deletion-service.php';

use function is_object;
use function is_string;

class ClustersRepository implements ClustersRepositoryInterface {
	private string $table_name;

	private ClustersReadRepository $read_repository;

	private ClusterCurationWriter $curation_writer;

	private ClusterProjectionWriter $projection_writer;

	private ClusterSnapshotMerger $snapshot_merger;

	private ClusterDeletionService $deletion_service;

	public function __construct(
		?string $table_name = null,
		?ClustersReadRepository $read_repository = null,
		?ClusterCurationWriter $curation_writer = null,
		?ClusterProjectionWriter $projection_writer = null,
		?ClusterSnapshotMerger $snapshot_merger = null,
		?ClusterDeletionService $deletion_service = null
	) {
		global $wpdb;

		$default_table = 'wp_acx_clusters';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_clusters';
		}

		$this->table_name        = $table_name ?? $default_table;
		$this->read_repository   = $read_repository ?? new ClustersReadRepository( $this->table_name );
		$this->curation_writer   = $curation_writer ?? new ClusterCurationWriter( $this->table_name );
		$this->projection_writer = $projection_writer ?? new ClusterProjectionWriter( $this->table_name );
		$this->snapshot_merger   = $snapshot_merger ?? new ClusterSnapshotMerger( $this->table_name );
		$this->deletion_service  = $deletion_service ?? new ClusterDeletionService( $this->table_name );
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $clusters, int $snapshot_version ): void {
		$this->snapshot_merger->merge_snapshot_for_tenant( $tenant_id, $clusters, $snapshot_version );
	}

	/**
	 * @param string[] $incoming_cluster_ids
	 */
	public function prepare_snapshot_merge_for_tenant( string $tenant_id, array $incoming_cluster_ids ): void {
		$this->snapshot_merger->prepare_snapshot_merge_for_tenant( $tenant_id, $incoming_cluster_ids );
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 */
	public function merge_snapshot_batch_for_tenant( string $tenant_id, array $clusters, int $snapshot_version ): void {
		$this->snapshot_merger->merge_snapshot_batch_for_tenant( $tenant_id, $clusters, $snapshot_version );
	}

	/**
	 * @param array<string,mixed> $filters
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_tenant( string $tenant_id, int $limit = ClustersRepositoryInterface::DEFAULT_LIST_LIMIT, int $offset = 0, array $filters = array() ): array {
		return $this->read_repository->list_for_tenant( $tenant_id, $limit, $offset, $filters );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_labels( string $tenant_id, string $search = '', int $limit = self::DEFAULT_LIST_LIMIT ): array {
		return $this->read_repository->list_labels( $tenant_id, $search, $limit );
	}

	public function has_projection_rows_for_tenant( string $tenant_id ): bool {
		return $this->read_repository->has_projection_rows_for_tenant( $tenant_id );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_top_unlabeled( string $tenant_id, int $limit = 10 ): array {
		return $this->read_repository->list_top_unlabeled( $tenant_id, $limit );
	}

	public function count_top_unlabeled_singletons( string $tenant_id ): int {
		return $this->read_repository->count_top_unlabeled_singletons( $tenant_id );
	}

	/**
	 * @return list<string>
	 */
	public function list_unlabeled_identity_count_drift( string $tenant_id, int $limit = 50 ): array {
		return $this->read_repository->list_unlabeled_identity_count_drift( $tenant_id, $limit );
	}

	/**
	 * @return array<string,mixed>|null
	 */
	public function find_by_uuid( string $cluster_uuid ): ?array {
		return $this->read_repository->find_by_uuid( $cluster_uuid );
	}

	public function update_label( string $cluster_uuid, string $label, bool $mark_user_confirmed = true ): int {
		return $this->curation_writer->update_label( $cluster_uuid, $label, $mark_user_confirmed );
	}

	public function dismiss( string $cluster_uuid ): int {
		return $this->curation_writer->dismiss( $cluster_uuid );
	}

	public function update_identity_count( string $cluster_uuid, int $identity_count ): int {
		return $this->curation_writer->update_identity_count( $cluster_uuid, $identity_count );
	}

	public function adjust_identity_count( string $cluster_uuid, int $delta ): int {
		return $this->curation_writer->adjust_identity_count( $cluster_uuid, $delta );
	}

	public function update_representative_state( string $cluster_uuid, ?string $representative_id, bool $is_pinned, bool $is_local_curation = true ): int {
		return $this->curation_writer->update_representative_state( $cluster_uuid, $representative_id, $is_pinned, $is_local_curation );
	}

	public function create_local_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1 ): int|\WP_Error {
		return $this->projection_writer->create_local_cluster( $tenant_id, $cluster_uuid, $label, $identity_count );
	}

	public function upsert_projection_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int {
		return $this->projection_writer->upsert_projection_cluster( $tenant_id, $cluster_uuid, $label, $identity_count, $snapshot_version, $representative_thumb_path, $representative_id, $is_pinned );
	}

	public function update_projection_cluster( string $cluster_uuid, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int {
		return $this->projection_writer->update_projection_cluster( $cluster_uuid, $identity_count, $snapshot_version, $representative_thumb_path, $representative_id, $is_pinned );
	}

	public function undismiss( string $cluster_uuid ): int {
		return $this->curation_writer->undismiss( $cluster_uuid );
	}

	/**
	 * @return array<string,array<string,mixed>>
	 */
	public function get_curated_clusters_for_tenant( string $tenant_id ): array {
		return $this->read_repository->get_curated_clusters_for_tenant( $tenant_id );
	}

	public function reset_curation( string $cluster_uuid, string $tenant_id ): int {
		return $this->curation_writer->reset_curation( $cluster_uuid, $tenant_id );
	}

	public function delete_cluster_with_members( string $cluster_uuid, string $tenant_id ): int {
		return $this->deletion_service->delete_cluster_with_members( $cluster_uuid, $tenant_id );
	}
}
