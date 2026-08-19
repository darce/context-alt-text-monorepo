<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';

use AltContext\Support\DetectsSystemDefinedLabels;

use function gmdate;
use function is_int;
use function is_numeric;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function trim;

class ClusterCurationWriter {
	use DetectsSystemDefinedLabels;
	use PreparesSqlQueries;

	private string $table_name;

	public function __construct( string $table_name ) {
		$this->table_name = $table_name;
	}

	public function update_label( string $cluster_uuid, string $label, bool $mark_user_confirmed = true ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_label        = trim( $label );
		if ( '' === $normalized_cluster_uuid || '' === $normalized_label ) {
			return 0;
		}

		if ( $this->is_reserved_label_shape( $normalized_label ) ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
			'UPDATE %i SET label = %s, is_user_confirmed = %d, local_revision = local_revision + 1, updated_at = %s, suggested_label = NULL, suggested_label_source = NULL, suggested_label_confidence = NULL, suggested_target_cluster_id = NULL WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				$normalized_label,
				$mark_user_confirmed ? 1 : 0,
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$query_result = $wpdb->query( $sql );
			if ( is_int( $query_result ) ) {
				return $query_result;
			}
		}

		return 0;
	}

	public function dismiss( string $cluster_uuid ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
			'UPDATE %i SET curation_state = %s, is_user_confirmed = 1, local_revision = local_revision + 1, updated_at = %s WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				'dismissed',
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$query_result = $wpdb->query( $sql );
			if ( is_int( $query_result ) ) {
				return $query_result;
			}
		}

		return 0;
	}

	public function undismiss( string $cluster_uuid ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
			'UPDATE %i SET curation_state = %s, is_user_confirmed = 0, local_revision = local_revision + 1, updated_at = %s WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				'uncurated',
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$query_result = $wpdb->query( $sql );
			if ( is_int( $query_result ) ) {
				return $query_result;
			}
		}

		return 0;
	}

	public function update_identity_count( string $cluster_uuid, int $identity_count ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
			'UPDATE %i SET identity_count = %d, local_revision = local_revision + 1, updated_at = %s WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				max( 0, $identity_count ),
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$query_result = $wpdb->query( $sql );
			if ( is_int( $query_result ) ) {
				return $query_result;
			}
		}

		return 0;
	}

	public function adjust_identity_count( string $cluster_uuid, int $delta ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		// CON-1: apply the count change as an atomic relative delta clamped at
		// zero, so concurrent reassigns into one cluster sum instead of racing
		// on a read-modify-write of an absolute value.
		$sql = $this->prepare_query(
			'UPDATE %i SET identity_count = GREATEST(0, identity_count + %d), local_revision = local_revision + 1, updated_at = %s WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				$delta,
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$query_result = $wpdb->query( $sql );
			if ( is_int( $query_result ) ) {
				return $query_result;
			}
		}

		return 0;
	}

	public function update_representative_state( string $cluster_uuid, ?string $representative_id, bool $is_pinned, bool $is_local_curation = true ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$normalized_representative_id = is_string( $representative_id ) ? trim( $representative_id ) : '';
		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql = $this->prepare_query(
			'UPDATE %i
			SET representative_id = %s,
				is_pinned = %d,
				local_revision = local_revision + 1,
				updated_at = %s
			WHERE cluster_uuid = %s',
			array(
				$this->table_name,
				'' !== $normalized_representative_id ? $normalized_representative_id : null,
				$is_pinned ? 1 : 0,
				$now_utc,
				$normalized_cluster_uuid,
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public const BIND_ALREADY_BOUND = -1;

	/**
	 * True when the cluster is bound to the requested person (updated or already bound).
	 */
	public static function bind_succeeded( int|false $bound ): bool {
		return false !== $bound && 0 !== $bound;
	}

	/**
	 * Single bind end-state for every person-to-cluster write.
	 *
	 * User-initiated ($confirm=true): person_id + curation_state=confirmed + is_user_confirmed=1.
	 * Heal/automatic ($confirm=false): person_id only (R1-07 — do not invent user intent).
	 * Already-bound to the same person returns BIND_ALREADY_BOUND.
	 * Missing cluster row returns 0. DB failure is false.
	 *
	 * @return int|false Rows updated, 0 when no row matched, BIND_ALREADY_BOUND, or false on DB failure.
	 */
	public function bind_person_to_cluster( string $cluster_uuid, int $person_id, string $tenant_id, bool $confirm = false ): int|false {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_tenant_id    = trim( $tenant_id );
		if ( '' === $normalized_cluster_uuid || '' === $normalized_tenant_id || $person_id <= 0 ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'update' ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return false;
		}

		$existing_sql = $this->prepare_query(
			'SELECT person_id FROM %i WHERE cluster_uuid = %s AND tenant_id = %s',
			array( $this->table_name, $normalized_cluster_uuid, $normalized_tenant_id )
		);
		if ( ! is_string( $existing_sql ) || '' === $existing_sql ) {
			return false;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$existing_row = $wpdb->get_row( $existing_sql, ARRAY_A );
		if ( ! is_array( $existing_row ) ) {
			return 0;
		}

		$existing_person_id = is_numeric( $existing_row['person_id'] ?? null ) ? (int) $existing_row['person_id'] : 0;
		if ( $existing_person_id === $person_id ) {
			return self::BIND_ALREADY_BOUND;
		}

		$data = array(
			'person_id'  => $person_id,
			'updated_at' => gmdate( 'Y-m-d H:i:s' ),
		);
		$format = array( '%d', '%s' );
		if ( $confirm ) {
			$data['curation_state']    = 'confirmed';
			$data['is_user_confirmed'] = 1;
			$format[]                  = '%s';
			$format[]                  = '%d';
		}

		$updated = $wpdb->update(
			$this->table_name,
			$data,
			array(
				'cluster_uuid' => $normalized_cluster_uuid,
				'tenant_id'    => $normalized_tenant_id,
			),
			$format,
			array( '%s', '%s' )
		);

		return false === $updated ? false : (int) $updated;
	}

	/**
	 * Clear local label + person bind in one write. Returns affected rows
	 * (0 when nothing matched) or false on DB failure.
	 *
	 * @return int|false
	 */
	public function reset_curation( string $cluster_uuid, string $tenant_id ): int|false {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_tenant_id    = trim( $tenant_id );
		if ( '' === $normalized_cluster_uuid || '' === $normalized_tenant_id ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return false;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$sql     = $this->prepare_query(
			'UPDATE %i SET label_cleared_label = label, label = NULL, person_id = NULL, curation_state = %s, is_user_confirmed = 0, local_revision = local_revision + 1, label_cleared_revision = snapshot_version, updated_at = %s WHERE cluster_uuid = %s AND tenant_id = %s',
			array(
				$this->table_name,
				'uncurated',
				$now_utc,
				$normalized_cluster_uuid,
				$normalized_tenant_id,
			)
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return false;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		if ( false === $query_result ) {
			return false;
		}

		return is_int( $query_result ) ? $query_result : 0;
	}
}
