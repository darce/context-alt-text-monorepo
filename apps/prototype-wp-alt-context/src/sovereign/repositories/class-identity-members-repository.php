<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/class-identity-members-read-repository.php';
require_once __DIR__ . '/class-identity-member-curation-writer.php';
require_once __DIR__ . '/class-member-conflict-recorder.php';
require_once __DIR__ . '/class-identity-member-snapshot-merger.php';
require_once __DIR__ . '/class-identity-member-deletion-service.php';
require_once __DIR__ . '/../sync/class-conflict-repository.php';

use AltContext\Sovereign\Sync\ConflictRepository;
use function is_object;
use function is_string;

class IdentityMembersRepository implements IdentityMembersRepositoryInterface {
	private string $members_table_name;
	private string $clusters_table_name;

	private IdentityMembersReadRepository $read_repository;

	private IdentityMemberCurationWriter $curation_writer;

	private MemberConflictRecorder $conflict_recorder;

	private IdentityMemberSnapshotMerger $snapshot_merger;

	private IdentityMemberDeletionService $deletion_service;

	public function __construct(
		?string $members_table_name = null,
		?string $clusters_table_name = null,
		?ConflictRepository $conflict_repository = null,
		?IdentityMembersReadRepository $read_repository = null,
		?IdentityMemberCurationWriter $curation_writer = null,
		?MemberConflictRecorder $conflict_recorder = null,
		?IdentityMemberSnapshotMerger $snapshot_merger = null,
		?IdentityMemberDeletionService $deletion_service = null
	) {
		global $wpdb;

		$prefix = 'wp_';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$prefix = $wpdb->prefix;
		}

		$this->members_table_name  = $members_table_name ?? $prefix . 'acx_identity_members';
		$this->clusters_table_name = $clusters_table_name ?? $prefix . 'acx_clusters';

		$resolved_conflict_repository = $conflict_repository ?? new ConflictRepository();
		$this->read_repository        = $read_repository ?? new IdentityMembersReadRepository( $this->members_table_name, $this->clusters_table_name );
		$this->conflict_recorder      = $conflict_recorder ?? new MemberConflictRecorder( $resolved_conflict_repository );
		$this->curation_writer        = $curation_writer ?? new IdentityMemberCurationWriter( $this->members_table_name, $this->clusters_table_name );
		$this->deletion_service       = $deletion_service ?? new IdentityMemberDeletionService( $this->members_table_name, $this->clusters_table_name );
		$this->snapshot_merger        = $snapshot_merger ?? new IdentityMemberSnapshotMerger(
			$this->members_table_name,
			$this->clusters_table_name,
			$this->read_repository,
			$this->conflict_recorder
		);
	}

	/**
	 * @param array<int,array<string,mixed>> $members
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $members, int $snapshot_version ): void {
		$this->snapshot_merger->merge_snapshot_for_tenant( $tenant_id, $members, $snapshot_version );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_cluster( string $cluster_uuid, int $limit = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT, int $offset = 0, ?string $tenant_id = null ): array {
		return $this->read_repository->list_for_cluster( $cluster_uuid, $limit, $offset, $tenant_id );
	}

	/**
	 * @param string[] $cluster_uuids
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	public function list_for_cluster_uuids( array $cluster_uuids, int $limit_per_cluster ): array {
		return $this->read_repository->list_for_cluster_uuids( $cluster_uuids, $limit_per_cluster );
	}

	/**
	 * @param int[] $media_ids
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_media_ids( string $tenant_id, array $media_ids ): array {
		return $this->read_repository->list_for_media_ids( $tenant_id, $media_ids );
	}

	public function has_projection_rows_for_tenant( string $tenant_id ): bool {
		return $this->read_repository->has_projection_rows_for_tenant( $tenant_id );
	}

	public function mark_as_curated( string $identity_uuid ): int {
		return $this->curation_writer->mark_as_curated( $identity_uuid );
	}

	public function reassign_to_cluster( string $identity_uuid, string $target_cluster_uuid ): int {
		return $this->curation_writer->reassign_to_cluster( $identity_uuid, $target_cluster_uuid );
	}

	public function assign_to_cluster_for_projection( string $identity_uuid, string $target_cluster_uuid, int $projection_version ): int {
		return $this->snapshot_merger->assign_to_cluster_for_projection( $identity_uuid, $target_cluster_uuid, $projection_version );
	}

	public function reassign_cluster_members( string $source_cluster_uuid, string $target_cluster_uuid ): int {
		return $this->curation_writer->reassign_cluster_members( $source_cluster_uuid, $target_cluster_uuid );
	}

	public function count_for_cluster( string $cluster_uuid ): int {
		return $this->read_repository->count_for_cluster( $cluster_uuid );
	}

	public function find_by_identity_uuid( string $identity_uuid ): ?array {
		return $this->read_repository->find_by_identity_uuid( $identity_uuid );
	}

	/**
	 * @return array<string,array<string,mixed>>
	 */
	public function get_curated_members_for_tenant( string $tenant_id ): array {
		return $this->read_repository->get_curated_members_for_tenant( $tenant_id );
	}

	public function reset_curation( string $identity_uuid, string $tenant_id ): int {
		return $this->curation_writer->reset_curation( $identity_uuid, $tenant_id );
	}

	public function delete_member( string $identity_uuid, string $tenant_id ): int {
		return $this->deletion_service->delete_member( $identity_uuid, $tenant_id );
	}

	public function accept_machine_cluster_assignment( string $identity_uuid, string $cluster_uuid, string $tenant_id ): int {
		return $this->curation_writer->accept_machine_cluster_assignment( $identity_uuid, $cluster_uuid, $tenant_id );
	}
}
