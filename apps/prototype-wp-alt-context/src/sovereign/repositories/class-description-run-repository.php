<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

use function absint;
use function array_fill_keys;
use function array_map;
use function array_values;
use function count;
use function current_time;
use function in_array;
use function is_array;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function trim;

class DescriptionRunRepository {
	private const ITEM_STATUSES = array( 'pending', 'running', 'succeeded', 'skipped', 'failed', 'retryable' );

	private string $runs_table_name;
	private string $items_table_name;

	public function __construct( ?string $runs_table_name = null, ?string $items_table_name = null ) {
		global $wpdb;

		$default_runs_table  = 'wp_acx_description_runs';
		$default_items_table = 'wp_acx_description_run_items';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_runs_table  = $wpdb->prefix . 'acx_description_runs';
			$default_items_table = $wpdb->prefix . 'acx_description_run_items';
		}

		$this->runs_table_name  = $runs_table_name ?? $default_runs_table;
		$this->items_table_name = $items_table_name ?? $default_items_table;
	}

	/**
	 * @param int[] $media_ids
	 */
	public function create_run( string $run_id, array $media_ids, int $limit, int $batch_size ): void {
		global $wpdb;

		$normalized_run_id = trim( $run_id );
		if ( '' === $normalized_run_id || ! $this->has_wpdb() ) {
			return;
		}

		$now = current_time( 'mysql' );
		$normalized_media_ids = array_values( array_unique( array_filter( array_map( 'absint', $media_ids ) ) ) );

		$wpdb->insert(
			$this->runs_table_name,
			array(
				'run_id'      => $normalized_run_id,
				'status'      => 'pending',
				'limit_count' => max( 1, $limit ),
				'batch_size'  => max( 1, $batch_size ),
				'total_items' => count( $normalized_media_ids ),
				'created_at'  => $now,
				'updated_at'  => $now,
			)
		);

		foreach ( $normalized_media_ids as $media_id ) {
			$wpdb->insert(
				$this->items_table_name,
				array(
					'run_id'     => $normalized_run_id,
					'media_id'   => $media_id,
					'status'     => 'pending',
					'attempts'   => 0,
					'created_at' => $now,
					'updated_at' => $now,
				)
			);
		}
	}

	public function update_item_status( string $run_id, int $media_id, string $status, string $error_code = '', string $error_message = '' ): void {
		global $wpdb;

		$normalized_run_id = trim( $run_id );
		$normalized_status = $this->normalize_status( $status );
		if ( '' === $normalized_run_id || $media_id <= 0 || ! $this->has_wpdb() ) {
			return;
		}

		$now = current_time( 'mysql' );
		$existing = $this->find_item_row( $normalized_run_id, $media_id );
		$attempts = max( 0, (int) ( $existing['attempts'] ?? 0 ) );
		if ( 'running' === $normalized_status ) {
			++$attempts;
		}

		$wpdb->update(
			$this->items_table_name,
			array(
				'status'            => $normalized_status,
				'error_code'        => '' === trim( $error_code ) ? null : trim( $error_code ),
				'error_message'     => '' === trim( $error_message ) ? null : trim( $error_message ),
				'attempts'          => $attempts,
				'last_attempted_at' => $now,
				'updated_at'        => $now,
			),
			array(
				'run_id'   => $normalized_run_id,
				'media_id' => $media_id,
			)
		);

		$this->refresh_run_status( $normalized_run_id );
	}

	/**
	 * @return array<string,mixed>
	 */
	public function get_run_status( string $run_id ): array {
		$normalized_run_id = trim( $run_id );
		$run = $this->find_run_row( $normalized_run_id );
		$items = $this->list_item_rows( $normalized_run_id );
		$counts = array_fill_keys( self::ITEM_STATUSES, 0 );

		foreach ( $items as $item ) {
			$status = $this->normalize_status( (string) ( $item['status'] ?? 'pending' ) );
			++$counts[ $status ];
		}

		return array(
			'run_id'      => $normalized_run_id,
			'status'      => (string) ( $run['status'] ?? 'pending' ),
			'limit'       => max( 0, (int) ( $run['limit_count'] ?? 0 ) ),
			'batch_size'  => max( 0, (int) ( $run['batch_size'] ?? 0 ) ),
			'total_items' => count( $items ),
			'counts'      => $counts,
			'items'       => array_map( array( $this, 'format_item_row' ), $items ),
		);
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_retryable_items( string $run_id ): array {
		$items = array();
		foreach ( $this->list_item_rows( trim( $run_id ) ) as $item ) {
			$status = (string) ( $item['status'] ?? '' );
			if ( in_array( $status, array( 'failed', 'retryable' ), true ) ) {
				$items[] = $this->format_item_row( $item );
			}
		}

		return $items;
	}

	private function has_wpdb(): bool {
		global $wpdb;

		return isset( $wpdb ) && is_object( $wpdb ) && method_exists( $wpdb, 'insert' ) && method_exists( $wpdb, 'update' );
	}

	private function normalize_status( string $status ): string {
		$normalized = trim( $status );
		return in_array( $normalized, self::ITEM_STATUSES, true ) ? $normalized : 'pending';
	}

	private function refresh_run_status( string $run_id ): void {
		global $wpdb;

		$items = $this->list_item_rows( $run_id );
		$status = 'pending';
		if ( array() !== $items ) {
			$status = 'succeeded';
			foreach ( $items as $item ) {
				$item_status = (string) ( $item['status'] ?? 'pending' );
				if ( in_array( $item_status, array( 'pending', 'running', 'failed', 'retryable' ), true ) ) {
					$status = 'running' === $item_status ? 'running' : 'pending';
					break;
				}
			}
		}

		$wpdb->update(
			$this->runs_table_name,
			array(
				'status'     => $status,
				'updated_at' => current_time( 'mysql' ),
			),
			array( 'run_id' => $run_id )
		);
	}

	/**
	 * @return array<string,mixed>|null
	 */
	private function find_run_row( string $run_id ): ?array {
		foreach ( $this->table_rows( $this->runs_table_name ) as $row ) {
			if ( $run_id === (string) ( $row['run_id'] ?? '' ) ) {
				return $row;
			}
		}

		return null;
	}

	/**
	 * @return array<string,mixed>|null
	 */
	private function find_item_row( string $run_id, int $media_id ): ?array {
		foreach ( $this->list_item_rows( $run_id ) as $row ) {
			if ( $media_id === (int) ( $row['media_id'] ?? 0 ) ) {
				return $row;
			}
		}

		return null;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function list_item_rows( string $run_id ): array {
		$rows = array();
		foreach ( $this->table_rows( $this->items_table_name ) as $row ) {
			if ( $run_id === (string) ( $row['run_id'] ?? '' ) ) {
				$rows[] = $row;
			}
		}

		return $rows;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function table_rows( string $table ): array {
		global $wpdb;

		if ( isset( $wpdb->tableRows[ $table ] ) && is_array( $wpdb->tableRows[ $table ] ) ) {
			return $wpdb->tableRows[ $table ];
		}

		return array();
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	private function format_item_row( array $row ): array {
		return array(
			'media_id'      => (int) ( $row['media_id'] ?? 0 ),
			'status'        => $this->normalize_status( (string) ( $row['status'] ?? 'pending' ) ),
			'error_code'    => (string) ( $row['error_code'] ?? '' ),
			'error_message' => (string) ( $row['error_message'] ?? '' ),
			'attempts'      => max( 0, (int) ( $row['attempts'] ?? 0 ) ),
		);
	}
}
