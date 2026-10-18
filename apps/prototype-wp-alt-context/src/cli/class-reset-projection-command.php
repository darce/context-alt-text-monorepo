<?php

declare(strict_types=1);

namespace AltContext\Cli;

use function class_exists;
use function is_object;
use function method_exists;
use function sprintf;

/**
 * Reset sovereign projection tables (development only).
 *
 * Truncates wp_acx_clusters, wp_acx_identity_members, and wp_acx_sync_state.
 * Use after a backend `make reset` to reconcile split-brain state.
 *
 * @package AltContext\Cli
 */
class ResetProjectionCommand extends \WP_CLI_Command {

	/**
	 * Plugin-owned projection table suffixes (without WordPress prefix).
	 *
	 * @var string[]
	 */
	private const TABLE_SUFFIXES = array(
		'acx_clusters',
		'acx_identity_members',
		'acx_sync_state',
	);

	/**
	 * Truncate all sovereign projection tables.
	 *
	 * WARNING: This is a destructive operation that deletes all locally-cached
	 * cluster and identity member data. User curation (confirmed labels,
	 * dismissed clusters) will be lost.
	 *
	 * Run this after a backend `make reset` to bring WP in sync with the
	 * empty backend. After resetting, re-trigger recognition and sync to
	 * re-populate both sides.
	 *
	 * ## OPTIONS
	 *
	 * [--yes]
	 * : Skip the confirmation prompt.
	 *
	 * ## EXAMPLES
	 *
	 *     wp acx reset-projection --yes
	 *
	 * @param string[] $args
	 * @param array<string,mixed> $assoc_args
	 */
	public function __invoke( array $args, array $assoc_args ): void {
		if ( ! class_exists( '\\WP_CLI' ) ) {
			return;
		}

		if ( ! isset( $assoc_args['yes'] ) || ! $assoc_args['yes'] ) {
			\WP_CLI::error( 'This will DELETE all local cluster/identity projection data. Add --yes to confirm.' );
		}

		/** @var \wpdb $wpdb */
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			\WP_CLI::error( '$wpdb is not available.' );
		}

		$total_rows = 0;

		foreach ( self::TABLE_SUFFIXES as $suffix ) {
			$table_name = $wpdb->prefix . $suffix;
			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.PreparedSQL.NotPrepared -- Table names are fixed plugin-owned suffixes with wpdb prefix.
			$count = (int) $wpdb->get_var( sprintf( 'SELECT COUNT(*) FROM `%s`', $table_name ) );

			\WP_CLI::log( sprintf( '  %s: %d rows', $table_name, $count ) );
			$total_rows += $count;

			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.PreparedSQL.NotPrepared -- Table names are fixed plugin-owned suffixes with wpdb prefix.
			$wpdb->query( "TRUNCATE TABLE `{$table_name}`" );
		}

		\WP_CLI::success( sprintf( 'Projection tables reset. %d rows removed across %d tables.', $total_rows, count( self::TABLE_SUFFIXES ) ) );
	}
}
