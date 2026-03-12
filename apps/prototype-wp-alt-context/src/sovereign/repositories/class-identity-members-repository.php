<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/../sync/class-conflict-repository.php';

use AltContext\Sovereign\Sync\ConflictRepository;
use function absint;
use function array_fill;
use function array_filter;
use function array_merge;
use function array_map;
use function array_unique;
use function array_values;
use function gmdate;
use function implode;
use function is_array;
use function is_numeric;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function preg_match;
use function sprintf;
use function trim;
use function wp_json_encode;

class IdentityMembersRepository implements IdentityMembersRepositoryInterface {
	use PreparesSqlQueries;

	private string $members_table_name;
	private string $clusters_table_name;
	private ConflictRepository $conflict_repository;

	public function __construct( ?string $members_table_name = null, ?string $clusters_table_name = null, ?ConflictRepository $conflict_repository = null ) {
		global $wpdb;

		$prefix = 'wp_';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$prefix = $wpdb->prefix;
		}

		$this->members_table_name  = $members_table_name ?? $prefix . 'acx_identity_members';
		$this->clusters_table_name = $clusters_table_name ?? $prefix . 'acx_clusters';
		$this->conflict_repository = $conflict_repository ?? new ConflictRepository();
	}

	/**
	 * @param array<int,array<string,mixed>> $members
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $members, int $snapshot_version ): void {
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
					return is_array( $member )
						&& '' !== trim( (string) ( $member['identity_uuid'] ?? $member['identity_id'] ?? '' ) )
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

		$curated_members = $this->get_curated_members_for_tenant( $normalized_tenant_id );
		$this->record_missing_curated_member_conflicts( $normalized_tenant_id, $curated_members, $incoming_identity_ids, $snapshot_version );

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
			if ( is_array( $existing_curated_member ) && $this->is_member_cluster_conflict( $existing_curated_member, $cluster_uuid ) ) {
				$this->record_member_cluster_reassignment_conflict( $normalized_tenant_id, $identity_uuid, $cluster_uuid, $similarity_value = $this->normalize_similarity_value( $member ), $snapshot_version, $existing_curated_member );
				continue;
			}

			$attachment_id    = absint( $member['attachment_id'] ?? $member['media_id'] ?? 0 );
			$similarity_value = $this->normalize_similarity_value( $member );
			$thumb_path       = $this->normalize_thumb_path( $member, $identity_uuid, $attachment_id );
			$bbox_json        = $this->encode_bbox_json( $member );

			$sql = $this->prepare_query(
				"INSERT INTO %i
					(identity_uuid, cluster_uuid, attachment_id, bbox_json, thumb_path, similarity, is_curated, projection_version, created_at, updated_at)
				SELECT %s, %s, %d, %s, %s, NULLIF(%s, ''), %d, %d, %s, %s
				FROM DUAL
				WHERE EXISTS (
					SELECT 1
					FROM %i c
					WHERE c.cluster_uuid = %s
						AND c.tenant_id = %s
				)
				ON DUPLICATE KEY UPDATE
					cluster_uuid = IF(is_curated = 1, cluster_uuid, VALUES(cluster_uuid)),
					attachment_id = VALUES(attachment_id),
					bbox_json = VALUES(bbox_json),
					thumb_path = VALUES(thumb_path),
					similarity = NULLIF(%s, ''),
					projection_version = IF(is_curated = 1, projection_version, VALUES(projection_version)),
					updated_at = VALUES(updated_at)",
				array(
					$this->members_table_name,
					$identity_uuid,
					$cluster_uuid,
					$attachment_id,
					$bbox_json,
					$thumb_path,
					$similarity_value,
					0,
					max( 0, $snapshot_version ),
					$now_utc,
					$now_utc,
					$this->clusters_table_name,
					$cluster_uuid,
					$normalized_tenant_id,
					$similarity_value,
				)
			);

			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
				$wpdb->query( $sql );
			}
		}
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_cluster( string $cluster_uuid, int $limit = 500, int $offset = 0, ?string $tenant_id = null ): array {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$normalized_limit  = max( 1, $limit );
		$normalized_offset = max( 0, $offset );

		// When tenant_id is provided, JOIN to clusters table for defense-in-depth
		if ( null !== $tenant_id && '' !== trim( $tenant_id ) ) {
			$sql = $this->prepare_query(
				'SELECT m.* FROM %i m
				INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
				WHERE m.cluster_uuid = %s AND c.tenant_id = %s
				ORDER BY m.updated_at DESC LIMIT %d OFFSET %d',
				array(
					$this->members_table_name,
					$this->clusters_table_name,
					$normalized_cluster_uuid,
					trim( $tenant_id ),
					$normalized_limit,
					$normalized_offset,
				)
			);
		} else {
			// Legacy path: UUID-only filtering (relies on UUID uniqueness)
			$sql = $this->prepare_query(
				'SELECT * FROM %i WHERE cluster_uuid = %s ORDER BY updated_at DESC LIMIT %d OFFSET %d',
				array(
					$this->members_table_name,
					$normalized_cluster_uuid,
					$normalized_limit,
					$normalized_offset,
				)
			);
		}

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		return is_array( $rows ) ? $rows : array();
	}

	/**
	 * @param string[] $cluster_uuids
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	public function list_for_cluster_uuids( array $cluster_uuids, int $limit_per_cluster ): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$normalized_uuids = array_values(
			array_unique(
				array_filter(
					array_map(
						static function ( $uuid ): string {
							return trim( (string) $uuid );
						},
						$cluster_uuids
					),
					static function ( string $uuid ): bool {
						return '' !== $uuid;
					}
				)
			)
		);

		if ( empty( $normalized_uuids ) ) {
			return array();
		}

		$normalized_limit = max( 1, $limit_per_cluster );
		$placeholders     = implode( ', ', array_fill( 0, count( $normalized_uuids ), '%s' ) );

		// Use ROW_NUMBER() window function to limit results per cluster
		$sql = $this->prepare_query(
			"SELECT * FROM (
				SELECT *, ROW_NUMBER() OVER (PARTITION BY cluster_uuid ORDER BY updated_at DESC) as rn
				FROM %i
				WHERE cluster_uuid IN ($placeholders)
			) subquery WHERE rn <= %d",
			array_merge(
				array( $this->members_table_name ),
				$normalized_uuids,
				array( $normalized_limit )
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );

		if ( ! is_array( $rows ) ) {
			return array();
		}

		// Group results by cluster_uuid
		$members_by_cluster = array();
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			if ( ! isset( $members_by_cluster[ $cluster_uuid ] ) ) {
				$members_by_cluster[ $cluster_uuid ] = array();
			}

			// Remove the ROW_NUMBER column before returning
			unset( $row['rn'] );
			$members_by_cluster[ $cluster_uuid ][] = $row;
		}

		return $members_by_cluster;
	}

	/**
	 * @param int[] $media_ids
	 * @return array<int,array<string,mixed>>
	 */
	public function list_for_media_ids( string $tenant_id, array $media_ids ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return array();
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$normalized_ids = array_values(
			array_unique(
				array_filter(
					array_map(
						static function ( $media_id ): int {
							return absint( $media_id );
						},
						$media_ids
					)
				)
			)
		);

		if ( empty( $normalized_ids ) ) {
			return array();
		}

		$placeholders = implode( ', ', array_fill( 0, count( $normalized_ids ), '%d' ) );
		$sql          = $this->prepare_query(
			"SELECT m.*, c.label AS cluster_label, c.curation_state, c.is_user_confirmed
			FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE c.tenant_id = %s AND m.attachment_id IN ($placeholders)
			ORDER BY m.updated_at DESC",
			array_merge(
				array(
					$this->members_table_name,
					$this->clusters_table_name,
					$normalized_tenant_id,
				),
				$normalized_ids
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		return is_array( $rows ) ? $rows : array();
	}

	public function mark_as_curated( string $identity_uuid ): int {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		if ( '' === $normalized_identity_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
			'UPDATE %i SET is_curated = 1, updated_at = %s WHERE identity_uuid = %s',
			array(
				$this->members_table_name,
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

	public function reassign_to_cluster( string $identity_uuid, string $target_cluster_uuid ): int {
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
			'UPDATE %i SET cluster_uuid = %s, is_curated = 1, updated_at = %s WHERE identity_uuid = %s',
			array(
				$this->members_table_name,
				$normalized_target_cluster_uuid,
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

	public function reassign_cluster_members( string $source_cluster_uuid, string $target_cluster_uuid ): int {
		global $wpdb;

		$normalized_source_cluster_uuid = trim( $source_cluster_uuid );
		$normalized_target_cluster_uuid = trim( $target_cluster_uuid );
		if ( '' === $normalized_source_cluster_uuid || '' === $normalized_target_cluster_uuid || $normalized_source_cluster_uuid === $normalized_target_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i SET cluster_uuid = %s, is_curated = 1, updated_at = %s WHERE cluster_uuid = %s',
			array(
				$this->members_table_name,
				$normalized_target_cluster_uuid,
				$now_utc,
				$normalized_source_cluster_uuid,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public function count_for_cluster( string $cluster_uuid ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return 0;
		}

		$sql = $this->prepare_query(
			'SELECT COUNT(*) FROM %i WHERE cluster_uuid = %s',
			array(
				$this->members_table_name,
				$normalized_cluster_uuid,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		return max( 0, (int) $value );
	}

	public function find_by_identity_uuid( string $identity_uuid ): ?array {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		if ( '' === $normalized_identity_uuid ) {
			return null;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT * FROM %i WHERE identity_uuid = %s LIMIT 1',
			array(
				$this->members_table_name,
				$normalized_identity_uuid,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row = $wpdb->get_row( $sql, ARRAY_A );
		return is_array( $row ) ? $row : null;
	}

	/**
	 * @return array<string,array<string,mixed>>
	 */
	public function get_curated_members_for_tenant( string $tenant_id ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard( __METHOD__ );
			return array();
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$sql = $this->prepare_query(
			"SELECT m.* FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE c.tenant_id = %s AND m.is_curated = 1",
			array(
				$this->members_table_name,
				$this->clusters_table_name,
				$normalized_tenant_id,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		if ( ! is_array( $rows ) ) {
			return array();
		}

		$members = array();
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			$identity_uuid = trim( (string) ( $row['identity_uuid'] ?? '' ) );
			if ( '' === $identity_uuid ) {
				continue;
			}

			$members[ $identity_uuid ] = $row;
		}

		return $members;
	}

	public function reset_curation( string $identity_uuid, string $tenant_id ): int {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_identity_uuid || '' === $normalized_tenant_id ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			SET m.is_curated = 0, m.updated_at = %s
			WHERE m.identity_uuid = %s AND c.tenant_id = %s',
			array(
				$this->members_table_name,
				$this->clusters_table_name,
				$now_utc,
				$normalized_identity_uuid,
				$normalized_tenant_id,
			)
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public function delete_member( string $identity_uuid, string $tenant_id ): int {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_identity_uuid || '' === $normalized_tenant_id ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$sql = $this->prepare_query(
			'DELETE m FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE m.identity_uuid = %s AND c.tenant_id = %s',
			array(
				$this->members_table_name,
				$this->clusters_table_name,
				$normalized_identity_uuid,
				$normalized_tenant_id,
			)
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public function accept_machine_cluster_assignment( string $identity_uuid, string $cluster_uuid, string $tenant_id ): int {
		global $wpdb;

		$normalized_identity_uuid = trim( $identity_uuid );
		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_identity_uuid || '' === $normalized_cluster_uuid || '' === $normalized_tenant_id ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i m
			INNER JOIN %i current_cluster ON current_cluster.cluster_uuid = m.cluster_uuid
			INNER JOIN %i target_cluster ON target_cluster.cluster_uuid = %s
			SET m.cluster_uuid = %s, m.is_curated = 0, m.updated_at = %s
			WHERE m.identity_uuid = %s
				AND current_cluster.tenant_id = %s
				AND target_cluster.tenant_id = %s',
			array(
				$this->members_table_name,
				$this->clusters_table_name,
				$this->clusters_table_name,
				$normalized_cluster_uuid,
				$normalized_cluster_uuid,
				$now_utc,
				$normalized_identity_uuid,
				$normalized_tenant_id,
				$normalized_tenant_id,
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

	/**
	 * @param array<string,mixed> $existing_member
	 */
	private function is_member_cluster_conflict( array $existing_member, string $incoming_cluster_uuid ): bool {
		$existing_cluster_uuid = trim( (string) ( $existing_member['cluster_uuid'] ?? '' ) );
		return '' !== $existing_cluster_uuid && $existing_cluster_uuid !== trim( $incoming_cluster_uuid );
	}

	/**
	 * @param array<string,mixed> $existing_member
	 */
	private function record_member_cluster_reassignment_conflict(
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
	private function record_missing_curated_member_conflicts( string $tenant_id, array $curated_members, array $incoming_identity_ids, int $snapshot_version ): void {
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

	/**
	 * @param array<string,mixed> $member
	 */
	private function normalize_similarity_value( array $member ): string {
		$value = $member['similarity'] ?? $member['match_similarity'] ?? null;
		if ( ! is_numeric( $value ) ) {
			return '';
		}

		return (string) (float) $value;
	}

	/**
	 * @param array<string,mixed> $member
	 */
	private function normalize_thumb_path( array $member, string $identity_uuid, int $attachment_id ): string {
		$thumb_path = trim( (string) ( $member['thumb_path'] ?? '' ) );
		if ( '' !== $thumb_path ) {
			return $thumb_path;
		}

		if ( $attachment_id > 0 ) {
			return sprintf( 'acx://identity/%s/attachment/%d', $identity_uuid, $attachment_id );
		}

		return '';
	}

	/**
	 * @param array<string,mixed> $member
	 */
	private function encode_bbox_json( array $member ): string {
		$bbox = $member['bbox'] ?? array();
		if ( ! is_array( $bbox ) ) {
			$bbox = array();
		}

		$pixels = $this->extract_pixels( $bbox );
		$normalized_bbox = $this->extract_normalized_bbox( $bbox, $member, $pixels );
		$payload = array(
			'pixels'           => $pixels,
			'normalized'       => $normalized_bbox,
			'coordinate_space' => 'original_image',
		);

		$json = wp_json_encode( $payload );
		return is_string( $json ) && '' !== $json ? $json : '{}';
	}

	/**
	 * @param array<string,mixed> $bbox
	 * @return array<string,int>
	 */
	private function extract_pixels( array $bbox ): array {
		$source = $bbox['pixels'] ?? $bbox;
		if ( ! is_array( $source ) ) {
			$source = array();
		}

		return array(
			'x'      => max( 0, absint( $source['x'] ?? 0 ) ),
			'y'      => max( 0, absint( $source['y'] ?? 0 ) ),
			'width'  => max( 0, absint( $source['width'] ?? 0 ) ),
			'height' => max( 0, absint( $source['height'] ?? 0 ) ),
		);
	}

	/**
	 * @param array<string,mixed> $bbox
	 * @param array<string,mixed> $member
	 * @param array<string,int> $pixels
	 * @return array<string,float>
	 */
	private function extract_normalized_bbox( array $bbox, array $member, array $pixels ): array {
		$normalized = $bbox['normalized'] ?? null;
		if ( is_array( $normalized )
			&& isset( $normalized['x'], $normalized['y'], $normalized['width'], $normalized['height'] )
			&& is_numeric( $normalized['x'] )
			&& is_numeric( $normalized['y'] )
			&& is_numeric( $normalized['width'] )
			&& is_numeric( $normalized['height'] )
		) {
			return array(
				'x'      => round( (float) $normalized['x'], 6 ),
				'y'      => round( (float) $normalized['y'], 6 ),
				'width'  => round( (float) $normalized['width'], 6 ),
				'height' => round( (float) $normalized['height'], 6 ),
			);
		}

		$image_width  = absint( $member['image_width'] ?? $bbox['image_width'] ?? 0 );
		$image_height = absint( $member['image_height'] ?? $bbox['image_height'] ?? 0 );

		return array(
			'x'      => $image_width > 0 ? round( $pixels['x'] / $image_width, 6 ) : 0.0,
			'y'      => $image_height > 0 ? round( $pixels['y'] / $image_height, 6 ) : 0.0,
			'width'  => $image_width > 0 ? round( $pixels['width'] / $image_width, 6 ) : 0.0,
			'height' => $image_height > 0 ? round( $pixels['height'] / $image_height, 6 ) : 0.0,
		);
	}

	/**
	 * @param string[] $candidate_ids
	 * @return string[]
	 */
	private function sanitize_uuid_list( array $candidate_ids ): array {
		$normalized_ids = array_map(
			static function ( $candidate ): string {
				return trim( (string) $candidate );
			},
			$candidate_ids
		);

		$valid_ids = array_filter(
			$normalized_ids,
			static function ( string $value ): bool {
				return '' !== $value && 1 === preg_match( '/^[A-Za-z0-9-]+$/', $value );
			}
		);

		return array_values( array_unique( $valid_ids ) );
	}
}
