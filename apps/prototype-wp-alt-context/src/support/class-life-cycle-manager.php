<?php

declare(strict_types=1);

namespace AltContext\Support;

use function defined;
use function function_exists;
use function get_option;
use function is_object;
use function is_readable;
use function method_exists;
use function time;
use function update_option;
use function wp_clear_scheduled_hook;

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

		$this->maybe_create_projection_tables();
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

	/**
	 * Create sovereign projection tables during activation.
	 *
	 * Safe to call multiple times; dbDelta performs idempotent updates.
	 */
	private function maybe_create_projection_tables(): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! isset( $wpdb->prefix ) || ! method_exists( $wpdb, 'get_charset_collate' ) ) {
			return;
		}

		if ( ! function_exists( 'dbDelta' ) ) {
			$upgrade_path = defined( 'ABSPATH' ) ? ABSPATH . 'wp-admin/includes/upgrade.php' : '';
			if ( '' === $upgrade_path || ! is_readable( $upgrade_path ) ) {
				return;
			}

			require_once $upgrade_path;

			if ( ! function_exists( 'dbDelta' ) ) {
				return;
			}
		}

		$charset_collate = $wpdb->get_charset_collate();
		$clusters_table  = $wpdb->prefix . 'acx_clusters';
		$members_table   = $wpdb->prefix . 'acx_identity_members';
		$sync_table      = $wpdb->prefix . 'acx_sync_state';

		$clusters_sql = "CREATE TABLE {$clusters_table} (
			cluster_uuid varchar(64) NOT NULL,
			tenant_id varchar(64) NOT NULL,
			label text NULL,
			curation_state varchar(20) NOT NULL,
			representative_thumb_path text NULL,
			identity_count int(11) unsigned NOT NULL DEFAULT 0,
			snapshot_version bigint(20) unsigned NOT NULL,
			is_user_confirmed tinyint(1) NOT NULL DEFAULT 0,
			created_at datetime NOT NULL,
			updated_at datetime NOT NULL,
			last_synced_at datetime NOT NULL,
			PRIMARY KEY  (cluster_uuid),
			KEY tenant_snapshot (tenant_id, snapshot_version),
			KEY tenant_confirmed (tenant_id, is_user_confirmed)
		) {$charset_collate};";

		$members_sql = "CREATE TABLE {$members_table} (
			identity_uuid varchar(64) NOT NULL,
			cluster_uuid varchar(64) NOT NULL,
			attachment_id bigint(20) unsigned NOT NULL,
			bbox_json longtext NOT NULL,
			thumb_path text NULL,
			similarity double NULL,
			created_at datetime NOT NULL,
			updated_at datetime NOT NULL,
			PRIMARY KEY  (identity_uuid),
			KEY cluster_identity (cluster_uuid, identity_uuid),
			KEY attachment_lookup (attachment_id)
		) {$charset_collate};";

		$sync_sql = "CREATE TABLE {$sync_table} (
			stream_name varchar(100) NOT NULL,
			last_snapshot_version bigint(20) unsigned NOT NULL DEFAULT 0,
			updated_at datetime NOT NULL,
			PRIMARY KEY  (stream_name)
		) {$charset_collate};";

		dbDelta( $clusters_sql );
		dbDelta( $members_sql );
		dbDelta( $sync_sql );
	}
}
