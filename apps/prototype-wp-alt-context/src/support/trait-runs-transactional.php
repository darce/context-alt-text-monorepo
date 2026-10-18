<?php

declare(strict_types=1);

namespace AltContext\Support;

use WP_Error;

trait RunsTransactional {
	/** @var bool Tracks an open wrapper transaction; nested calls must not issue START TRANSACTION. */
	private bool $runs_transactional_active = false;

	/**
	 * Runs $operation inside a DB transaction.
	 *
	 * Preconditions (callers must respect; wrapper enforces where noted):
	 * - Do not nest run_transactional() calls. MySQL treats nested START TRANSACTION as an implicit
	 *   COMMIT of the outer transaction; the wrapper returns acx_db_error instead (no START issued).
	 * - global $wpdb must exist with a query() method; otherwise returns acx_db_error via $start_error.
	 *
	 * - START fails       → WP_Error( 'acx_db_error', $start_error, [ 'status' => 500 ] )
	 * - $operation returns WP_Error → ROLLBACK, return that WP_Error verbatim
	 * - $operation throws → ROLLBACK, rethrow
	 * - COMMIT fails      → ROLLBACK, WP_Error( 'acx_db_error', $commit_error, [ 'status' => 500 ] )
	 * - otherwise         → return $operation result unchanged
	 *
	 * @throws \Throwable Rethrown after ROLLBACK when $operation throws.
	 * @return mixed WP_Error or the callable's return value.
	 */
	private function run_transactional(
		callable $operation,
		string $start_error = 'Could not start local transaction.',
		string $commit_error = 'Could not commit local transaction.'
	) {
		global $wpdb;

		if ( $this->runs_transactional_active ) {
			return new WP_Error( 'acx_db_error', $start_error, array( 'status' => 500 ) );
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', $start_error, array( 'status' => 500 ) );
		}

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', $start_error, array( 'status' => 500 ) );
		}

		$this->runs_transactional_active = true;
		try {
			$result = $operation();
		} catch ( \Throwable $throwable ) {
			$wpdb->query( 'ROLLBACK' );
			$this->runs_transactional_active = false;
			throw $throwable;
		}
		if ( is_wp_error( $result ) ) {
			$wpdb->query( 'ROLLBACK' );
			$this->runs_transactional_active = false;
			return $result;
		}
		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			$this->runs_transactional_active = false;
			return new WP_Error( 'acx_db_error', $commit_error, array( 'status' => 500 ) );
		}
		$this->runs_transactional_active = false;
		return $result;
	}
}
