<?php

declare(strict_types=1);

namespace AltContext\Support;

require_once __DIR__ . '/../sovereign/sync/class-outbox-drain.php';
require_once __DIR__ . '/../api/services/class-person-resolution-service.php';
require_once __DIR__ . '/../api/services/class-person-label-backfill-service.php';
require_once __DIR__ . '/../api/class-tenant-identity.php';

use AltContext\Api\Services\PersonLabelBackfillService;
use AltContext\Api\Services\PersonResolutionService;
use AltContext\Api\TenantIdentity;
use AltContext\Sovereign\Sync\OutboxDrain;
use function array_keys;
use function defined;
use function function_exists;
use function get_debug_type;
use function get_option;
use function is_object;
use function is_readable;
use function is_string;
use function max;
use function method_exists;
use function sprintf;
use function time;
use function update_option;
use function wp_clear_scheduled_hook;

class LifecycleManager {

	private const OPTION_VERSION      = 'acx_version';
	private const OPTION_INSTALLED_AT = 'acx_installed';
	private const OPTION_SCHEMA_FINGERPRINT = 'acx_schema_fingerprint';
	private const OPTION_HEAL_COMPLETE = 'acx_label_heal_complete';
	private const OPTION_HEAL_ATTEMPTS = 'acx_label_heal_attempts';
	private const MAX_HEAL_ATTEMPTS_PER_LOAD = 1;
	private const OPTION_LEGACY_ROSTER_MIGRATION_CURSOR = 'acx_legacy_roster_migration_cursor';
	private const LEGACY_ROSTER_MIGRATION_HOOK = 'acx_continue_legacy_roster_migration';
	private const MAX_LEGACY_MIGRATION_CHUNK = 100;
	private const SNAPSHOT_SYNC_HOOK  = 'acx_sync_pull_snapshot';
	private const CURATION_OUTBOX_DRAIN_HOOK = 'acx_sync_drain_curation_outbox';
	private const SPLIT_TOPOLOGY_DRAIN_HOOK = 'acx_sync_drain_split_topology_commands';
	private const ACTION_SCHEDULER_GROUP = 'acx-sync';
	/**
	 * Epoch DEFAULT for assigned_at under STRICT_TRANS_TABLES / NO_ZERO_DATE.
	 * Matches IdentityMemberSnapshotMerger::ASSIGNED_AT_FALLBACK_UTC so ALTER TABLE
	 * ADD COLUMN against populated tables succeeds (implicit zero-date is rejected).
	 */
	private const ASSIGNED_AT_FALLBACK_UTC = '1970-01-01 00:00:00.000000';

	/**
	 * Leading tokens that are table-constraint / index definitions, not columns.
	 * Kept explicit so an unrecognised ALL-CAPS keyword fails closed (SV-06)
	 * instead of being collected as a phantom column that can never appear in
	 * SHOW COLUMNS (permanent non-stamp / every-request dbDelta loop).
	 */
	private const SCHEMA_CONSTRAINT_KEYWORDS = array(
		'PRIMARY',
		'KEY',
		'UNIQUE',
		'FULLTEXT',
		'SPATIAL',
		'INDEX',
		'CONSTRAINT',
		'FOREIGN',
		'CHECK',
	);

	/**
	 * Legacy UNIQUE on acx_persons.name from pre-E21-9 DDL. dbDelta never DROP
	 * INDEXes, so this must be removed explicitly (LO-03).
	 */
	private const LEGACY_PERSONS_NAME_UNIQUE_INDEX = 'idx_name';

