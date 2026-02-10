<?php

declare(strict_types=1);

namespace AltContext\Support;

class LifecycleManager {

	private const OPTION_VERSION      = 'acx_version';
	private const OPTION_INSTALLED_AT = 'acx_installed';
	private const SNAPSHOT_SYNC_HOOK  = 'acx_sync_pull_snapshot';
	/**
	 * Plugin-owned custom table suffixes (without WordPress prefix).
	 *
	 * @var string[]
	 */
	private const OWNED_TABLE_SUFFIXES = array(
		'acx_clusters',
		'acx_identity_members',
		'acx_sync_state',
	);

	/**
	 * Run when the plugin is activated.
	 *
	 * Stores install metadata and ensures rewrite rules are refreshed.
	 */
	public function activate(): void {
		if ( defined( 'ACX_VERSION' ) ) {
			update_option( self::OPTION_VERSION, ACX_VERSION );
		}

		if ( false === get_option( self::OPTION_INSTALLED_AT ) ) {
			update_option( self::OPTION_INSTALLED_AT, time() );
		}

		flush_rewrite_rules( false );
	}

	/**
	 * Run when the plugin is deactivated.
	 *
	 * Currently we just flush rewrite rules to remove custom routes.
	 */
	public function deactivate(): void {
		wp_clear_scheduled_hook( self::SNAPSHOT_SYNC_HOOK );
		flush_rewrite_rules( false );
	}

	/**
	 * Run when the plugin is uninstalled.
	 *
	 * Cleans up plugin-owned persistence:
	 * - options: acx_version, acx_installed
	 * - scheduled hooks: acx_sync_pull_snapshot
	 * - custom tables: wp_acx_clusters, wp_acx_identity_members, wp_acx_sync_state
	 */
	public function uninstall(): void {
		delete_option( self::OPTION_VERSION );
		delete_option( self::OPTION_INSTALLED_AT );
		wp_clear_scheduled_hook( self::SNAPSHOT_SYNC_HOOK );
		$this->drop_tables();
		flush_rewrite_rules( false );
	}

	/**
	 * Drop plugin-owned custom tables during uninstall.
	 *
	 * This keeps create/destroy behavior symmetric as sovereign tables are added.
	 */
	private function drop_tables(): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! isset( $wpdb->prefix ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		foreach ( self::OWNED_TABLE_SUFFIXES as $table_suffix ) {
			$table_name = $wpdb->prefix . $table_suffix;
			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.PreparedSQL.NotPrepared -- Table names are fixed plugin-owned suffixes with wpdb prefix.
			$wpdb->query( "DROP TABLE IF EXISTS `{$table_name}`" );
		}
	}
}
