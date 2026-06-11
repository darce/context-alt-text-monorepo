<?php

declare(strict_types=1);

namespace AltContext\Support;

use WP_Error;

trait RunsTransactional {
	/**
	 * Runs $operation inside a DB transaction.
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
		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return new WP_Error( 'acx_db_error', $start_error, array( 'status' => 500 ) );
		}
		try {
			$result = $operation();
		} catch ( \Throwable $throwable ) {
			$wpdb->query( 'ROLLBACK' );
			throw $throwable;
		}
		if ( is_wp_error( $result ) ) {
			$wpdb->query( 'ROLLBACK' );
			return $result;
		}
		if ( false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return new WP_Error( 'acx_db_error', $commit_error, array( 'status' => 500 ) );
		}
		return $result;
	}
}
