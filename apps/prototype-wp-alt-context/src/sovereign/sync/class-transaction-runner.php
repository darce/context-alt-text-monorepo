<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use function is_object;
use function method_exists;

class TransactionRunner {
	/**
	 * @template T
	 * @param callable():T $callback
	 * @return T|false
	 */
	public static function run_transactional( callable $callback ): mixed {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return false;
		}

		$started = false !== $wpdb->query( 'START TRANSACTION' );
		if ( ! $started ) {
			return false;
		}

		try {
			$result = $callback();
			if ( false === $wpdb->query( 'COMMIT' ) ) {
				$wpdb->query( 'ROLLBACK' );
				return false;
			}

			return $result;
		} catch ( \Throwable $exception ) {
			$wpdb->query( 'ROLLBACK' );
			throw $exception;
		}
	}
}