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
		'acx_persons',
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
		$this->migrate_legacy_roster_data();
		flush_rewrite_rules( false );
	}

	/**
	 * Migrates data from legacy WP options to custom tables.
	 *
	 * @H-PCRUD-4: Ensure data persistence during upgrade.
	 */
	private function migrate_legacy_roster_data(): void {
		$legacy_entries     = get_option( 'acx_roster_entries', array() );
		$legacy_assignments = get_option( 'acx_roster_assignments', array() );

		if ( empty( $legacy_entries ) && empty( $legacy_assignments ) ) {
			return;
		}

		global $wpdb;
		$table_persons  = $wpdb->prefix . 'acx_persons';
		$table_clusters = $wpdb->prefix . 'acx_clusters';

		// 1. Import persons
		$id_map = array(); // legacy_id -> new_db_id
		foreach ( (array) $legacy_entries as $entry ) {
			if ( ! isset( $entry['id'], $entry['name'] ) ) {
				continue;
			}

			$legacy_id = (int) $entry['id'];
			$name      = sanitize_text_field( (string) $entry['name'] );
			$tags      = isset( $entry['tags'] ) ? (array) $entry['tags'] : array();

			// Check if already exists by name to avoid duplicates
			$existing_id = $wpdb->get_var(
				$wpdb->prepare( 'SELECT id FROM %i WHERE name = %s', $table_persons, $name )
			);

			if ( $existing_id ) {
				$id_map[ $legacy_id ] = (int) $existing_id;
			} else {
				$person_uuid = wp_generate_uuid4();
				$now         = current_time( 'mysql' );
				$inserted    = $wpdb->insert(
					$table_persons,
					array(
						'person_uuid' => $person_uuid,
						'name'        => $name,
						'tags'        => wp_json_encode( $tags ),
						'created_at'  => $now,
						'updated_at'  => $now,
					)
				);
				if ( $inserted ) {
					$id_map[ $legacy_id ] = (int) $wpdb->insert_id;
				}
			}
		}

		// 2. Import assignments
		foreach ( (array) $legacy_assignments as $cluster_id => $data ) {
			$cluster_id = sanitize_text_field( (string) $cluster_id );
			$legacy_eid = isset( $data['roster_entry_id'] ) ? (int) $data['roster_entry_id'] : null;
			$new_name   = isset( $data['new_entry_name'] ) ? sanitize_text_field( (string) $data['new_entry_name'] ) : null;

			$final_person_id = null;

			if ( $legacy_eid && isset( $id_map[ $legacy_eid ] ) ) {
				$final_person_id = $id_map[ $legacy_eid ];
			} elseif ( $new_name ) {
				// Handle entry names that weren't in entries yet
				$existing_id = $wpdb->get_var(
					$wpdb->prepare( 'SELECT id FROM %i WHERE name = %s', $table_persons, $new_name )
				);
				if ( $existing_id ) {
					$final_person_id = (int) $existing_id;
				} else {
					$person_uuid = wp_generate_uuid4();
					$now         = current_time( 'mysql' );
					$inserted    = $wpdb->insert(
						$table_persons,
						array(
							'person_uuid' => $person_uuid,
							'name'        => $new_name,
							'tags'        => wp_json_encode( array() ),
							'created_at'  => $now,
							'updated_at'  => $now,
						)
					);
					if ( $inserted ) {
						$final_person_id = (int) $wpdb->insert_id;
					}
				}
			}

			if ( $final_person_id ) {
				$wpdb->update(
					$table_clusters,
					array(
						'person_id' => $final_person_id,
					),
					array( 'cluster_uuid' => $cluster_id ),
					array( '%d' ),
					array( '%s' )
				);
			}
		}

		// 3. Retire legacy options
		delete_option( 'acx_roster_entries' );
		delete_option( 'acx_roster_assignments' );
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

			/** @phpstan-ignore booleanNot.alwaysTrue */
			if ( ! function_exists( 'dbDelta' ) ) {
				return;
			}
		}

		$charset_collate = $wpdb->get_charset_collate();
		$clusters_table  = $wpdb->prefix . 'acx_clusters';
		$members_table   = $wpdb->prefix . 'acx_identity_members';
		$sync_table      = $wpdb->prefix . 'acx_sync_state';
		$persons_table   = $wpdb->prefix . 'acx_persons';

		$persons_sql = "CREATE TABLE {$persons_table} (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			person_uuid char(36) NOT NULL,
			name varchar(255) NOT NULL,
			tags text DEFAULT '',
			reference_thumb_path varchar(512) DEFAULT NULL,
			cluster_count int(11) unsigned DEFAULT 0,
			created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
			updated_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
			PRIMARY KEY  (id),
			UNIQUE KEY idx_name (name),
			UNIQUE KEY idx_person_uuid (person_uuid)
		) {$charset_collate};";

		$clusters_sql = "CREATE TABLE {$clusters_table} (
			cluster_uuid varchar(64) NOT NULL,
			tenant_id varchar(64) NOT NULL,
			label text NULL,
			curation_state varchar(20) NOT NULL,
			person_id bigint(20) unsigned DEFAULT NULL,
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

		dbDelta( $persons_sql );
		dbDelta( $clusters_sql );
		dbDelta( $members_sql );
		dbDelta( $sync_sql );
	}
}
