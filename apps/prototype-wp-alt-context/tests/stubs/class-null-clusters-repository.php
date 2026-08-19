<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;

/**
 * No-op implementation of ClustersRepositoryInterface for unit tests.
 *
 * Extend this class and override only the methods your test needs, instead of
 * writing an anonymous class that must implement all 8 interface methods.
 */
class NullClustersRepository implements ClustersRepositoryInterface {
	public function merge_snapshot_for_tenant( string $tenant_id, array $clusters, int $snapshot_version ): void {}

	public function prepare_snapshot_merge_for_tenant( string $tenant_id, array $incoming_cluster_ids ): void {}

	public function merge_snapshot_batch_for_tenant( string $tenant_id, array $clusters, int $snapshot_version ): void {}

	public function list_for_tenant( string $tenant_id, int $limit = 50, int $offset = 0, array $filters = array() ): array {
		return array();
	}

	public function list_labels( string $tenant_id, string $search = '', int $limit = self::DEFAULT_LIST_LIMIT ): array {
		return array();
	}

	public function has_projection_rows_for_tenant( string $tenant_id ): bool {
		return false;
	}

	public function list_top_unlabeled( string $tenant_id, int $limit = 10 ): array {
		return array();
	}

	public function count_top_unlabeled_singletons( string $tenant_id ): int {
		return 0;
	}

	public function list_unlabeled_identity_count_drift( string $tenant_id, int $limit = 50 ): array {
		return array();
	}

	public function find_by_uuid( string $cluster_uuid ): ?array {
		return null;
	}

	public function update_label( string $cluster_uuid, string $label, bool $mark_user_confirmed = true ): int {
		return 0;
	}

	public function dismiss( string $cluster_uuid ): int {
		return 0;
	}

	public function update_identity_count( string $cluster_uuid, int $identity_count ): int {
		return 0;
	}

	public function adjust_identity_count( string $cluster_uuid, int $delta ): int {
		return 0;
	}

	public function update_representative_state( string $cluster_uuid, ?string $representative_id, bool $is_pinned, bool $is_local_curation = true ): int {
		return 0;
	}

	public function create_local_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1 ): int|\WP_Error {
		return 0;
	}

	public function upsert_projection_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int {
		return 0;
	}

	public function update_projection_cluster( string $cluster_uuid, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int {
		return 0;
	}

	public function undismiss( string $cluster_uuid ): int {
		return 0;
	}

	public function get_curated_clusters_for_tenant( string $tenant_id ): array {
		return array();
	}

	public function reset_curation( string $cluster_uuid, string $tenant_id ): int {
		return 0;
	}

	public function delete_cluster_with_members( string $cluster_uuid, string $tenant_id ): int {
		return 0;
	}
}
