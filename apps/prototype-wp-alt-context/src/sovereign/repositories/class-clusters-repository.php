<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

use function absint;
use function array_filter;
use function array_map;
use function array_values;
use function count;
use function gmdate;
use function in_array;
use function is_array;
use function is_numeric;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function preg_match_all;
use function preg_replace;
use function sprintf;
use function strpos;
use function trim;

class ClustersRepository implements ClustersRepositoryInterface {
	private string $table_name;

	public function __construct( ?string $table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_clusters';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_clusters';
		}

		$this->table_name = $table_name ?? $default_table;
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 */
	public function merge_snapshot_for_tenant( string $tenant_id, array $clusters, int $snapshot_version ): void {
		global $wpdb;

		if ( '' === trim( $tenant_id ) || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$normalized_clusters = array_values(
			array_filter(
				$clusters,
				static function ( $cluster ): bool {
					return is_array( $cluster ) && '' !== trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
				}
			)
		);

		$incoming_ids = array_values(
			array_filter(
				array_map(
					static function ( array $cluster ): string {
						return trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
					},
					$normalized_clusters
				)
			)
		);

		$this->delete_stale_non_curated_rows( $tenant_id, $incoming_ids );

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		foreach ( $normalized_clusters as $cluster ) {
			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			$label       = $this->normalize_label( $cluster );
			$thumb_path  = $this->resolve_representative_thumb_path( $cluster, $cluster_uuid );
			$inserted_at = $now_utc;

			$sql = $this->prepare_query(
				'INSERT INTO %i
				(cluster_uuid, tenant_id, label, curation_state, representative_thumb_path, identity_count, snapshot_version, is_user_confirmed, created_at, updated_at, last_synced_at)
				VALUES (%s, %s, %s, %s, %s, %d, %d, %d, %s, %s, %s)
				ON DUPLICATE KEY UPDATE
					label = IF(is_user_confirmed = 1, label, VALUES(label)),
					curation_state = IF(is_user_confirmed = 1, curation_state, VALUES(curation_state)),
					is_user_confirmed = IF(is_user_confirmed = 1, is_user_confirmed, VALUES(is_user_confirmed)),
					representative_thumb_path = VALUES(representative_thumb_path),
					identity_count = VALUES(identity_count),
					snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version)),
					updated_at = VALUES(updated_at),
					last_synced_at = VALUES(last_synced_at)',
				array(
					$this->table_name,
					$cluster_uuid,
					$tenant_id,
					$label,
					$this->normalize_curation_state( $cluster ),
					$thumb_path,
					$this->resolve_identity_count( $cluster ),
					max( 0, $snapshot_version ),
					$this->resolve_user_confirmed_flag( $cluster ),
					$inserted_at,
					$now_utc,
					$now_utc,
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
	public function list_for_tenant( string $tenant_id, int $limit = 50, int $offset = 0 ): array {
		global $wpdb;

		if ( '' === trim( $tenant_id ) || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$normalized_limit  = max( 1, $limit );
		$normalized_offset = max( 0, $offset );
		$sql               = $this->prepare_query(
			'SELECT * FROM %i WHERE tenant_id = %s ORDER BY updated_at DESC LIMIT %d OFFSET %d',
			array(
				$this->table_name,
				$tenant_id,
				$normalized_limit,
				$normalized_offset,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		return is_array( $rows ) ? $rows : array();
	}

	/**
	 * @return array<string,mixed>|null
	 */
	public function find_by_uuid( string $cluster_uuid ): ?array {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT * FROM %i WHERE cluster_uuid = %s LIMIT 1',
			array(
				$this->table_name,
				$normalized_cluster_uuid,
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
	 * @param string[] $incoming_cluster_ids
	 */
	private function delete_stale_non_curated_rows( string $tenant_id, array $incoming_cluster_ids ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		if ( empty( $incoming_cluster_ids ) ) {
			$sql = $this->prepare_query(
				'DELETE FROM %i WHERE tenant_id = %s AND is_user_confirmed = 0',
				array(
					$this->table_name,
					$tenant_id,
				)
			);

			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
				$wpdb->query( $sql );
			}

			return;
		}

		$sql = $this->prepare_query(
			'DELETE FROM %i
			WHERE tenant_id = %s
				AND is_user_confirmed = 0
				AND FIND_IN_SET(cluster_uuid, %s) = 0',
			array(
				$this->table_name,
				$tenant_id,
				implode( ',', $incoming_cluster_ids ),
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$wpdb->query( $sql );
		}
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function normalize_label( array $cluster ): string {
		$label = trim( (string) ( $cluster['label'] ?? $cluster['cluster_label'] ?? '' ) );
		return $label;
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function resolve_identity_count( array $cluster ): int {
		if ( is_numeric( $cluster['identity_count'] ?? null ) ) {
			return max( 0, (int) $cluster['identity_count'] );
		}

		if ( is_array( $cluster['members'] ?? null ) ) {
			return count( $cluster['members'] );
		}

		if ( is_array( $cluster['identities'] ?? null ) ) {
			return count( $cluster['identities'] );
		}

		return 0;
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function normalize_curation_state( array $cluster ): string {
		$state = trim( (string) ( $cluster['curation_state'] ?? '' ) );
		if ( in_array( $state, array( 'uncurated', 'confirmed', 'dismissed' ), true ) ) {
			return $state;
		}

		return 'uncurated';
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function resolve_user_confirmed_flag( array $cluster ): int {
		$value = $cluster['is_user_confirmed'] ?? false;
		if ( is_bool( $value ) ) {
			return $value ? 1 : 0;
		}

		return in_array( trim( (string) $value ), array( '1', 'true', 'yes', 'on' ), true ) ? 1 : 0;
	}

	/**
	 * @param array<string,mixed> $cluster
	 */
	private function resolve_representative_thumb_path( array $cluster, string $cluster_uuid ): string {
		$explicit_path = trim( (string) ( $cluster['representative_thumb_path'] ?? '' ) );
		if ( '' !== $explicit_path ) {
			return $explicit_path;
		}

		$representative_media_id = absint( $cluster['representative_media_id'] ?? 0 );
		if ( $representative_media_id > 0 ) {
			return $this->build_thumb_key( $cluster_uuid, $representative_media_id );
		}

		$representatives = $cluster['representatives'] ?? null;
		if ( is_array( $representatives ) ) {
			foreach ( $representatives as $representative ) {
				if ( ! is_array( $representative ) ) {
					continue;
				}

				$thumb_path = trim( (string) ( $representative['thumb_path'] ?? $representative['thumbnail_path'] ?? '' ) );
				if ( '' !== $thumb_path ) {
					return $thumb_path;
				}

				$media_id = absint( $representative['media_id'] ?? 0 );
				if ( $media_id > 0 ) {
					return $this->build_thumb_key( $cluster_uuid, $media_id );
				}
			}
		}

		return '';
	}

	private function build_thumb_key( string $cluster_uuid, int $media_id ): string {
		return sprintf( 'acx://cluster/%s/media/%d', trim( $cluster_uuid ), $media_id );
	}

	/**
	 * @param array<int,mixed> $args
	 */
	private function prepare_query( string $query, array $args ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return null;
		}

		$supports_identifier_placeholders = method_exists( $wpdb, 'has_cap' ) && true === $wpdb->has_cap( 'identifier_placeholders' );
		if ( ! $supports_identifier_placeholders && false !== strpos( $query, '%i' ) ) {
			$matches = array();
			preg_match_all( '/%[sdfi]/', $query, $matches );

			$value_args = array();
			foreach ( $matches[0] as $index => $placeholder ) {
				$arg = $args[ $index ] ?? '';
				if ( '%i' === $placeholder ) {
					$query = (string) preg_replace( '/%i/', $this->escape_identifier( (string) $arg ), $query, 1 );
					continue;
				}

				$value_args[] = $arg;
			}

			$args = $value_args;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query string is assembled from fixed templates and escaped identifiers.
		$prepared = $wpdb->prepare( $query, ...$args );
		return is_string( $prepared ) && '' !== $prepared ? $prepared : null;
	}

	private function escape_identifier( string $identifier ): string {
		$sanitized = preg_replace( '/[^A-Za-z0-9_$.]/', '', $identifier );
		$value     = is_string( $sanitized ) && '' !== $sanitized ? $sanitized : 'invalid_identifier';
		return sprintf( '`%s`', $value );
	}
}
