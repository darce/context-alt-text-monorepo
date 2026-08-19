<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/class-person-resolution-service.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';
require_once __DIR__ . '/../../sovereign/repositories/trait-prepares-sql-queries.php';
require_once __DIR__ . '/../../sovereign/repositories/class-cluster-curation-writer.php';

use AltContext\Support\DetectsSystemDefinedLabels;
use AltContext\Sovereign\Repositories\ClusterCurationWriter;
use AltContext\Sovereign\Repositories\PreparesSqlQueries;

use function array_values;
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
 *
 * Heal binds person_id ONLY (does not set is_user_confirmed / curation_state).
 */
class PersonLabelBackfillService {
	use DetectsSystemDefinedLabels;
	use PreparesSqlQueries;

	public const BATCH_SIZE = 100;
	public const MAX_STALLS = 3;

	/**
	 * @return array{bound:int,created:int,persons:int,skipped:int,examined:int,collisions:int,stalls:int,stalled:bool,empty:bool}
	 */
	public function backfill_tenant( string $tenant_id, int $batch_size = self::BATCH_SIZE, bool $dry_run = false ): array {
		$normalized_tenant = trim( $tenant_id );
		$bound             = 0;
		$created           = 0;
		$skipped           = 0;
		$examined          = 0;
		$collisions        = 0;
		$stalls            = 0;
		$stalled           = false;
		$person_ids        = array();
		$seen              = array();
		$limit             = max( 1, min( $batch_size, self::BATCH_SIZE ) );

		$empty = array(
			'bound'      => 0,
			'created'    => 0,
			'persons'    => 0,
			'skipped'    => 0,
			'examined'   => 0,
			'collisions' => 0,
			'stalls'     => 0,
			'stalled'    => false,
			'empty'      => true,
		);

		if ( '' === $normalized_tenant ) {
			return $empty;
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
				$cluster_uuid          = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
				$seen[ $cluster_uuid ] = true;
				$result                = $this->bind_row( $row, $normalized_tenant, $dry_run );
				if ( 'bound' === $result['status'] ) {
					++$batch_bound;
					if ( $result['person_id'] > 0 ) {
						$person_ids[ $result['person_id'] ] = true;
					}
					if ( $result['created'] ) {
						++$created;
					}
					if ( $result['collision'] ) {
						++$collisions;
					}
				} else {
					++$skipped;
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
			'bound'      => $bound,
			'created'    => $created,
			'persons'    => count( $person_ids ),
			'skipped'    => $skipped,
			'examined'   => $examined,
			'collisions' => $collisions,
			'stalls'     => $stalls,
			'stalled'    => $stalled,
			'empty'      => 0 === $examined,
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
				AND NOT {$this->reserved_label_sql_predicate( 'label' )}
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
	 * @return array{status:string,person_id:int,created:bool,collision:bool}
	 */
	private function bind_row( array $row, string $tenant_id, bool $dry_run ): array {
		$none = array(
			'status'     => 'skipped',
			'person_id'  => 0,
			'created'    => false,
			'collision'  => false,
		);

		$cluster_uuid = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
		$label        = trim( (string) ( $row['label'] ?? '' ) );
		if ( '' === $cluster_uuid || '' === $label || $this->is_reserved_label_shape( $label ) ) {
			return $none;
		}

		if ( is_numeric( $row['person_id'] ?? null ) && (int) $row['person_id'] > 0 ) {
			return $none;
		}

		if ( $dry_run ) {
			return array(
				'status'     => 'bound',
				'person_id'  => 0,
				'created'    => false,
				'collision'  => false,
			);
		}

		global $wpdb;
		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) ) {
			return $none;
		}

		$resolver = new PersonResolutionService();
		$resolved = $resolver->resolve_for_automatic_bind(
			$label,
			$tenant_id,
			$cluster_uuid,
			static function (): bool {
				return true;
			}
		);
		if ( is_wp_error( $resolved ) ) {
			return $none;
		}

		$writer = new ClusterCurationWriter( $wpdb->prefix . 'acx_clusters' );
		$bound  = $writer->bind_person_to_cluster( $cluster_uuid, (int) $resolved['person_id'], $tenant_id, false );
		if ( false === $bound ) {
			return $none;
		}

		return array(
			'status'     => 'bound',
			'person_id'  => (int) $resolved['person_id'],
			'created'    => 'created' === $resolved['outcome'],
			'collision'  => true === ( $resolved['collision'] ?? false ),
		);
	}
}
