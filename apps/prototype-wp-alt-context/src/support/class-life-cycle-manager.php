<?php

declare(strict_types=1);

namespace AltContext\Support;

require_once __DIR__ . '/../sovereign/sync/class-outbox-drain.php';

use AltContext\Sovereign\Sync\OutboxDrain;
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
	private const OPTION_LEGACY_ROSTER_MIGRATION_CURSOR = 'acx_legacy_roster_migration_cursor';
	private const LEGACY_ROSTER_MIGRATION_HOOK = 'acx_continue_legacy_roster_migration';
	private const MAX_LEGACY_MIGRATION_CHUNK = 100;
	private const SNAPSHOT_SYNC_HOOK  = 'acx_sync_pull_snapshot';
	private const CURATION_OUTBOX_DRAIN_HOOK = 'acx_sync_drain_curation_outbox';
	private const SPLIT_TOPOLOGY_DRAIN_HOOK = 'acx_sync_drain_split_topology_commands';
	private const ACTION_SCHEDULER_GROUP = 'acx-sync';
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
		'acx_batch_runs',
		'acx_batch_run_failures',
		'acx_description_runs',
		'acx_description_run_items',
		'acx_sync_outbox',
		'acx_topology_commands',
		'acx_sync_conflicts',
	);

	public function __construct() {
		if ( function_exists( 'add_action' ) ) {
			add_action( self::LEGACY_ROSTER_MIGRATION_HOOK, array( $this, 'continue_legacy_roster_migration' ) );
		}
	}

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
	 * Apply projection-table schema upgrades when the packaged plugin version
	 * diverges from the stored acx_version option.
	 *
	 * WP-admin plugin updates (and `wp plugin install --force`) skip activation
	 * hooks, so dbDelta must also run on load. Equal versions are a strict
	 * no-op so the every-request path stays cheap. Does not run legacy roster
	 * migration or flush rewrite rules — those remain activation-only.
	 *
	 * The version is stamped only when the upgrade actually ran; if the
	 * environment guards skip dbDelta, the mismatch persists so a later
	 * request retries instead of permanently masking a missed upgrade.
	 *
	 * A mismatch includes downgrades (stored newer than code): dbDelta never
	 * drops columns, but it may narrow a changed column type on rollback.
	 */
	public function maybe_upgrade(): void {
		if ( ! defined( 'ACX_VERSION' ) ) {
			return;
		}

		$stored = get_option( self::OPTION_VERSION );
		if ( $stored === ACX_VERSION ) {
			return;
		}

		if ( ! $this->maybe_create_projection_tables() ) {
			return;
		}
		update_option( self::OPTION_VERSION, ACX_VERSION );
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
			$this->clear_legacy_roster_migration_schedule();
			delete_option( self::OPTION_LEGACY_ROSTER_MIGRATION_CURSOR );
			return;
		}

		global $wpdb;
		$table_persons  = $wpdb->prefix . 'acx_persons';
		$table_clusters = $wpdb->prefix . 'acx_clusters';
		$cursor         = $this->normalize_legacy_roster_migration_cursor( get_option( self::OPTION_LEGACY_ROSTER_MIGRATION_CURSOR, array() ) );
		$entry_offset   = $cursor['entry_offset'];
		$assignment_offset = $cursor['assignment_offset'];
		$entries_count     = \count( (array) $legacy_entries );
		$assignments_count = \count( (array) $legacy_assignments );
		$remaining         = self::MAX_LEGACY_MIGRATION_CHUNK;
		$id_map         = array();
		$migration_complete = true;

		foreach ( \array_slice( (array) $legacy_entries, $entry_offset, $remaining ) as $entry ) {
			if ( ! $this->import_legacy_roster_entry( $entry, $table_persons, $wpdb, $id_map ) ) {
				$migration_complete = false;
				break;
			}

			++$entry_offset;
			--$remaining;
		}

		if ( ! $migration_complete ) {
			$this->persist_legacy_roster_migration_cursor( $entry_offset, $assignment_offset );
			return;
		}

		if ( $entry_offset < $entries_count ) {
			$this->persist_legacy_roster_migration_cursor( $entry_offset, $assignment_offset );
			return;
		}

		$legacy_entry_names_by_id = $this->index_legacy_entry_names_by_id( (array) $legacy_entries );

		foreach ( \array_slice( (array) $legacy_assignments, $assignment_offset, $remaining, true ) as $cluster_id => $data ) {
			if ( ! $this->import_legacy_roster_assignment( $cluster_id, $data, $id_map, $legacy_entry_names_by_id, $table_persons, $table_clusters, $wpdb ) ) {
				$migration_complete = false;
				break;
			}

			++$assignment_offset;
			--$remaining;
		}

		if ( ! $migration_complete ) {
			$this->persist_legacy_roster_migration_cursor( $entry_offset, $assignment_offset );
			return;
		}

		if ( $assignment_offset < $assignments_count ) {
			$this->persist_legacy_roster_migration_cursor( $entry_offset, $assignment_offset );
			return;
		}

		$this->clear_legacy_roster_migration_schedule();
		delete_option( 'acx_roster_entries' );
		delete_option( 'acx_roster_assignments' );
		delete_option( self::OPTION_LEGACY_ROSTER_MIGRATION_CURSOR );
	}

	public function continue_legacy_roster_migration(): void {
		$this->clear_legacy_roster_migration_schedule();
		$this->migrate_legacy_roster_data();
	}

	private function import_legacy_roster_entry( mixed $entry, string $table_persons, object $wpdb, array &$id_map ): bool {
		if ( ! is_array( $entry ) || ! isset( $entry['id'], $entry['name'] ) ) {
			return true;
		}

		$legacy_id = (int) $entry['id'];
		$name      = sanitize_text_field( (string) $entry['name'] );

		if ( '' === trim( $name ) ) {
			return true;
		}

		$tags        = isset( $entry['tags'] ) ? (array) $entry['tags'] : array();
		$existing_id = $wpdb->get_var(
			$wpdb->prepare( 'SELECT id FROM %i WHERE name = %s', $table_persons, $name )
		);

		if ( $existing_id ) {
			$id_map[ $legacy_id ] = (int) $existing_id;
			return true;
		}

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

		if ( ! $inserted ) {
			return false;
		}

		$id_map[ $legacy_id ] = (int) $wpdb->insert_id;
		return true;
	}

	private function import_legacy_roster_assignment( mixed $legacy_cluster_id, mixed $data, array $id_map, array $legacy_entry_names_by_id, string $table_persons, string $table_clusters, object $wpdb ): bool {
		if ( ! \is_array( $data ) ) {
			return true;
		}

		$cluster_id = sanitize_text_field( (string) $legacy_cluster_id );
		if ( '' === \trim( $cluster_id ) ) {
			return true;
		}

		$legacy_entry_id = isset( $data['roster_entry_id'] ) ? (int) $data['roster_entry_id'] : null;
		$new_name        = isset( $data['new_entry_name'] ) ? sanitize_text_field( (string) $data['new_entry_name'] ) : '';
		$final_person_id = null;

		if ( $legacy_entry_id && isset( $id_map[ $legacy_entry_id ] ) ) {
			$final_person_id = $id_map[ $legacy_entry_id ];
		} elseif ( $legacy_entry_id && isset( $legacy_entry_names_by_id[ $legacy_entry_id ] ) ) {
			$existing_id = $wpdb->get_var(
				$wpdb->prepare( 'SELECT id FROM %i WHERE name = %s', $table_persons, $legacy_entry_names_by_id[ $legacy_entry_id ] )
			);
			if ( $existing_id ) {
				$final_person_id = (int) $existing_id;
			}
		} elseif ( '' !== \trim( $new_name ) ) {
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

				if ( ! $inserted ) {
					return false;
				}

				$final_person_id = (int) $wpdb->insert_id;
			}
		}

		if ( null === $final_person_id ) {
			return true;
		}

		$updated = $wpdb->update(
			$table_clusters,
			array(
				'person_id' => $final_person_id,
			),
			array( 'cluster_uuid' => $cluster_id ),
			array( '%d' ),
			array( '%s' )
		);

		if ( false === $updated ) {
			return false;
		}

		if ( 0 === $updated ) {
			return $this->legacy_assignment_already_imported( $cluster_id, $final_person_id, $table_clusters, $wpdb );
		}

		return true;
	}

	/**
	 * @param array<int,mixed> $legacy_entries
	 * @return array<int,string>
	 */
	private function index_legacy_entry_names_by_id( array $legacy_entries ): array {
		$names_by_id = array();

		foreach ( $legacy_entries as $entry ) {
			if ( ! \is_array( $entry ) || ! isset( $entry['id'], $entry['name'] ) ) {
				continue;
			}

			$legacy_id = (int) $entry['id'];
			$name      = sanitize_text_field( (string) $entry['name'] );
			if ( $legacy_id <= 0 || '' === \trim( $name ) ) {
				continue;
			}

			$names_by_id[ $legacy_id ] = $name;
		}

		return $names_by_id;
	}

	/**
	 * @param mixed $cursor
	 * @return array{entry_offset:int,assignment_offset:int}
	 */
	private function normalize_legacy_roster_migration_cursor( mixed $cursor ): array {
		if ( ! \is_array( $cursor ) ) {
			return array(
				'entry_offset'      => 0,
				'assignment_offset' => 0,
			);
		}

		return array(
			'entry_offset'      => \max( 0, absint( $cursor['entry_offset'] ?? 0 ) ),
			'assignment_offset' => \max( 0, absint( $cursor['assignment_offset'] ?? 0 ) ),
		);
	}

	private function persist_legacy_roster_migration_cursor( int $entry_offset, int $assignment_offset ): void {
		update_option(
			self::OPTION_LEGACY_ROSTER_MIGRATION_CURSOR,
			array(
				'entry_offset'      => $entry_offset,
				'assignment_offset' => $assignment_offset,
			)
		);

		$this->schedule_legacy_roster_migration_continuation();
	}

	private function schedule_legacy_roster_migration_continuation(): void {
		if ( function_exists( 'as_enqueue_async_action' ) ) {
			if ( false === as_next_scheduled_action( self::LEGACY_ROSTER_MIGRATION_HOOK, array(), self::ACTION_SCHEDULER_GROUP ) ) {
				as_enqueue_async_action( self::LEGACY_ROSTER_MIGRATION_HOOK, array(), self::ACTION_SCHEDULER_GROUP );
			}

			return;
		}

		if ( false === wp_next_scheduled( self::LEGACY_ROSTER_MIGRATION_HOOK, array() ) ) {
			wp_schedule_single_event( time(), self::LEGACY_ROSTER_MIGRATION_HOOK, array() );
		}
	}

	private function clear_legacy_roster_migration_schedule(): void {
		wp_clear_scheduled_hook( self::LEGACY_ROSTER_MIGRATION_HOOK, array() );

		if ( function_exists( 'as_unschedule_all_actions' ) ) {
			as_unschedule_all_actions( self::LEGACY_ROSTER_MIGRATION_HOOK, array(), self::ACTION_SCHEDULER_GROUP );
		}
	}

	private function legacy_assignment_already_imported( string $cluster_id, int $final_person_id, string $table_clusters, object $wpdb ): bool {
		$current_person_id = $wpdb->get_var(
			$wpdb->prepare( 'SELECT person_id FROM %i WHERE cluster_uuid = %s LIMIT 1', $table_clusters, $cluster_id )
		);

		return null !== $current_person_id && $final_person_id === (int) $current_person_id;
	}

	/**
	 * Run when the plugin is deactivated.
	 *
	 * Currently we just flush rewrite rules to remove custom routes.
	 */
	public function deactivate(): void {
		wp_clear_scheduled_hook( self::SNAPSHOT_SYNC_HOOK );
		$this->clear_legacy_roster_migration_schedule();
		$this->clear_curation_outbox_drain_schedule();
		$this->clear_split_topology_drain_schedule();
		OutboxDrain::clear_scheduled_purge();
		flush_rewrite_rules( false );
	}

	/**
	 * Run when the plugin is uninstalled.
	 *
	 * Cleans up plugin-owned persistence:
	 * - options: acx_version, acx_installed
	 * - scheduled hooks: acx_sync_pull_snapshot, acx_sync_drain_curation_outbox, acx_sync_drain_split_topology_commands
	 * - custom tables: wp_acx_clusters, wp_acx_identity_members, wp_acx_sync_state,
	 *   wp_acx_persons, wp_acx_sync_outbox, wp_acx_topology_commands, wp_acx_sync_conflicts
	 */
	public function uninstall(): void {
		delete_option( self::OPTION_VERSION );
		delete_option( self::OPTION_INSTALLED_AT );
		wp_clear_scheduled_hook( self::SNAPSHOT_SYNC_HOOK );
		$this->clear_legacy_roster_migration_schedule();
		$this->clear_curation_outbox_drain_schedule();
		$this->clear_split_topology_drain_schedule();
		OutboxDrain::clear_scheduled_purge();
		$this->drop_tables();
		flush_rewrite_rules( false );
	}

	private function clear_curation_outbox_drain_schedule(): void {
		wp_clear_scheduled_hook( self::CURATION_OUTBOX_DRAIN_HOOK );

		if ( function_exists( 'as_unschedule_all_actions' ) ) {
			as_unschedule_all_actions( self::CURATION_OUTBOX_DRAIN_HOOK, array(), self::ACTION_SCHEDULER_GROUP );
		}
	}

	private function clear_split_topology_drain_schedule(): void {
		wp_clear_scheduled_hook( self::SPLIT_TOPOLOGY_DRAIN_HOOK );

		if ( function_exists( 'as_unschedule_all_actions' ) ) {
			as_unschedule_all_actions( self::SPLIT_TOPOLOGY_DRAIN_HOOK, array(), self::ACTION_SCHEDULER_GROUP );
		}
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
	 *
	 * @return bool True when dbDelta ran; false when an environment guard
	 *              skipped the upgrade (callers must not mark it complete).
	 */
	private function maybe_create_projection_tables(): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! isset( $wpdb->prefix ) || ! method_exists( $wpdb, 'get_charset_collate' ) ) {
			return false;
		}

		if ( ! function_exists( 'dbDelta' ) ) {
			$upgrade_path = defined( 'ABSPATH' ) ? ABSPATH . 'wp-admin/includes/upgrade.php' : '';
			if ( '' === $upgrade_path || ! is_readable( $upgrade_path ) ) {
				return false;
			}

			require_once $upgrade_path;

			/** @phpstan-ignore booleanNot.alwaysTrue */
			if ( ! function_exists( 'dbDelta' ) ) {
				return false;
			}
		}

		$charset_collate = $wpdb->get_charset_collate();
		$clusters_table  = $wpdb->prefix . 'acx_clusters';
		$members_table   = $wpdb->prefix . 'acx_identity_members';
		$sync_table      = $wpdb->prefix . 'acx_sync_state';
		$persons_table   = $wpdb->prefix . 'acx_persons';
		$batch_runs_table = $wpdb->prefix . 'acx_batch_runs';
		$batch_failures_table = $wpdb->prefix . 'acx_batch_run_failures';
		$description_runs_table = $wpdb->prefix . 'acx_description_runs';
		$description_run_items_table = $wpdb->prefix . 'acx_description_run_items';
		$description_usage_table = $wpdb->prefix . 'acx_description_usage';
		$outbox_table    = $wpdb->prefix . 'acx_sync_outbox';
		$topology_table  = $wpdb->prefix . 'acx_topology_commands';
		$conflicts_table = $wpdb->prefix . 'acx_sync_conflicts';

		$persons_sql = "CREATE TABLE {$persons_table} (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			person_uuid char(36) NOT NULL,
			name varchar(255) NOT NULL,
			tags text DEFAULT '',
			local_revision bigint(20) unsigned NOT NULL DEFAULT 0,
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
			representative_id varchar(64) DEFAULT NULL,
			is_pinned tinyint(1) NOT NULL DEFAULT 0,
			identity_count int(11) unsigned NOT NULL DEFAULT 0,
			snapshot_version bigint(20) unsigned NOT NULL,
			is_user_confirmed tinyint(1) NOT NULL DEFAULT 0,
			local_revision bigint(20) unsigned NOT NULL DEFAULT 0,
			created_at datetime NOT NULL,
			updated_at datetime NOT NULL,
			last_synced_at datetime NOT NULL,
			suggested_label text NULL,
			suggested_label_source varchar(30) NULL,
			suggested_label_confidence varchar(12) NULL,
			suggested_target_cluster_id varchar(64) NULL,
			PRIMARY KEY  (cluster_uuid),
			KEY tenant_snapshot (tenant_id, snapshot_version),
			KEY tenant_confirmed (tenant_id, is_user_confirmed),
			KEY tenant_representative (tenant_id, representative_id),
			KEY tenant_revision (tenant_id, local_revision)
		) {$charset_collate};";

		// rg-005 / CON-11 / CON-12: assigned_at is the recognition source-of-truth
		// membership-order key (ORDER BY assigned_at ASC, identity_uuid). Greenfield —
		// no migration; CREATE TABLE is authoritative after wipe-on-deploy.
		$members_sql = "CREATE TABLE {$members_table} (
			identity_uuid varchar(64) NOT NULL,
			cluster_uuid varchar(64) NOT NULL,
			attachment_id bigint(20) unsigned NOT NULL,
			bbox_json longtext NOT NULL,
			thumb_path text NULL,
			similarity double NULL,
			similarity_threshold double NULL,
			is_curated tinyint(1) NOT NULL DEFAULT 0,
			projection_version bigint(20) unsigned NOT NULL DEFAULT 0,
			assigned_at datetime NOT NULL,
			created_at datetime NOT NULL,
			updated_at datetime NOT NULL,
			PRIMARY KEY  (identity_uuid),
			KEY cluster_identity (cluster_uuid, identity_uuid),
			KEY attachment_lookup (attachment_id)
		) {$charset_collate};";

		$sync_sql = "CREATE TABLE {$sync_table} (
			stream_name varchar(100) NOT NULL,
			last_snapshot_version bigint(20) unsigned NOT NULL DEFAULT 0,
			last_sync_result varchar(20) NOT NULL DEFAULT 'ok',
			last_sync_attempted_at datetime DEFAULT NULL,
			pending_curation_operations int(11) unsigned NOT NULL DEFAULT 0,
			failed_curation_operations int(11) unsigned NOT NULL DEFAULT 0,
			conflict_count int(11) unsigned NOT NULL DEFAULT 0,
			last_curation_acknowledged_at datetime DEFAULT NULL,
			last_curation_conflict_at datetime DEFAULT NULL,
			last_curation_failed_at datetime DEFAULT NULL,
			updated_at datetime NOT NULL,
			PRIMARY KEY  (stream_name)
		) {$charset_collate};";

		$batch_runs_sql = "CREATE TABLE {$batch_runs_table} (
			run_id char(36) NOT NULL,
			tenant_id varchar(64) NOT NULL,
			submitted_total int(11) unsigned NOT NULL DEFAULT 0,
			accepted_total int(11) unsigned NOT NULL DEFAULT 0,
			completed_total int(11) unsigned NOT NULL DEFAULT 0,
			failed_total int(11) unsigned NOT NULL DEFAULT 0,
			cancelled_total int(11) unsigned NOT NULL DEFAULT 0,
			unreadable_media_ids_json longtext NOT NULL,
			child_jobs_json longtext NOT NULL,
			terminal_state tinyint(1) NOT NULL DEFAULT 0,
			created_at datetime NOT NULL,
			updated_at datetime NOT NULL,
			PRIMARY KEY  (run_id),
			KEY idx_tenant_created (tenant_id, created_at)
		) {$charset_collate};";

		$batch_failures_sql = "CREATE TABLE {$batch_failures_table} (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			run_id char(36) NOT NULL,
			tenant_id varchar(64) NOT NULL,
			batch_index int(11) unsigned NOT NULL DEFAULT 0,
			media_ids_json longtext NOT NULL,
			error_code varchar(64) NOT NULL,
			error_message text NOT NULL,
			created_at datetime NOT NULL,
			PRIMARY KEY  (id),
			UNIQUE KEY uq_run_batch (run_id, batch_index),
			KEY idx_tenant_run (tenant_id, run_id)
		) {$charset_collate};";

		$description_runs_sql = "CREATE TABLE {$description_runs_table} (
			run_id varchar(64) NOT NULL,
			status varchar(20) NOT NULL DEFAULT 'pending',
			limit_count int(11) unsigned NOT NULL DEFAULT 0,
			batch_size int(11) unsigned NOT NULL DEFAULT 0,
			total_items int(11) unsigned NOT NULL DEFAULT 0,
			started_at datetime DEFAULT NULL,
			completed_at datetime DEFAULT NULL,
			created_at datetime NOT NULL,
			updated_at datetime NOT NULL,
			PRIMARY KEY  (run_id),
			KEY idx_status_created (status, created_at)
		) {$charset_collate};";

		$description_run_items_sql = "CREATE TABLE {$description_run_items_table} (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			run_id varchar(64) NOT NULL,
			media_id bigint(20) unsigned NOT NULL,
			status varchar(20) NOT NULL DEFAULT 'pending',
			error_code varchar(64) DEFAULT NULL,
			error_message text DEFAULT NULL,
			attempts int(11) unsigned NOT NULL DEFAULT 0,
			last_attempted_at datetime DEFAULT NULL,
			created_at datetime NOT NULL,
			updated_at datetime NOT NULL,
			PRIMARY KEY  (id),
			UNIQUE KEY uq_run_media (run_id, media_id),
			KEY idx_run_status (run_id, status),
			KEY idx_media (media_id)
		) {$charset_collate};";

		$description_usage_sql = "CREATE TABLE {$description_usage_table} (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			occurred_at datetime NOT NULL,
			media_id bigint(20) unsigned NOT NULL DEFAULT 0,
			outcome varchar(20) NOT NULL,
			adapter varchar(64) NOT NULL DEFAULT '',
			provider varchar(64) NOT NULL DEFAULT '',
			duration_ms int(11) unsigned DEFAULT NULL,
			cached tinyint(1) NOT NULL DEFAULT 0,
			write_status varchar(64) DEFAULT NULL,
			cost_amount decimal(12,6) NOT NULL DEFAULT 0,
			cost_currency varchar(8) DEFAULT NULL,
			error_code varchar(128) DEFAULT NULL,
			error_message text DEFAULT NULL,
			retryable tinyint(1) DEFAULT NULL,
			error_source varchar(64) DEFAULT NULL,
			PRIMARY KEY  (id),
			KEY idx_outcome_occurred (outcome, occurred_at),
			KEY idx_media_occurred (media_id, occurred_at)
		) {$charset_collate};";

		$outbox_sql = "CREATE TABLE {$outbox_table} (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			tenant_id varchar(64) NOT NULL,
			operation_type varchar(64) NOT NULL,
			entity_type varchar(64) NOT NULL,
			entity_key varchar(128) NOT NULL,
			idempotency_key char(36) NOT NULL,
			expected_base_version bigint(20) unsigned NOT NULL DEFAULT 0,
			local_revision bigint(20) unsigned NOT NULL DEFAULT 0,
			payload longtext NOT NULL,
			status varchar(20) NOT NULL DEFAULT 'pending',
			attempts int(11) unsigned NOT NULL DEFAULT 0,
			last_error_code varchar(64) DEFAULT NULL,
			last_error_message text DEFAULT NULL,
			acknowledged_version bigint(20) unsigned DEFAULT NULL,
			created_at datetime NOT NULL,
			claimed_at datetime DEFAULT NULL,
			last_attempted_at datetime DEFAULT NULL,
			next_attempt_at datetime DEFAULT NULL,
			first_failed_at datetime DEFAULT NULL,
			acknowledged_at datetime DEFAULT NULL,
			PRIMARY KEY  (id),
			UNIQUE KEY uq_idempotency (idempotency_key),
			KEY idx_status_created (status, created_at),
			KEY idx_entity (entity_type, entity_key)
		) {$charset_collate};";

		$topology_sql = "CREATE TABLE {$topology_table} (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			tenant_id varchar(64) NOT NULL,
			command_type varchar(64) NOT NULL,
			entity_key varchar(128) NOT NULL,
			payload_json longtext NOT NULL,
			idempotency_key char(36) NOT NULL,
			expected_base_version bigint(20) unsigned NOT NULL DEFAULT 0,
			status varchar(20) NOT NULL DEFAULT 'pending',
			attempts int(11) unsigned NOT NULL DEFAULT 0,
			reconcile_attempts int(11) unsigned NOT NULL DEFAULT 0,
			backend_command_id varchar(128) DEFAULT NULL,
			result_json longtext DEFAULT NULL,
			projection_reconciled_at datetime DEFAULT NULL,
			last_error_code varchar(64) DEFAULT NULL,
			last_error_message text DEFAULT NULL,
			created_at datetime NOT NULL,
			updated_at datetime NOT NULL,
			claimed_at datetime DEFAULT NULL,
			last_attempted_at datetime DEFAULT NULL,
			acknowledged_at datetime DEFAULT NULL,
				PRIMARY KEY  (id),
				UNIQUE KEY uq_idempotency (idempotency_key),
				KEY idx_tenant_status (tenant_id, status),
				KEY idx_status_created (status, created_at),
				KEY idx_entity (entity_key, command_type)
			) {$charset_collate};";

		$conflicts_sql = "CREATE TABLE {$conflicts_table} (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			tenant_id varchar(64) NOT NULL,
			entity_type varchar(64) NOT NULL,
			entity_key varchar(128) NOT NULL,
			outbox_id bigint(20) unsigned NOT NULL,
			expected_base_version bigint(20) unsigned NOT NULL DEFAULT 0,
			backend_version bigint(20) unsigned NOT NULL DEFAULT 0,
			local_revision bigint(20) unsigned NOT NULL DEFAULT 0,
			conflict_code varchar(64) NOT NULL,
			backend_proposed_value text DEFAULT NULL,
			machine_payload longtext NOT NULL,
			local_payload longtext NOT NULL,
			resolution_status varchar(20) NOT NULL DEFAULT 'open',
			created_at datetime NOT NULL,
			resolved_at datetime DEFAULT NULL,
			PRIMARY KEY  (id),
			UNIQUE KEY uq_projection_conflict (tenant_id, entity_type, entity_key, conflict_code, backend_version),
			KEY idx_entity_resolution (entity_type, entity_key, resolution_status)
		) {$charset_collate};";

		dbDelta( $persons_sql );
		dbDelta( $clusters_sql );
		dbDelta( $members_sql );
		dbDelta( $sync_sql );
		dbDelta( $outbox_sql );
		dbDelta( $topology_sql );
		dbDelta( $conflicts_sql );
		dbDelta( $batch_runs_sql );
		dbDelta( $batch_failures_sql );
		dbDelta( $description_runs_sql );
		dbDelta( $description_run_items_sql );
		dbDelta( $description_usage_sql );

		return true;
	}
}
