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

	/**
	 * Mark one projected member row as locally curated.
	 */
	public function mark_as_curated( string $identity_uuid ): int;

	/**
	 * Reassign one projected member row to a different cluster and mark it as curated.
	 */
	public function reassign_to_cluster( string $identity_uuid, string $target_cluster_uuid ): int;

	/**
	 * Reassign one projected member row based on backend-authored projection state.
	 */
	public function assign_to_cluster_for_projection( string $identity_uuid, string $target_cluster_uuid, int $projection_version ): int;

	/**
	 * Reassign every projected member from one cluster to another and mark them as curated.
	 */
	public function reassign_cluster_members( string $source_cluster_uuid, string $target_cluster_uuid ): int;

	/**
	 * Count projected members for one cluster.
	 */
	public function count_for_cluster( string $cluster_uuid ): int;

	/**
	 * Return one projected member row by identity UUID when present.
	 *
	 * @return array<string,mixed>|null
	 */
	public function find_by_identity_uuid( string $identity_uuid ): ?array;

	/**
	 * Return curated member rows for one tenant keyed by identity_uuid.
	 *
	 * @return array<string,array<string,mixed>>
	 */
	public function get_curated_members_for_tenant( string $tenant_id ): array;
}
