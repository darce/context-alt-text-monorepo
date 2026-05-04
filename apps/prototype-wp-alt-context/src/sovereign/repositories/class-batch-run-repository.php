<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/trait-prepares-sql-queries.php';

use WP_Error;

use function absint;
use function array_filter;
use function array_key_exists;
use function array_map;
use function array_unique;
use function count;
use function gmdate;
use function is_array;
use function is_object;
use function is_string;
use function json_decode;
use function max;
use function method_exists;
use function trim;
use function wp_json_encode;

class BatchRunRepository {
	use PreparesSqlQueries;

	private string $runs_table_name;
	private string $failures_table_name;

	public function __construct( ?string $runs_table_name = null, ?string $failures_table_name = null ) {
		global $wpdb;

		$default_runs_table     = 'wp_acx_batch_runs';
		$default_failures_table = 'wp_acx_batch_run_failures';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_runs_table     = $wpdb->prefix . 'acx_batch_runs';
			$default_failures_table = $wpdb->prefix . 'acx_batch_run_failures';
		}

		$this->runs_table_name     = $runs_table_name ?? $default_runs_table;
		$this->failures_table_name = $failures_table_name ?? $default_failures_table;
	}

	/**
	 * @param int[] $media_ids
	 * @param int[] $unreadable_media_ids
	 */
	public function record_job_submission( string $tenant_id, string $run_id, int $batch_index, int $submitted_total, string $job_id, array $media_ids, array $unreadable_media_ids ): void {
		$normalized_tenant_id = trim( $tenant_id );
		$normalized_run_id    = trim( $run_id );
		$normalized_job_id    = trim( $job_id );

		if ( '' === $normalized_tenant_id || '' === $normalized_run_id || '' === $normalized_job_id ) {
			return;
		}

		$this->in_transaction(
			function () use ( $normalized_tenant_id, $normalized_run_id, $batch_index, $submitted_total, $normalized_job_id, $media_ids, $unreadable_media_ids ): void {
				$row        = $this->get_or_create_run_row( $normalized_tenant_id, $normalized_run_id, $submitted_total );
				$child_jobs = $this->decode_child_jobs( $row['child_jobs_json'] ?? '' );
				$child_jobs[ $normalized_job_id ] = array(
					'job_id'                  => $normalized_job_id,
					'batch_index'             => max( 0, $batch_index ),
					'media_ids'               => array_values( array_map( 'absint', $media_ids ) ),
					'status'                  => 'pending',
					'last_status_observed_at' => '',
				);
				$row['child_jobs_json']          = $this->encode_child_jobs( $child_jobs );
				$row['unreadable_media_ids_json'] = $this->encode_int_list(
					$this->merge_int_lists( $this->decode_int_list( $row['unreadable_media_ids_json'] ?? '' ), $unreadable_media_ids )
				);
				$this->refresh_aggregate_fields( $row, $this->get_failure_rows( $normalized_tenant_id, $normalized_run_id ) );
				$this->persist_run_row( $row );
			}
		);
	}

	/**
	 * @param int[] $media_ids
	 * @param int[] $unreadable_media_ids
	 */
	public function record_batch_failure( string $tenant_id, string $run_id, int $batch_index, int $submitted_total, array $media_ids, WP_Error $error, array $unreadable_media_ids ): void {
		$normalized_tenant_id = trim( $tenant_id );
		$normalized_run_id    = trim( $run_id );

		if ( '' === $normalized_tenant_id || '' === $normalized_run_id ) {
			return;
		}

		$this->in_transaction(
			function () use ( $normalized_tenant_id, $normalized_run_id, $batch_index, $submitted_total, $media_ids, $error, $unreadable_media_ids ): void {
				$row = $this->get_or_create_run_row( $normalized_tenant_id, $normalized_run_id, $submitted_total );
				$this->delete_failure_row( $normalized_tenant_id, $normalized_run_id, $batch_index );
				$this->insert_failure_row(
					$normalized_tenant_id,
					$normalized_run_id,
					$batch_index,
					$media_ids,
					(string) $error->get_error_code(),
					$error->get_error_message()
				);
				$row['unreadable_media_ids_json'] = $this->encode_int_list(
					$this->merge_int_lists( $this->decode_int_list( $row['unreadable_media_ids_json'] ?? '' ), $unreadable_media_ids )
				);
				$this->refresh_aggregate_fields( $row, $this->get_failure_rows( $normalized_tenant_id, $normalized_run_id ) );
				$this->persist_run_row( $row );
			}
		);
	}

	public function record_observed_job_status( string $tenant_id, string $job_id, string $status ): void {
		$normalized_tenant_id = trim( $tenant_id );
		$normalized_job_id    = trim( $job_id );

		if ( '' === $normalized_tenant_id || '' === $normalized_job_id ) {
			return;
		}

		$run_id = $this->lookup_run_id_for_job( $normalized_tenant_id, $normalized_job_id );
		if ( '' === $run_id ) {
			return;
		}

		$this->in_transaction(
			function () use ( $normalized_tenant_id, $run_id, $normalized_job_id, $status ): void {
				$row = $this->get_run_row( $normalized_tenant_id, $run_id );
				if ( ! is_array( $row ) ) {
					return;
				}

				$child_jobs = $this->decode_child_jobs( $row['child_jobs_json'] ?? '' );
				if ( ! isset( $child_jobs[ $normalized_job_id ] ) || ! is_array( $child_jobs[ $normalized_job_id ] ) ) {
					return;
				}

				$child_jobs[ $normalized_job_id ]['status']                  = trim( $status );
				$child_jobs[ $normalized_job_id ]['last_status_observed_at'] = gmdate( 'Y-m-d H:i:s' );
				$row['child_jobs_json']                                      = $this->encode_child_jobs( $child_jobs );
				$this->refresh_aggregate_fields( $row, $this->get_failure_rows( $normalized_tenant_id, $run_id ) );
				$this->persist_run_row( $row );
			}
		);
	}

	public function get_status( string $tenant_id, string $run_id ): ?array {
		$row = $this->get_run_row( trim( $tenant_id ), trim( $run_id ) );
		if ( ! is_array( $row ) ) {
			return null;
		}

		$failures = $this->get_failure_rows( trim( $tenant_id ), trim( $run_id ) );
		$this->refresh_aggregate_fields( $row, $failures );

		return array(
			'id'                   => (string) $row['run_id'],
			'submitted_total'      => max( 0, (int) $row['submitted_total'] ),
			'accepted_total'       => max( 0, (int) $row['accepted_total'] ),
			'completed_total'      => max( 0, (int) $row['completed_total'] ),
			'failed_total'         => max( 0, (int) $row['failed_total'] ),
			'cancelled_total'      => max( 0, (int) $row['cancelled_total'] ),
			'unreadable_media_ids' => $this->decode_int_list( (string) ( $row['unreadable_media_ids_json'] ?? '' ) ),
			'failed_batches'       => array_map( array( $this, 'format_failure_row' ), $failures ),
			'child_job_ids'        => array_values( array_keys( $this->decode_child_jobs( (string) ( $row['child_jobs_json'] ?? '' ) ) ) ),
			'terminal_state'       => (bool) $row['terminal_state'],
		);
	}

	/**
	 * @return string[]
	 */
	public function get_stale_non_terminal_job_ids( string $tenant_id, string $run_id, int $max_age_seconds ): array {
		$row = $this->get_run_row( trim( $tenant_id ), trim( $run_id ) );
		if ( ! is_array( $row ) ) {
			return array();
		}

		$child_jobs = $this->decode_child_jobs( (string) ( $row['child_jobs_json'] ?? '' ) );
		$cutoff     = time() - max( 1, $max_age_seconds );
		$job_ids    = array();
		foreach ( $child_jobs as $job_id => $child_job ) {
			if ( ! is_array( $child_job ) ) {
				continue;
			}
			$status = trim( (string) ( $child_job['status'] ?? '' ) );
			if ( in_array( $status, array( 'completed', 'failed', 'cancelled', 'canceled' ), true ) ) {
				continue;
			}
			$observed_at = trim( (string) ( $child_job['last_status_observed_at'] ?? '' ) );
			if ( '' === $observed_at || strtotime( $observed_at ) <= $cutoff ) {
				$job_ids[] = (string) $job_id;
			}
		}

		return $job_ids;
	}

	public function lookup_run_id_for_job( string $tenant_id, string $job_id ): string {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_job_id    = trim( $job_id );
		if ( '' === $normalized_tenant_id || '' === $normalized_job_id ) {
			return '';
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return '';
		}

		$sql = $this->prepare_query(
			'SELECT run_id FROM %i WHERE tenant_id = %s AND child_jobs_json LIKE %s LIMIT 1',
			array(
				$this->runs_table_name,
				$normalized_tenant_id,
				'%' . $normalized_job_id . '%',
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return '';
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		return is_string( $value ) ? trim( $value ) : '';
	}

	private function get_or_create_run_row( string $tenant_id, string $run_id, int $submitted_total ): array {
		$row = $this->get_run_row( $tenant_id, $run_id );
		if ( is_array( $row ) ) {
			return $row;
		}

		$timestamp = gmdate( 'Y-m-d H:i:s' );
		return array(
			'run_id'                   => $run_id,
			'tenant_id'                => $tenant_id,
			'submitted_total'          => max( 0, $submitted_total ),
			'accepted_total'           => 0,
			'completed_total'          => 0,
			'failed_total'             => 0,
			'cancelled_total'          => 0,
			'unreadable_media_ids_json' => '[]',
			'child_jobs_json'          => '{}',
			'terminal_state'           => 0,
			'created_at'               => $timestamp,
			'updated_at'               => $timestamp,
		);
	}

	private function get_run_row( string $tenant_id, string $run_id ): ?array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return null;
		}

		$sql = $this->prepare_query(
			'SELECT * FROM %i WHERE run_id = %s AND tenant_id = %s LIMIT 1',
			array( $this->runs_table_name, $run_id, $tenant_id )
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return null;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row = $wpdb->get_row( $sql, ARRAY_A );
		return is_array( $row ) ? $row : null;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function get_failure_rows( string $tenant_id, string $run_id ): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$sql = $this->prepare_query(
			'SELECT * FROM %i WHERE run_id = %s AND tenant_id = %s ORDER BY batch_index ASC',
			array( $this->failures_table_name, $run_id, $tenant_id )
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		return is_array( $rows ) ? $rows : array();
	}

	/**
	 * @param array<string,mixed> $row
	 * @param array<int,array<string,mixed>> $failure_rows
	 */
	private function refresh_aggregate_fields( array &$row, array $failure_rows ): void {
		$child_jobs      = $this->decode_child_jobs( (string) ( $row['child_jobs_json'] ?? '' ) );
		$accepted_total  = 0;
		$completed_total = 0;
		$failed_total    = 0;
		$cancelled_total = 0;
		$all_terminal    = true;

		foreach ( $child_jobs as $child_job ) {
			if ( ! is_array( $child_job ) ) {
				continue;
			}
			$media_ids = array_values( array_filter( array_map( 'absint', is_array( $child_job['media_ids'] ?? null ) ? $child_job['media_ids'] : array() ) ) );
			$count     = count( $media_ids );
			$accepted_total += $count;
			$status = trim( (string) ( $child_job['status'] ?? '' ) );
			switch ( $status ) {
				case 'completed':
					$completed_total += $count;
					break;
				case 'failed':
					$failed_total += $count;
					break;
				case 'cancelled':
				case 'canceled':
					$cancelled_total += $count;
					break;
				default:
					$all_terminal = false;
			}
		}

		foreach ( $failure_rows as $failure_row ) {
			$failed_total += count( $this->decode_int_list( (string) ( $failure_row['media_ids_json'] ?? '' ) ) );
		}

		$submitted_total = max( 0, (int) ( $row['submitted_total'] ?? 0 ) );
		$terminal_state  = $all_terminal && ( $completed_total + $failed_total + $cancelled_total ) >= $submitted_total;

		$row['accepted_total']  = $accepted_total;
		$row['completed_total'] = $completed_total;
		$row['failed_total']    = $failed_total;
		$row['cancelled_total'] = $cancelled_total;
		$row['terminal_state']  = $terminal_state ? 1 : 0;
		$row['updated_at']      = gmdate( 'Y-m-d H:i:s' );
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function persist_run_row( array $row ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'insert' ) || ! method_exists( $wpdb, 'update' ) ) {
			return;
		}

		$existing = $this->get_run_row( (string) $row['tenant_id'], (string) $row['run_id'] );
		$data     = array(
			'tenant_id'                 => (string) $row['tenant_id'],
			'submitted_total'           => max( 0, (int) $row['submitted_total'] ),
			'accepted_total'            => max( 0, (int) $row['accepted_total'] ),
			'completed_total'           => max( 0, (int) $row['completed_total'] ),
			'failed_total'              => max( 0, (int) $row['failed_total'] ),
			'cancelled_total'           => max( 0, (int) $row['cancelled_total'] ),
			'unreadable_media_ids_json' => (string) $row['unreadable_media_ids_json'],
			'child_jobs_json'           => (string) $row['child_jobs_json'],
			'terminal_state'            => max( 0, (int) $row['terminal_state'] ),
			'updated_at'                => (string) $row['updated_at'],
		);

		if ( is_array( $existing ) ) {
			$wpdb->update( $this->runs_table_name, $data, array( 'run_id' => (string) $row['run_id'] ) );
			return;
		}

		$wpdb->insert(
			$this->runs_table_name,
			array_merge(
				array(
					'run_id'     => (string) $row['run_id'],
					'created_at' => (string) $row['created_at'],
				),
				$data
			)
		);
	}

	/**
	 * @param int[] $media_ids
	 */
	private function insert_failure_row( string $tenant_id, string $run_id, int $batch_index, array $media_ids, string $error_code, string $error_message ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'insert' ) ) {
			return;
		}

		$wpdb->insert(
			$this->failures_table_name,
			array(
				'run_id'         => $run_id,
				'tenant_id'      => $tenant_id,
				'batch_index'    => max( 0, $batch_index ),
				'media_ids_json' => $this->encode_int_list( $media_ids ),
				'error_code'     => $error_code,
				'error_message'  => $error_message,
				'created_at'     => gmdate( 'Y-m-d H:i:s' ),
			)
		);
	}

	private function delete_failure_row( string $tenant_id, string $run_id, int $batch_index ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'delete' ) ) {
			return;
		}

		$wpdb->delete(
			$this->failures_table_name,
			array(
				'run_id'      => $run_id,
				'tenant_id'   => $tenant_id,
				'batch_index' => max( 0, $batch_index ),
			)
		);
	}

	/**
	 * @param array<string,mixed> $failure_row
	 * @return array<string,mixed>
	 */
	private function format_failure_row( array $failure_row ): array {
		return array(
			'batch_index'   => max( 0, (int) ( $failure_row['batch_index'] ?? 0 ) ),
			'media_ids'     => $this->decode_int_list( (string) ( $failure_row['media_ids_json'] ?? '' ) ),
			'error_code'    => trim( (string) ( $failure_row['error_code'] ?? '' ) ),
			'error_message' => trim( (string) ( $failure_row['error_message'] ?? '' ) ),
		);
	}

	/**
	 * @return array<string,array<string,mixed>>
	 */
	private function decode_child_jobs( string $value ): array {
		$decoded = json_decode( $value, true );
		return is_array( $decoded ) ? $decoded : array();
	}

	/**
	 * @param array<string,array<string,mixed>> $child_jobs
	 */
	private function encode_child_jobs( array $child_jobs ): string {
		return (string) wp_json_encode( $child_jobs );
	}

	/**
	 * @return int[]
	 */
	private function decode_int_list( string $value ): array {
		$decoded = json_decode( $value, true );
		if ( ! is_array( $decoded ) ) {
			return array();
		}

		return array_values( array_filter( array_map( 'absint', $decoded ) ) );
	}

	/**
	 * @param int[] $values
	 */
	private function encode_int_list( array $values ): string {
		return (string) wp_json_encode( array_values( array_filter( array_map( 'absint', $values ) ) ) );
	}

	/**
	 * @param int[] $left
	 * @param int[] $right
	 * @return int[]
	 */
	private function merge_int_lists( array $left, array $right ): array {
		return array_values( array_unique( array_map( 'absint', array_filter( array_merge( $left, $right ) ) ) ) );
	}

	private function in_transaction( callable $callback ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			$callback();
			return;
		}

		$wpdb->query( 'START TRANSACTION' );
		try {
			$callback();
			$wpdb->query( 'COMMIT' );
		} catch ( \Throwable $throwable ) {
			$wpdb->query( 'ROLLBACK' );
			throw $throwable;
		}
	}
}