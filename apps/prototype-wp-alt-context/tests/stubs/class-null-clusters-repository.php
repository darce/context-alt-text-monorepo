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

	public function list_for_tenant( string $tenant_id, int $limit = 50, int $offset = 0, array $filters = array() ): array {
		return array();
	}

	public function list_labels( string $tenant_id ): array {
		return array();
	}

	public function list_top_unlabeled( string $tenant_id, int $limit = 10 ): array {
		return array();
	}

	public function find_by_uuid( string $cluster_uuid ): ?array {
		return null;
	}

	public function update_label( string $cluster_uuid, string $label ): void {}

	public function dismiss( string $cluster_uuid ): void {}

	public function undismiss( string $cluster_uuid ): void {}
}
