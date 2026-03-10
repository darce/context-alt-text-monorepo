<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;

/**
 * No-op implementation of IdentityMembersRepositoryInterface for unit tests.
 *
 * Extend this class and override only the methods your test needs.
 */
class NullIdentityMembersRepository implements IdentityMembersRepositoryInterface {
	public function merge_snapshot_for_tenant( string $tenant_id, array $members, int $snapshot_version ): void {}

	public function list_for_cluster( string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null ): array {
		return array();
	}

	public function list_for_cluster_uuids( array $cluster_uuids, int $limit_per_cluster ): array {
		return array();
	}

	public function list_for_media_ids( string $tenant_id, array $media_ids ): array {
		return array();
	}

	public function mark_as_curated( string $identity_uuid ): int {
		return 0;
	}

	public function reassign_to_cluster( string $identity_uuid, string $target_cluster_uuid ): int {
		return 0;
	}

	public function reassign_cluster_members( string $source_cluster_uuid, string $target_cluster_uuid ): int {
		return 0;
	}

	public function count_for_cluster( string $cluster_uuid ): int {
		return 0;
	}

	public function find_by_identity_uuid( string $identity_uuid ): ?array {
		return null;
	}

	public function get_curated_members_for_tenant( string $tenant_id ): array {
		return array();
	}
}
