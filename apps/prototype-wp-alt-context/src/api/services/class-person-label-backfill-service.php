<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/class-person-resolution-service.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';
require_once __DIR__ . '/../../sovereign/repositories/trait-prepares-sql-queries.php';

use AltContext\Support\DetectsSystemDefinedLabels;
use AltContext\Sovereign\Repositories\PreparesSqlQueries;

use function array_values;
use function current_time;
use function is_array;
use function is_numeric;
use function is_object;
use function is_string;
use function is_wp_error;
use function max;
use function method_exists;
use function min;
use function trim;

/**
 * Idempotent heal: bind persons for human-labelled clusters that have no person_id.
 */
class PersonLabelBackfillService {
	use DetectsSystemDefinedLabels;
	use PreparesSqlQueries;

	public const BATCH_SIZE = 100;
	public const MAX_STALLS = 3;

	/**
	 * @return array{bound:int,examined:int,stalls:int,stalled:bool}
	 */
	public function backfill_tenant( string $tenant_id, int $batch_size = self::BATCH_SIZE ): array {
		$normalized_tenant = trim( $tenant_id );
		$bound             = 0;
		$examined          = 0;
		$stalls            = 0;
		$stalled           = false;
		$seen              = array();
		$limit             = max( 1, min( $batch_size, self::BATCH_SIZE ) );

		if ( '' === $normalized_tenant ) {
			return array(
				'bound'    => 0,
				'examined' => 0,
				'stalls'   => 0,
				'stalled'  => false,
			);
		}

		while ( true ) {
			$rows = $this->list_unbound_human_labels( $normalized_tenant, $limit );
			if ( array() === $rows ) {
				break;
			}

			$fresh = array();
			foreach ( $rows as $row ) {
				$cluster_uuid = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
				if ( '' === $cluster_uuid || isset( $seen[ $cluster_uuid ] ) ) {
					continue;
				}
				$fresh[] = $row;
			}

			if ( array() === $fresh ) {
				break;
			}

			$examined   += count( $fresh );
			$batch_bound = 0;
			foreach ( $fresh as $row ) {
				$cluster_uuid = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
				if ( $this->bind_row( $row ) ) {
					$seen[ $cluster_uuid ] = true;
					++$batch_bound;
				}
			}

			$bound += $batch_bound;
			if ( 0 === $batch_bound ) {
				++$stalls;
				if ( $stalls >= self::MAX_STALLS ) {
					$stalled = true;
					break;
				}
			} else {
				$stalls = 0;
			}
		}

		return array(
			'bound'    => $bound,
			'examined' => $examined,
			'stalls'   => $stalls,
			'stalled'  => $stalled,
		);
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function list_unbound_human_labels( string $tenant_id, int $limit ): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$table = $wpdb->prefix . 'acx_clusters';
		$sql   = $this->prepare_query(
			"SELECT cluster_uuid, label, person_id FROM %i
			WHERE tenant_id = %s
				AND person_id IS NULL
				AND label IS NOT NULL
				AND label <> ''
				AND label NOT LIKE 'cluster-%%'
			LIMIT %d",
			array( $table, $tenant_id, $limit )
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		return is_array( $rows ) ? array_values( $rows ) : array();
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function bind_row( array $row ): bool {
		global $wpdb;

		$cluster_uuid = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
		$label        = trim( (string) ( $row['label'] ?? '' ) );
		if ( '' === $cluster_uuid || '' === $label || $this->is_reserved_label_shape( $label ) ) {
			return false;
		}

		if ( is_numeric( $row['person_id'] ?? null ) && (int) $row['person_id'] > 0 ) {
			return false;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'update' ) ) {
			return false;
		}

		$resolver = new PersonResolutionService();
		$resolved = $resolver->resolve_or_create(
			$label,
			static function (): bool {
				return true;
			}
		);
		if ( is_wp_error( $resolved ) ) {
			return false;
		}

		$updated = $wpdb->update(
			$wpdb->prefix . 'acx_clusters',
			array(
				'person_id'         => $resolved['person_id'],
				'curation_state'    => 'confirmed',
				'is_user_confirmed' => 1,
				'updated_at'        => current_time( 'mysql' ),
			),
			array( 'cluster_uuid' => $cluster_uuid ),
			array( '%d', '%s', '%d', '%s' ),
			array( '%s' )
		);

		return false !== $updated;
	}
}
