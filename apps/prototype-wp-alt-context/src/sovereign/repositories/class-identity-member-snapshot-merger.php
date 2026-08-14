<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/trait-normalizes-member-rows.php';

use function absint;
use function array_filter;
use function array_fill;
use function array_map;
use function array_merge;
use function array_values;
use function gmdate;
use function implode;
use function is_array;
use function is_int;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function trim;

class IdentityMemberSnapshotMerger {
	use PreparesSqlQueries;
	use NormalizesMemberRows;

	/**
	 * B-03: stable epoch fallback for the defensive both-timestamps-missing case, so a
	 * re-merge at equal projection_version is idempotent instead of stamping a fresh now()
	 * that churns the row's ORDER BY assigned_at position each sync. datetime(6)-shaped.
	 */
	private const ASSIGNED_AT_FALLBACK_UTC = '1970-01-01 00:00:00.000000';

	private string $members_table_name;
	private string $clusters_table_name;
	private IdentityMembersReadRepository $read_repository;
	private MemberConflictRecorder $conflict_recorder;

	public function __construct(
		string $members_table_name,
		string $clusters_table_name,
		IdentityMembersReadRepository $read_repository,
		MemberConflictRecorder $conflict_recorder
	) {
		$this->members_table_name  = $members_table_name;
		$this->clusters_table_name = $clusters_table_name;
		$this->read_repository     = $read_repository;
		$this->conflict_recorder   = $conflict_recorder;
	}

