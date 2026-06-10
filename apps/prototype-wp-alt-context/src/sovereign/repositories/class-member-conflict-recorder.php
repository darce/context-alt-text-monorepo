<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-normalizes-member-rows.php';
require_once __DIR__ . '/../sync/class-conflict-repository.php';

use AltContext\Sovereign\Sync\ConflictRepository;
use function array_fill_keys;
use function is_array;
use function max;
use function trim;

class MemberConflictRecorder {
	use NormalizesMemberRows;

	private ConflictRepository $conflict_repository;

	public function __construct( ConflictRepository $conflict_repository ) {
		$this->conflict_repository = $conflict_repository;
	}

	/**
	 * @param array<string,mixed> $existing_member
	 */
	public function is_member_cluster_conflict( array $existing_member, string $incoming_cluster_uuid ): bool {
		$existing_cluster_uuid = trim( (string) ( $existing_member['cluster_uuid'] ?? '' ) );
		return '' !== $existing_cluster_uuid && $existing_cluster_uuid !== trim( $incoming_cluster_uuid );
	}

	/**
	 * @param array<string,mixed> $existing_member
	 */
	public function record_member_cluster_reassignment_conflict(
		string $tenant_id,
		string $identity_uuid,
		string $incoming_cluster_uuid,
		string $similarity_value,
		int $snapshot_version,
		array $existing_member
	): void {
		$this->conflict_repository->record_projection_conflict(
			$tenant_id,
			'member',
			$identity_uuid,
			'member_cluster_reassignment',
			max( 0, $snapshot_version ),
			max( 0, (int) ( $existing_member['projection_version'] ?? 0 ) ),
			0,
			array(
				'cluster_uuid' => $incoming_cluster_uuid,
				'similarity' => '' !== $similarity_value ? (float) $similarity_value : null,
			),
			array(
				'cluster_uuid' => $existing_member['cluster_uuid'] ?? null,
			)
		);
	}

	/**
	 * @param array<string,array<string,mixed>> $curated_members
	 * @param string[] $incoming_identity_ids
	 */
	public function record_missing_curated_member_conflicts( string $tenant_id, array $curated_members, array $incoming_identity_ids, int $snapshot_version ): void {
		$incoming_identity_lookup = array_fill_keys( $this->sanitize_uuid_list( $incoming_identity_ids ), true );

		foreach ( $curated_members as $identity_uuid => $member ) {
			if ( isset( $incoming_identity_lookup[ $identity_uuid ] ) || ! is_array( $member ) ) {
				continue;
			}

			$this->conflict_repository->record_projection_conflict(
				$tenant_id,
				'member',
				(string) $identity_uuid,
				'curated_member_deleted',
				max( 0, $snapshot_version ),
				max( 0, (int) ( $member['projection_version'] ?? 0 ) ),
				0,
				array(
					'identity_uuid' => (string) $identity_uuid,
					'status' => 'missing_from_snapshot',
				),
				array(
					'cluster_uuid' => $member['cluster_uuid'] ?? null,
				)
			);
		}
	}
}
