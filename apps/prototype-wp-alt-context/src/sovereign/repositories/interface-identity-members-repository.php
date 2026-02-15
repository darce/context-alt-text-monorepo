<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

interface IdentityMembersRepositoryInterface {
	/**
	 * Merge identity-member rows from a snapshot payload.
	 *
	 * @param array<int,array<string,mixed>> $members
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $members, int $snapshot_version ): void;

	/**
	 * Return member rows for one projected cluster.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_cluster( string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null ): array;

	/**
	 * Return member rows for multiple cluster UUIDs in a single query.
	 *
	 * @param string[] $cluster_uuids
	 * @return array<string,array<int,array<string,mixed>>> Indexed by cluster_uuid
	 */
	public function list_for_cluster_uuids( array $cluster_uuids, int $limit_per_cluster ): array;

	/**
	 * Return member rows for attachment IDs scoped to a tenant.
	 *
	 * @param int[] $media_ids
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_media_ids( string $tenant_id, array $media_ids ): array;
}
