<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-normalizes-member-rows.php';
require_once __DIR__ . '/../sync/class-conflict-repository.php';

use AltContext\Sovereign\Sync\ConflictRepository;
use function array_fill_keys;
use function array_key_exists;
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
	 * Partition curated-member divergence against an incoming snapshot payload by
	 * conflict code, without writing anything. The projector uses this pre-count to
	 * decide storm suppression and to build the aggregate's code-partitioned entity
	 * map (E15-35 Slice 3).
	 *
	 * Presence here is intentionally cluster-qualified: a curated member counts as
	 * `curated_member_deleted` only when its identity is absent from the incoming
	 * members that carry BOTH an identity_uuid and a cluster_uuid (see the
	 * identity+cluster guard below). This deliberately mirrors the deletion surface
	 * driven by record_missing_curated_member_conflicts(): its `incoming_identity_ids`
	 * argument is built from the merger's normalized member list, which already
	 * drops cluster-less rows (IdentityMemberSnapshotMerger::merge_snapshot_for_tenant,
	 * identity+cluster filter). Keeping both surfaces on the same cluster-qualified
	 * presence set is what makes the storm pre-count agree exactly with the per-entity
	 * rows the recorder later writes — the single-pre-count-drives-suppression invariant.
	 * Do not relax this to identity-only presence on one side without doing the same on
	 * the merger's feed, or the pre-count and the recorded conflicts will diverge for
	 * incoming members that arrive with an identity but no cluster.
	 *
	 * @param array<string,array<string,mixed>> $curated_members Keyed by identity_uuid.
	 * @param array<int,array<string,mixed>> $incoming_members
	 * @return array{curated_member_deleted:string[], member_cluster_reassignment:array<string,string>}
	 *         Reassignments map identity_uuid to the incoming cluster_uuid.
	 */
	public function collect_member_divergence( array $curated_members, array $incoming_members ): array {
		$incoming_cluster_by_identity = array();
		foreach ( $incoming_members as $member ) {
			if ( ! is_array( $member ) ) {
				continue;
			}

			$identity_uuid = trim( (string) ( $member['identity_uuid'] ?? $member['identity_id'] ?? '' ) );
			$cluster_uuid  = trim( (string) ( $member['cluster_uuid'] ?? $member['cluster_id'] ?? '' ) );
			if ( '' === $identity_uuid || '' === $cluster_uuid ) {
				continue;
			}

			$incoming_cluster_by_identity[ $identity_uuid ] = $cluster_uuid;
		}

		$deleted    = array();
		$reassigned = array();
		foreach ( $curated_members as $identity_uuid => $member ) {
			if ( ! is_array( $member ) ) {
				continue;
			}

			$identity_uuid = (string) $identity_uuid;
			if ( ! array_key_exists( $identity_uuid, $incoming_cluster_by_identity ) ) {
				$deleted[] = $identity_uuid;
				continue;
			}

			if ( $this->is_member_cluster_conflict( $member, $incoming_cluster_by_identity[ $identity_uuid ] ) ) {
				$reassigned[ $identity_uuid ] = $incoming_cluster_by_identity[ $identity_uuid ];
			}
		}

		return array(
			'curated_member_deleted' => $deleted,
			'member_cluster_reassignment' => $reassigned,
		);
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
		array $existing_member,
		bool $suppress_conflict_storm = false
	): void {
		if ( $suppress_conflict_storm ) {
			return;
		}

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
	public function record_missing_curated_member_conflicts( string $tenant_id, array $curated_members, array $incoming_identity_ids, int $snapshot_version, bool $suppress_conflict_storm = false ): void {
		if ( $suppress_conflict_storm ) {
			return;
		}

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