	public function __construct() {
		if ( function_exists( 'add_action' ) ) {
			add_action( self::LEGACY_ROSTER_MIGRATION_HOOK, array( $this, 'continue_legacy_roster_migration' ) );
			add_action( 'admin_notices', array( $this, 'render_label_heal_notice' ) );
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

		if ( $this->maybe_create_projection_tables() ) {
			update_option( self::OPTION_SCHEMA_FINGERPRINT, $this->compute_projection_schema_fingerprint() );
		}
		$this->maybe_heal_unbound_human_labels();
		$this->migrate_legacy_roster_data();
		flush_rewrite_rules( false );
	}

	/**
	 * Apply projection-table schema upgrades when the packaged plugin version
	 * or the projection DDL fingerprint diverges from stored options.
	 *
	 * WP-admin plugin updates (and `wp plugin install --force`) skip activation
	 * hooks, so dbDelta must also run on load. Matching version AND fingerprint
	 * is a strict no-op so the every-request path stays cheap (one option read
	 * plus a hash of static DDL strings). Does not run legacy roster migration
	 * or flush rewrite rules — those remain activation-only.
	 *
	 * Version and fingerprint are stamped only when the upgrade actually ran;
	 * if the environment guards skip dbDelta, the mismatch persists so a later
	 * request retries instead of permanently masking a missed upgrade.
	 *
	 * Fingerprint gating is the durable fix for DDL edits that forget to bump
	 * ACX_VERSION (DATA-03 / DATA-04): any change to build_projection_schema_statements
	 * changes the hash and re-runs dbDelta automatically.
	 *
	 * A version mismatch includes downgrades (stored newer than code): dbDelta
	 * never drops columns, but it may narrow a changed column type on rollback.
	 */
	public function maybe_upgrade(): void {
		if ( ! defined( 'ACX_VERSION' ) ) {
			return;
		}

		$fingerprint         = $this->compute_projection_schema_fingerprint();
		$version_matches     = get_option( self::OPTION_VERSION ) === ACX_VERSION;
		$fingerprint_matches = get_option( self::OPTION_SCHEMA_FINGERPRINT ) === $fingerprint;
		if ( ! $version_matches || ! $fingerprint_matches ) {
			if ( ! $this->maybe_create_projection_tables() ) {
				// RLSE-05 / OBS-08: refuse to stamp so the next request retries.
				Telemetry::log_line(
					sprintf(
						'[acx] maybe_upgrade: projection schema apply failed; not stamping acx_version=%s or fingerprint (will retry)',
						ACX_VERSION
					)
				);
				$this->maybe_heal_unbound_human_labels();
				return;
			}
			update_option( self::OPTION_VERSION, ACX_VERSION );
			update_option( self::OPTION_SCHEMA_FINGERPRINT, $fingerprint );
		}

		$this->maybe_heal_unbound_human_labels();
	}

	public function render_label_heal_notice(): void {
		if ( '1' === (string) get_option( self::OPTION_HEAL_COMPLETE, '' ) ) {
			return;
		}

		if ( false === get_option( self::OPTION_VERSION ) ) {
			return;
		}

		echo '<div class="notice notice-warning"><p>'
			. esc_html__( 'Alt Context is still repairing unlabeled clusters. The heal will retry on the next page load.', 'alt-context' )
			. '</p></div>';
	}

	private function maybe_heal_unbound_human_labels(): void {
		if ( '1' === (string) get_option( self::OPTION_HEAL_COMPLETE, '' ) ) {
			return;
		}

		$attempts = (int) get_option( self::OPTION_HEAL_ATTEMPTS, 0 );
		if ( $attempts >= self::MAX_HEAL_ATTEMPTS_PER_LOAD ) {
			// Bounded per load (rg-007). A later request retries from zero.
			delete_option( self::OPTION_HEAL_ATTEMPTS );
		}

		update_option( self::OPTION_HEAL_ATTEMPTS, 1 );
		$this->heal_unbound_human_labels();
	}

	private function heal_unbound_human_labels(): void {
		$tenant_id = TenantIdentity::resolve()['value'] ?? '';
		if ( ! is_string( $tenant_id ) || '' === trim( $tenant_id ) ) {
			return;
		}

		$result = $this->run_label_heal( $tenant_id );
		if ( ! empty( $result['stalled'] ) ) {
			Telemetry::log_line(
				sprintf(
					'[acx] unbound-label heal stalled after %d batches; will retry on next load',
					(int) ( $result['stalls'] ?? 0 )
				)
			);
			return;
		}

		update_option( self::OPTION_HEAL_COMPLETE, '1' );
		delete_option( self::OPTION_HEAL_ATTEMPTS );
	}

	/**
	 * @return array{stalled:bool,stalls?:int}
	 */
	protected function run_label_heal( string $tenant_id ): array {
		return ( new PersonLabelBackfillService() )->backfill_tenant( $tenant_id );
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

		$tags             = isset( $entry['tags'] ) ? (array) $entry['tags'] : array();
		$normalized_name  = PersonResolutionService::normalize_name( $name );
		$existing_id      = $wpdb->get_var(
			$wpdb->prepare( 'SELECT id FROM %i WHERE normalized_name = %s', $table_persons, $normalized_name )
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
				'person_uuid'     => $person_uuid,
				'name'            => $name,
				'normalized_name' => $normalized_name,
				'tags'            => wp_json_encode( $tags ),
				'created_at'      => $now,
				'updated_at'      => $now,
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
			$legacy_name = $legacy_entry_names_by_id[ $legacy_entry_id ];
			$existing_id = $wpdb->get_var(
				$wpdb->prepare(
					'SELECT id FROM %i WHERE normalized_name = %s',
					$table_persons,
					PersonResolutionService::normalize_name( $legacy_name )
				)
			);
			if ( $existing_id ) {
				$final_person_id = (int) $existing_id;
			}
		} elseif ( '' !== \trim( $new_name ) ) {
			$normalized_name = PersonResolutionService::normalize_name( $new_name );
			$existing_id     = $wpdb->get_var(
				$wpdb->prepare( 'SELECT id FROM %i WHERE normalized_name = %s', $table_persons, $normalized_name )
			);
			if ( $existing_id ) {
				$final_person_id = (int) $existing_id;
			} else {
				$person_uuid = wp_generate_uuid4();
				$now         = current_time( 'mysql' );
				$inserted    = $wpdb->insert(
					$table_persons,
					array(
						'person_uuid'     => $person_uuid,
						'name'            => $new_name,
						'normalized_name' => $normalized_name,
						'tags'            => wp_json_encode( array() ),
						'created_at'      => $now,
						'updated_at'      => $now,
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
		delete_option( self::OPTION_SCHEMA_FINGERPRINT );
		delete_option( self::OPTION_HEAL_COMPLETE );
		delete_option( self::OPTION_HEAL_ATTEMPTS );
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
	 * Suffixes are derived from build_projection_schema_statements so create,
	 * fingerprint, and destroy share one source of truth (BR-02 / BR-09).
	 */
	private function drop_tables(): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! isset( $wpdb->prefix ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		foreach ( $this->owned_table_suffixes() as $table_suffix ) {
			$table_name = $wpdb->prefix . $table_suffix;
			// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared,WordPress.DB.PreparedSQL.NotPrepared -- Table names are fixed plugin-owned suffixes with wpdb prefix.
			$wpdb->query( "DROP TABLE IF EXISTS `{$table_name}`" );
		}
	}

	/**
	 * Plugin-owned custom table suffixes (without WordPress prefix).
	 *
	 * @return list<string>
	 */
	private function owned_table_suffixes(): array {
		return array_keys( $this->build_projection_schema_statements( '', '' ) );
	}

	/**
	 * Pure projection CREATE TABLE statements keyed by logical table name.
	 *
	 * Shared by the schema fingerprint and the dbDelta runner so DDL edits
	 * cannot drift between the two surfaces. Keys are stable table suffixes
	 * (without WordPress prefix).
	 *
	 * @return array<string, string>
	 */
	public function build_projection_schema_statements( string $prefix, string $charset_collate ): array {
		$clusters_table              = $prefix . 'acx_clusters';
		$members_table               = $prefix . 'acx_identity_members';
		$sync_table                  = $prefix . 'acx_sync_state';
		$persons_table               = $prefix . 'acx_persons';
		$batch_runs_table            = $prefix . 'acx_batch_runs';
		$batch_failures_table        = $prefix . 'acx_batch_run_failures';
		$description_runs_table      = $prefix . 'acx_description_runs';
		$description_run_items_table = $prefix . 'acx_description_run_items';
		$description_usage_table     = $prefix . 'acx_description_usage';
		$outbox_table                = $prefix . 'acx_sync_outbox';
		$topology_table              = $prefix . 'acx_topology_commands';
		$conflicts_table             = $prefix . 'acx_sync_conflicts';

		// E21-9: uniqueness is product policy via normalized_name (utf8mb4_bin), not
		// collation-folded idx_name. Greenfield — edit CREATE TABLE directly; no migration.
		$persons_sql = "CREATE TABLE {$persons_table} (
			id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
			person_uuid char(36) NOT NULL,
			tenant_id varchar(64) NOT NULL,
			name varchar(255) NOT NULL,
			normalized_name varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
			tags text DEFAULT '',
			local_revision bigint(20) unsigned NOT NULL DEFAULT 0,
			reference_thumb_path varchar(512) DEFAULT NULL,
			cluster_count int(11) unsigned DEFAULT 0,
			created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
			updated_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
			PRIMARY KEY  (id),
			UNIQUE KEY idx_normalized_name (normalized_name),
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
			label_cleared_revision bigint(20) unsigned DEFAULT NULL,
			label_cleared_label text NULL,
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

		// rg-005 / DATA-15: assigned_at is the recognition source-of-truth membership-order
		// key (ORDER BY assigned_at ASC, identity_uuid); datetime(6) preserves recognition's
		// sub-second precision so same-second members keep true order. assigned_at is stamped
		// by a single writer (recognition), so DATA-15's multi-node clock-skew failure mode
		// does not apply, and the identity_uuid secondary sort makes same-timestamp ordering
		// deterministic.
		// Explicit DEFAULT is required under STRICT_TRANS_TABLES + NO_ZERO_DATE so
		// dbDelta ALTER ADD COLUMN against populated tables does not fail (DATA-03).
		$assigned_at_default = self::ASSIGNED_AT_FALLBACK_UTC;
		$members_sql         = "CREATE TABLE {$members_table} (
			identity_uuid varchar(64) NOT NULL,
			cluster_uuid varchar(64) NOT NULL,
			attachment_id bigint(20) unsigned NOT NULL,
			bbox_json longtext NOT NULL,
			thumb_path text NULL,
			similarity double NULL,
			similarity_threshold double NULL,
			is_curated tinyint(1) NOT NULL DEFAULT 0,
			projection_version bigint(20) unsigned NOT NULL DEFAULT 0,
			assigned_at datetime(6) NOT NULL DEFAULT '{$assigned_at_default}',
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

		return array(
			'acx_persons'              => $persons_sql,
			'acx_clusters'             => $clusters_sql,
			'acx_identity_members'     => $members_sql,
			'acx_sync_state'           => $sync_sql,
			'acx_sync_outbox'          => $outbox_sql,
			'acx_topology_commands'    => $topology_sql,
			'acx_sync_conflicts'       => $conflicts_sql,
			'acx_batch_runs'           => $batch_runs_sql,
			'acx_batch_run_failures'   => $batch_failures_sql,
			'acx_description_runs'     => $description_runs_sql,
			'acx_description_run_items'=> $description_run_items_sql,
			'acx_description_usage'    => $description_usage_sql,
		);
	}

	/**
	 * sha1 of normalised projection DDL. Prefix/charset are fixed placeholders so
	 * the hash is environment-independent and cheap to recompute every request.
	 */
	public function compute_projection_schema_fingerprint(): string {
		$statements = $this->build_projection_schema_statements( '{prefix}', '{charset_collate}' );
		ksort( $statements );

		$normalized_parts = array();
		foreach ( $statements as $table => $sql ) {
			$collapsed = preg_replace( '/\s+/', ' ', trim( $sql ) );
			$normalized_parts[] = $table . "\n" . ( is_string( $collapsed ) ? $collapsed : trim( $sql ) );
		}

		return sha1( implode( "\n", $normalized_parts ) );
	}

	/**
	 * Create sovereign projection tables during activation / upgrade.
	 *
	 * Safe to call multiple times; dbDelta performs idempotent updates.
	 * Iterates the statement map directly (single source of truth with the
	 * fingerprint and uninstall drop list). Partial applies are left in place
	 * and return false so callers refuse to stamp; the next request retries.
	 *
	 * @return bool True when every statement and the assigned_at seed succeeded;
	 *              false when an environment guard skipped the run or MySQL
	 *              rejected a statement (callers must not mark complete).
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

		$statements = $this->build_projection_schema_statements(
			(string) $wpdb->prefix,
			$wpdb->get_charset_collate()
		);

		// Map insertion order is the apply order (persons before clusters, etc.).
		foreach ( $statements as $key => $sql ) {
			if ( property_exists( $wpdb, 'last_error' ) ) {
				$wpdb->last_error = '';
			}

			dbDelta( $sql );

			$error = property_exists( $wpdb, 'last_error' ) ? (string) $wpdb->last_error : '';
			if ( '' !== $error ) {
				if ( property_exists( $wpdb, 'last_error' ) ) {
					$wpdb->last_error = '';
				}
				Telemetry::log_line(
					sprintf( '[acx] schema apply failed for %s: %s', $key, $error )
				);
				return false;
			}
		}

		// LO-03: dbDelta never DROP INDEXes; remove the pre-E21-9 UNIQUE on name.
		if ( ! $this->drop_legacy_persons_name_unique_index( (string) $wpdb->prefix . 'acx_persons' ) ) {
			return false;
		}

		if ( ! $this->verify_projection_schema_columns( $statements ) ) {
			return false;
		}

		if ( ! $this->seed_assigned_at_from_created_at( (string) $wpdb->prefix . 'acx_identity_members' ) ) {
			return false;
		}

		return true;
	}

	/**
	 * Extract column names from a CREATE TABLE statement.
	 *
	 * Single grammar shared with the test dbDelta stub (SV-03) so the suite
	 * cannot tautologically agree with a second parser. Returns null when the
	 * body cannot be parsed, yields no columns, or contains an unrecognised
	 * leading keyword — empty intended sets are verifier defects (SV-01), not
	 * a perfect match against SHOW COLUMNS.
	 *
	 * @return list<string>|null
	 */
	public static function parse_create_table_column_names( string $sql ): ?array {
		$sql = trim( $sql );
		if ( ! preg_match( '/^CREATE TABLE\s+[^\s(]+\s*\((.*)\)\s*[^)]*;?$/si', $sql, $matches ) ) {
			return null;
		}

		$columns = array();
		$definitions = preg_split( '/\R/', $matches[1] );
		if ( ! is_array( $definitions ) ) {
			$definitions = array();
		}
		foreach ( $definitions as $definition ) {
			$line = trim( $definition );
			$line = rtrim( $line, ',' );
			$line = trim( $line );
			if ( '' === $line ) {
				continue;
			}

			// Plain identifier, optionally backtick-quoted, followed by type/constraint rest.
			if ( ! preg_match( '/^`([a-zA-Z_][a-zA-Z0-9_]*)`(?:\s|$)/', $line, $column_match )
				&& ! preg_match( '/^([a-zA-Z_][a-zA-Z0-9_]*)(?:\s|$)/', $line, $column_match ) ) {
				// Non-empty line that is not an identifier lead-in → unrecognised structure.
				return null;
			}

			$name       = $column_match[1];
			$name_upper = strtoupper( $name );

			if ( in_array( $name_upper, self::SCHEMA_CONSTRAINT_KEYWORDS, true ) ) {
				continue;
			}

			// Unquoted ALL-CAPS token that is not a known constraint keyword is
			// treated as an unrecognised leading keyword (fail closed, SV-06).
			// Production column names are lowercase; intentional keyword-as-column
			// would need backticks and is accepted via the backtick branch above.
			$is_backticked = str_starts_with( ltrim( $definition ), '`' );
			if ( ! $is_backticked && $name === $name_upper ) {
				return null;
			}

			$columns[] = $name;
		}

		if ( array() === $columns ) {
			return null;
		}

		return $columns;
	}

	/**
	 * @param array<string,string> $statements
	 */
	private function verify_projection_schema_columns( array $statements ): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return false;
		}

		$statement_count = count( $statements );
		$parsed_count    = 0;

		foreach ( $statements as $key => $sql ) {
			$intended_columns = self::parse_create_table_column_names( $sql );
			if ( null === $intended_columns ) {
				Telemetry::log_line(
					sprintf(
						'[acx] schema verification failed for %s: could not parse intended columns (verifier defect or unrecognised DDL structure)',
						$key
					)
				);
				return false;
			}
			++$parsed_count;

			$table = (string) $wpdb->prefix . $key;

			// Match the dbDelta probe pattern: never attribute a prior query's
			// last_error to this SHOW COLUMNS (SV-04).
			if ( property_exists( $wpdb, 'last_error' ) ) {
				$wpdb->last_error = '';
			}

			$query = method_exists( $wpdb, 'prepare' ) ? $wpdb->prepare( 'SHOW COLUMNS FROM %i', $table ) : "SHOW COLUMNS FROM `{$table}`";
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Prepared above or plugin-owned table name.
			$rows = $wpdb->get_results( $query, ARRAY_A );

			$error = property_exists( $wpdb, 'last_error' ) ? (string) $wpdb->last_error : '';
			if ( '' !== $error ) {
				if ( property_exists( $wpdb, 'last_error' ) ) {
					$wpdb->last_error = '';
				}
				Telemetry::log_line(
					sprintf( '[acx] schema verification failed for %s: SHOW COLUMNS error: %s', $table, $error )
				);
				return false;
			}

			$actual_columns = array();
			foreach ( is_array( $rows ) ? $rows : array() as $row ) {
				if ( is_array( $row ) && isset( $row['Field'] ) ) {
					$actual_columns[] = (string) $row['Field'];
				}
			}

			$missing = array_values( array_diff( $intended_columns, $actual_columns ) );
			if ( array() !== $missing ) {
				Telemetry::log_line(
					sprintf( '[acx] schema verification failed for %s; missing columns: %s', $table, implode( ', ', $missing ) )
				);
				return false;
			}
		}

		if ( $parsed_count !== $statement_count ) {
			Telemetry::log_line(
				sprintf(
					'[acx] schema verification failed: parsed table count %d does not match statement map size %d',
					$parsed_count,
					$statement_count
				)
			);
			return false;
		}

		return true;
	}

	/**
	 * Greenfield cleanup: drop the pre-E21-9 UNIQUE idx_name on acx_persons.name.
	 * Idempotent — no-op when the index is absent. Verifier stays column-only
	 * (extra indexes do not refuse the stamp; see LO-03 report rationale).
	 *
	 * @return bool False only when a probe/drop query errors.
	 */
	private function drop_legacy_persons_name_unique_index( string $persons_table ): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return false;
		}

		if ( property_exists( $wpdb, 'last_error' ) ) {
			$wpdb->last_error = '';
		}

		$index_name = self::LEGACY_PERSONS_NAME_UNIQUE_INDEX;
		$query      = null;
		if ( method_exists( $wpdb, 'prepare' ) ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- %i table placeholder.
			$query = $wpdb->prepare(
				'SHOW INDEX FROM %i WHERE Key_name = %s',
				$persons_table,
				$index_name
			);
		}
		if ( ! is_string( $query ) || '' === $query ) {
			$query = "SHOW INDEX FROM `{$persons_table}` WHERE Key_name = '{$index_name}'";
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Prepared above or plugin-owned identifiers.
		$rows  = $wpdb->get_results( $query, ARRAY_A );
		$error = property_exists( $wpdb, 'last_error' ) ? (string) $wpdb->last_error : '';
		// Mirror PreparesSqlQueries::guard_query_error: null from get_results is a
		// failed probe (query did not execute), not an empty result set. Conflating
		// the two would leave legacy idx_name in place while reporting success.
		if ( '' !== $error || null === $rows ) {
			if ( property_exists( $wpdb, 'last_error' ) ) {
				$wpdb->last_error = '';
			}
			$message = '' !== $error
				? $error
				: 'query did not execute (wpdb not ready or query filtered)';
			Telemetry::log_line(
				sprintf( '[acx] schema legacy-index probe failed for %s.%s: %s', $persons_table, $index_name, $message )
			);
			return false;
		}

		if ( ! is_array( $rows ) || array() === $rows ) {
			return true;
		}

		if ( property_exists( $wpdb, 'last_error' ) ) {
			$wpdb->last_error = '';
		}

		$drop = null;
		if ( method_exists( $wpdb, 'prepare' ) ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- %i identifiers.
			$drop = $wpdb->prepare(
				'ALTER TABLE %i DROP INDEX %i',
				$persons_table,
				$index_name
			);
		}
		if ( ! is_string( $drop ) || '' === $drop ) {
			$drop = "ALTER TABLE `{$persons_table}` DROP INDEX `{$index_name}`";
		}

		if ( ! method_exists( $wpdb, 'query' ) ) {
			return false;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Prepared above or plugin-owned identifiers.
		$result = $wpdb->query( $drop );
		$error  = property_exists( $wpdb, 'last_error' ) ? (string) $wpdb->last_error : '';
		if ( false === $result || '' !== $error ) {
			if ( property_exists( $wpdb, 'last_error' ) ) {
				$wpdb->last_error = '';
			}
			$message = '' !== $error ? $error : 'query returned false';
			Telemetry::log_line(
				sprintf( '[acx] schema legacy-index drop failed for %s.%s: %s', $persons_table, $index_name, $message )
			);
			return false;
		}

		Telemetry::log_line(
			sprintf( '[acx] schema dropped legacy index %s on %s', $index_name, $persons_table )
		);

		return true;
	}

	/**
	 * Derived-projection repair: rows that received the epoch DEFAULT when
	 * assigned_at was added keep a sane ORDER BY until the next recognition
	 * sync overwrites them. Not a migration framework (Greenfield Policy).
	 *
	 * Pre-counts sentinel rows, runs the UPDATE, and requires the affected-row
	 * count to match. A zero-row UPDATE against a non-zero sentinel population
	 * is a silent-success trap (wrong sentinel literals, filtered query) and
	 * must refuse the stamp so the next request retries.
	 *
	 * @return bool False when the UPDATE fails, the row counts disagree, or the environment cannot query.
	 */
	private function seed_assigned_at_from_created_at( string $members_table ): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return false;
		}

		$fallback        = self::ASSIGNED_AT_FALLBACK_UTC;
		$fallback_second = '1970-01-01 00:00:00';

		$expected = $this->count_assigned_at_sentinel_rows( $members_table, $fallback, $fallback_second );
		if ( null === $expected ) {
			return false;
		}

		if ( property_exists( $wpdb, 'last_error' ) ) {
			$wpdb->last_error = '';
		}

		$result = null;

		if ( method_exists( $wpdb, 'prepare' ) ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- %i table placeholder; constants only.
			$sql = $wpdb->prepare(
				'UPDATE %i SET assigned_at = created_at WHERE assigned_at = %s OR assigned_at = %s',
				$members_table,
				$fallback,
				$fallback_second
			);
			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Prepared above.
				$result = $wpdb->query( $sql );
			}
		}

		if ( null === $result ) {
			$result = $wpdb->query(
				// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared -- Table name is plugin-owned; literals are constants.
				"UPDATE `{$members_table}` SET assigned_at = created_at WHERE assigned_at = '{$fallback}' OR assigned_at = '{$fallback_second}'"
			);
		}

		$error = property_exists( $wpdb, 'last_error' ) ? (string) $wpdb->last_error : '';
		// false = MySQL error; 0 = successful UPDATE that matched nothing. Distinct outcomes.
		if ( false === $result || '' !== $error ) {
			if ( property_exists( $wpdb, 'last_error' ) ) {
				$wpdb->last_error = '';
			}
			$message = '' !== $error ? $error : 'query returned false';
			Telemetry::log_line(
				sprintf( '[acx] schema seed assigned_at failed for %s: %s', $members_table, $message )
			);
			return false;
		}

		// Real wpdb returns int rows-affected on UPDATE success (never boolean true).
		if ( ! is_int( $result ) ) {
			Telemetry::log_line(
				sprintf(
					'[acx] schema seed assigned_at failed for %s: UPDATE returned non-integer success (%s)',
					$members_table,
					get_debug_type( $result )
				)
			);
			return false;
		}

		if ( $result !== $expected ) {
			Telemetry::log_line(
				sprintf(
					'[acx] schema seed assigned_at row-count mismatch for %s: expected %d, affected %d',
					$members_table,
					$expected,
					$result
				)
			);
			return false;
		}

		return true;
	}

	/**
	 * Count identity_members rows still holding an assigned_at sentinel.
	 *
	 * @return int|null Null when the COUNT cannot run or MySQL errors (fail the repair).
	 */
	private function count_assigned_at_sentinel_rows( string $members_table, string $fallback, string $fallback_second ): ?int {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) ) {
			Telemetry::log_line(
				sprintf( '[acx] schema seed assigned_at failed for %s: wpdb get_var unavailable for sentinel pre-count', $members_table )
			);
			return null;
		}

