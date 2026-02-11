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
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_tenant( string $tenant_id, int $limit = 50, int $offset = 0 ): array;

	/**
	 * Return one projected cluster row when present.
	 *
	 * @return array<string,mixed>|null
	 */
	public function find_by_uuid( string $cluster_uuid ): ?array;
}
