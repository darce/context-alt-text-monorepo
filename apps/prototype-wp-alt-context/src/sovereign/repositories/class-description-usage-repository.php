<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';

use function array_key_exists;
use function array_map;
use function array_reverse;
use function array_slice;
use function array_values;
use function count;
use function gmdate;
use function is_array;
use function is_object;
use function is_string;
use function method_exists;

/**
 * Stores description usage/error events.
 */
class DescriptionUsageRepository {
	use PreparesSqlQueries;

	private string $table_name;

	public function __construct( ?string $table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_description_usage';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_description_usage';
		}

		$this->table_name = $table_name ?? $default_table;
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	public function insert( array $row ): array {
		$row = $this->with_defaults( $row );

		if ( $this->can_use_database() ) {
			global $wpdb;

			$wpdb->insert(
				$this->table_name,
				array(
					'occurred_at'   => $row['occurred_at'],
					'media_id'      => $row['media_id'],
					'outcome'       => $row['outcome'],
					'adapter'       => $row['adapter'],
					'provider'      => $row['provider'],
					'duration_ms'   => $row['duration_ms'],
					'cached'        => $row['cached'] ? 1 : 0,
					'write_status'  => $row['write_status'],
					'cost_amount'   => $row['cost_amount'],
					'cost_currency' => $row['cost_currency'],
					'error_code'    => $row['error_code'],
					'error_message' => $row['error_message'],
					'retryable'     => null === $row['retryable'] ? null : ( $row['retryable'] ? 1 : 0 ),
					'error_source'  => $row['source'],
				)
			);

			if ( isset( $wpdb->insert_id ) && (int) $wpdb->insert_id > 0 ) {
				$row['id'] = (int) $wpdb->insert_id;
			}

			return $row;
		}

		if ( ! isset( $GLOBALS['__ac_description_usage_rows'] ) || ! is_array( $GLOBALS['__ac_description_usage_rows'] ) ) {
			$GLOBALS['__ac_description_usage_rows'] = array();
		}

		$row['id'] = count( $GLOBALS['__ac_description_usage_rows'] ) + 1;
		$GLOBALS['__ac_description_usage_rows'][] = $row;

		return $row;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function all(): array {
		if ( $this->can_use_database() ) {
			$sql = $this->prepare_query(
				'SELECT * FROM %i ORDER BY occurred_at ASC',
				array( $this->table_name )
			);

			if ( ! is_string( $sql ) || '' === $sql ) {
				return array();
			}

			global $wpdb;
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$rows = $wpdb->get_results( $sql, ARRAY_A );
			return is_array( $rows ) ? array_values( array_map( array( $this, 'normalize_row' ), $rows ) ) : array();
		}

		if ( ! isset( $GLOBALS['__ac_description_usage_rows'] ) || ! is_array( $GLOBALS['__ac_description_usage_rows'] ) ) {
			return array();
		}

		return array_values( $GLOBALS['__ac_description_usage_rows'] );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function recent_errors( int $limit = 10 ): array {
		if ( $this->can_use_database() ) {
			$sql = $this->prepare_query(
				'SELECT * FROM %i WHERE outcome = %s ORDER BY occurred_at DESC LIMIT %d',
				array( $this->table_name, 'failure', $limit )
			);

			if ( ! is_string( $sql ) || '' === $sql ) {
				return array();
			}

			global $wpdb;
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$rows = $wpdb->get_results( $sql, ARRAY_A );
			return is_array( $rows ) ? array_values( array_map( array( $this, 'normalize_row' ), $rows ) ) : array();
		}

		$errors = array();
		foreach ( $this->all() as $row ) {
			if ( 'failure' === ( $row['outcome'] ?? null ) ) {
				$errors[] = $row;
			}
		}

		return array_slice( array_reverse( $errors ), 0, $limit );
	}

	private function can_use_database(): bool {
		global $wpdb;

		return isset( $wpdb )
			&& is_object( $wpdb )
			&& method_exists( $wpdb, 'insert' )
			&& method_exists( $wpdb, 'get_results' )
			&& method_exists( $wpdb, 'prepare' );
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	private function with_defaults( array $row ): array {
		return array_merge(
			array(
				'id'            => null,
				'occurred_at'   => gmdate( 'Y-m-d H:i:s' ),
				'media_id'      => 0,
				'outcome'       => 'success',
				'adapter'       => '',
				'provider'      => '',
				'duration_ms'   => null,
				'cached'        => false,
				'write_status'  => null,
				'cost_amount'   => 0.0,
				'cost_currency' => null,
				'error_code'    => null,
				'error_message' => null,
				'retryable'     => null,
				'source'        => null,
			),
			$row
		);
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	private function normalize_row( array $row ): array {
		if ( array_key_exists( 'error_source', $row ) && ! array_key_exists( 'source', $row ) ) {
			$row['source'] = $row['error_source'];
		}

		$row['media_id']    = (int) ( $row['media_id'] ?? 0 );
		$row['duration_ms'] = null === ( $row['duration_ms'] ?? null ) ? null : (int) $row['duration_ms'];
		$row['cached']      = (bool) ( $row['cached'] ?? false );
		$row['cost_amount'] = (float) ( $row['cost_amount'] ?? 0.0 );
		$row['retryable']   = null === ( $row['retryable'] ?? null ) ? null : (bool) $row['retryable'];

		return $row;
	}
}