		if ( property_exists( $wpdb, 'last_error' ) ) {
			$wpdb->last_error = '';
		}

		$count = null;
		if ( method_exists( $wpdb, 'prepare' ) ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- %i table placeholder; constants only.
			$sql = $wpdb->prepare(
				'SELECT COUNT(*) FROM %i WHERE assigned_at = %s OR assigned_at = %s',
				$members_table,
				$fallback,
				$fallback_second
			);
			if ( is_string( $sql ) && '' !== $sql ) {
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Prepared above.
				$count = $wpdb->get_var( $sql );
			}
		}

		if ( null === $count ) {
			$count = $wpdb->get_var(
				// phpcs:ignore WordPress.DB.PreparedSQL.InterpolatedNotPrepared -- Table name is plugin-owned; literals are constants.
				"SELECT COUNT(*) FROM `{$members_table}` WHERE assigned_at = '{$fallback}' OR assigned_at = '{$fallback_second}'"
			);
		}

		$error = property_exists( $wpdb, 'last_error' ) ? (string) $wpdb->last_error : '';
		// Mirror PreparesSqlQueries::guard_query_error with null_is_failure for COUNT.
		if ( '' !== $error || null === $count ) {
			if ( property_exists( $wpdb, 'last_error' ) ) {
				$wpdb->last_error = '';
			}
			$message = '' !== $error
				? $error
				: 'query did not execute (wpdb not ready or query filtered)';
			Telemetry::log_line(
				sprintf( '[acx] schema seed assigned_at failed for %s: sentinel pre-count: %s', $members_table, $message )
			);
			return null;
		}

		return max( 0, (int) $count );
	}
}