	/**
	 * @param array<int,array<string,mixed>> $members
	 * @param bool $suppress_conflict_storm When true (degraded storm cycle, E15-35 Slice 3)
	 *                                      per-entity conflict recording is skipped; curated
	 *                                      rows stay protected from projection overwrites.
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $members, int $snapshot_version, bool $suppress_conflict_storm = false ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$normalized_members = array_values(
			array_filter(
				$members,
				static function ( $member ): bool {
					return '' !== trim( (string) ( $member['identity_uuid'] ?? $member['identity_id'] ?? '' ) )
						&& '' !== trim( (string) ( $member['cluster_uuid'] ?? $member['cluster_id'] ?? '' ) );
				}
			)
		);

		$incoming_identity_ids = array_values(
			array_filter(
				array_map(
					static function ( array $member ): string {
						return trim( (string) ( $member['identity_uuid'] ?? $member['identity_id'] ?? '' ) );
					},
					$normalized_members
				)
			)
		);

		$curated_members = $this->read_repository->get_curated_members_for_tenant( $normalized_tenant_id );
		$this->conflict_recorder->record_missing_curated_member_conflicts( $normalized_tenant_id, $curated_members, $incoming_identity_ids, $snapshot_version, $suppress_conflict_storm );

		$this->delete_stale_non_curated_rows( $normalized_tenant_id, $incoming_identity_ids );
		$this->delete_orphan_rows();

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		foreach ( $normalized_members as $member ) {
			$identity_uuid = trim( (string) ( $member['identity_uuid'] ?? $member['identity_id'] ?? '' ) );
			$cluster_uuid  = trim( (string) ( $member['cluster_uuid'] ?? $member['cluster_id'] ?? '' ) );
			if ( '' === $identity_uuid || '' === $cluster_uuid ) {
				continue;
			}

			$existing_curated_member = $curated_members[ $identity_uuid ] ?? null;
			if ( is_array( $existing_curated_member ) && $this->conflict_recorder->is_member_cluster_conflict( $existing_curated_member, $cluster_uuid ) ) {
				$this->conflict_recorder->record_member_cluster_reassignment_conflict(
					$normalized_tenant_id,
					$identity_uuid,
					$cluster_uuid,
					$this->normalize_similarity_value( $member ),
					$snapshot_version,
					$existing_curated_member,
					$suppress_conflict_storm
				);
				continue;
			}

			$attachment_id    = absint( $member['attachment_id'] ?? $member['media_id'] ?? 0 );
			$similarity_value = $this->normalize_similarity_value( $member );
			$similarity_threshold_value = $this->normalize_optional_float_value( $member['similarity_threshold'] ?? null );
			$thumb_path       = $this->normalize_thumb_path( $member, $identity_uuid, $attachment_id );
			$bbox_json        = $this->encode_bbox_json( $member );
			// rg-005 / DATA-15: populate assigned_at so members ORDER BY matches recognition
			// source-of-truth (assigned_at ASC, identity_uuid). Fallback is a STABLE epoch
			// (not $now_utc) so a timestamp-less re-merge is idempotent (B-03).
			$assigned_at      = $this->normalize_assigned_at( $member, self::ASSIGNED_AT_FALLBACK_UTC );

			// COR-1: gate member data on projection_version (kept monotonic via
			// GREATEST) so a stale snapshot cannot regress newer member rows.
			$sql = $this->prepare_query(
				"INSERT INTO %i
					(identity_uuid, cluster_uuid, attachment_id, bbox_json, thumb_path, similarity, similarity_threshold, is_curated, projection_version, assigned_at, created_at, updated_at)
				SELECT %s, %s, %d, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), %d, %d, %s, %s, %s
				FROM DUAL
				WHERE EXISTS (
					SELECT 1
					FROM %i c
					WHERE c.cluster_uuid = %s
						AND c.tenant_id = %s
				)
				ON DUPLICATE KEY UPDATE
					cluster_uuid = IF(is_curated = 1, cluster_uuid, VALUES(cluster_uuid)),
					attachment_id = IF(VALUES(projection_version) >= projection_version, VALUES(attachment_id), attachment_id),
					bbox_json = IF(VALUES(projection_version) >= projection_version, VALUES(bbox_json), bbox_json),
					thumb_path = IF(VALUES(projection_version) >= projection_version, VALUES(thumb_path), thumb_path),
					similarity = IF(VALUES(projection_version) >= projection_version, NULLIF(%s, ''), similarity),
					similarity_threshold = IF(VALUES(projection_version) >= projection_version, NULLIF(%s, ''), similarity_threshold),
					assigned_at = IF(VALUES(projection_version) >= projection_version, VALUES(assigned_at), assigned_at),
					projection_version = IF(is_curated = 1, projection_version, GREATEST(projection_version, VALUES(projection_version))),
					updated_at = VALUES(updated_at)",
				array(
					$this->members_table_name,
					$identity_uuid,
					$cluster_uuid,
					$attachment_id,
					$bbox_json,
					$thumb_path,
					$similarity_value,
					$similarity_threshold_value,
					0,
					max( 0, $snapshot_version ),
					$assigned_at,
					$now_utc,
					$now_utc,
					$this->clusters_table_name,
					$cluster_uuid,
					$normalized_tenant_id,
					$similarity_value,
					$similarity_threshold_value,
				)
			);

			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
				$wpdb->query( $sql );
			}
		}
	}

	public function assign_to_cluster_for_projection( string $identity_uuid, string $target_cluster_uuid, int $projection_version ): int {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		$normalized_target_cluster_uuid = trim( $target_cluster_uuid );
		if ( '' === $normalized_identity_uuid || '' === $normalized_target_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i SET cluster_uuid = %s, projection_version = GREATEST(projection_version, %d), updated_at = %s WHERE identity_uuid = %s',
			array(
				$this->members_table_name,
				$normalized_target_cluster_uuid,
				max( 0, $projection_version ),
				$now_utc,
				$normalized_identity_uuid,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	/**
	 * @param string[] $incoming_identity_ids
	 */
	private function delete_stale_non_curated_rows( string $tenant_id, array $incoming_identity_ids ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		if ( empty( $incoming_identity_ids ) ) {
			$sql = $this->prepare_query(
				"DELETE m FROM %i m
				INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
				WHERE c.tenant_id = %s
					AND c.is_user_confirmed = 0
					AND m.is_curated = 0",
				array(
					$this->members_table_name,
					$this->clusters_table_name,
					$tenant_id,
				)
			);

			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
				$wpdb->query( $sql );
			}

			return;
		}

		$valid_identity_ids = $this->sanitize_uuid_list( $incoming_identity_ids );
		if ( empty( $valid_identity_ids ) ) {
			return;
		}

		$placeholders = implode( ', ', array_fill( 0, count( $valid_identity_ids ), '%s' ) );
		$sql = $this->prepare_query(
			"DELETE m FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE c.tenant_id = %s
				AND c.is_user_confirmed = 0
				AND m.is_curated = 0
				AND m.identity_uuid NOT IN ($placeholders)",
			array_merge(
				array(
					$this->members_table_name,
					$this->clusters_table_name,
					$tenant_id,
				),
				$valid_identity_ids
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$wpdb->query( $sql );
		}
	}

	private function delete_orphan_rows(): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$sql = $this->prepare_query(
			"DELETE m FROM %i m
			LEFT JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE c.cluster_uuid IS NULL
				AND m.is_curated = 0",
			array(
				$this->members_table_name,
				$this->clusters_table_name,
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$wpdb->query( $sql );
		}
	}
}
