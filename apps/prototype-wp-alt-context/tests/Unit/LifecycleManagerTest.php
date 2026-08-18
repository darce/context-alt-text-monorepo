<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;

/**
 * Tests for LifecycleManager.
 *
 * @covers \AltContext\Support\LifecycleManager
 */
class LifecycleManagerTest extends TestCase
{
    private LifecycleManager $manager;

    protected function setUp(): void
    {
        parent::setUp();
        $this->manager = new LifecycleManager();
    }

    /**
     * Test activate stores version option.
     */
    public function testActivateSetsVersionOption(): void
    {
        $this->manager->activate();

        $this->assertSame(
            ACX_VERSION,
            get_option('acx_version'),
            'Version should be stored on activation'
        );
    }

    /**
     * Test activate stores install timestamp on first activation.
     */
    public function testActivateSetsInstallTimestampOnFirstRun(): void
    {
        $this->manager->activate();

        $installed = get_option('acx_installed');
        $this->assertNotFalse($installed, 'Install timestamp should be set');
        $this->assertIsInt($installed, 'Install timestamp should be an integer');
        $this->assertGreaterThan(0, $installed, 'Install timestamp should be positive');
    }

    /**
     * Test activate does not overwrite existing install timestamp.
     */
    public function testActivateDoesNotOverwriteExistingInstallTimestamp(): void
    {
        $originalTimestamp = 1234567890;
        $this->setOption('acx_installed', $originalTimestamp);

        $this->manager->activate();

        $this->assertSame(
            $originalTimestamp,
            get_option('acx_installed'),
            'Existing install timestamp should not be overwritten'
        );
    }

    public function testActivateCreatesProjectionTablesViaDbDelta(): void
    {
        $this->manager->activate();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertIsArray($queries);
        $this->assertCount(12, $queries);

        $personsSql = $queries[0];
        $clustersSql = $queries[1];
        $membersSql = $queries[2];
        $syncSql = $queries[3];
        $outboxSql = $queries[4];
        $topologySql = $queries[5];
        $conflictsSql = $queries[6];
        $batchRunsSql = $queries[7];
        $batchFailuresSql = $queries[8];
        $descriptionUsageSql = $queries[11];

        $this->assertStringContainsString('CREATE TABLE wp_acx_persons', $personsSql);
        $this->assertStringContainsString('person_uuid', $personsSql);
        $this->assertStringContainsString('reference_thumb_path', $personsSql);

        $this->assertStringContainsString('CREATE TABLE wp_acx_clusters', $clustersSql);
        $this->assertStringContainsString('representative_thumb_path', $clustersSql);
        $this->assertStringContainsString('representative_id', $clustersSql);
        $this->assertStringContainsString('is_pinned', $clustersSql);
        $this->assertStringContainsString('identity_count', $clustersSql);
        $this->assertStringContainsString('created_at', $clustersSql);
        $this->assertStringContainsString('updated_at', $clustersSql);
        $this->assertStringContainsString('last_synced_at', $clustersSql);
        $this->assertStringContainsString('local_revision', $clustersSql);

        $this->assertStringContainsString('CREATE TABLE wp_acx_identity_members', $membersSql);
        $this->assertStringContainsString('bbox_json', $membersSql);
        $this->assertStringContainsString('is_curated', $membersSql);
        $this->assertStringContainsString('projection_version', $membersSql);
        $this->assertStringContainsString('attachment_lookup', $membersSql);

        $this->assertStringContainsString('CREATE TABLE wp_acx_sync_state', $syncSql);
        $this->assertStringContainsString('last_snapshot_version', $syncSql);
        $this->assertStringContainsString('last_sync_result', $syncSql);
        $this->assertStringContainsString('last_sync_attempted_at', $syncSql);
        $this->assertStringContainsString('pending_curation_operations', $syncSql);
        $this->assertStringContainsString('failed_curation_operations', $syncSql);
        $this->assertStringContainsString('conflict_count', $syncSql);
        $this->assertStringContainsString('last_curation_failed_at', $syncSql);

        $this->assertStringContainsString('CREATE TABLE wp_acx_sync_outbox', $outboxSql);
        $this->assertStringContainsString('idempotency_key', $outboxSql);
        $this->assertStringContainsString('acknowledged_version', $outboxSql);

        $this->assertStringContainsString('CREATE TABLE wp_acx_topology_commands', $topologySql);
        $this->assertStringContainsString('command_type', $topologySql);
        $this->assertStringContainsString('payload_json', $topologySql);
        $this->assertStringContainsString('projection_reconciled_at', $topologySql);

        $this->assertStringContainsString('CREATE TABLE wp_acx_sync_conflicts', $conflictsSql);
        $this->assertStringContainsString('conflict_code', $conflictsSql);
        $this->assertStringContainsString('backend_proposed_value', $conflictsSql);
        $this->assertStringContainsString('resolution_status', $conflictsSql);
        $this->assertStringContainsString('UNIQUE KEY uq_projection_conflict', $conflictsSql);

        $this->assertStringContainsString('CREATE TABLE wp_acx_batch_runs', $batchRunsSql);
        $this->assertStringContainsString('tenant_id', $batchRunsSql);
        $this->assertStringContainsString('child_jobs_json', $batchRunsSql);
        $this->assertStringContainsString('terminal_state', $batchRunsSql);

        $this->assertStringContainsString('CREATE TABLE wp_acx_batch_run_failures', $batchFailuresSql);
        $this->assertStringContainsString('run_id', $batchFailuresSql);
        $this->assertStringContainsString('batch_index', $batchFailuresSql);
        $this->assertStringContainsString('error_code', $batchFailuresSql);

        $this->assertStringContainsString('CREATE TABLE wp_acx_description_usage', $descriptionUsageSql);
        $this->assertStringContainsString('media_id', $descriptionUsageSql);
        $this->assertStringContainsString('outcome', $descriptionUsageSql);
        $this->assertStringContainsString('cost_amount', $descriptionUsageSql);
    }

    public function testActivateProjectionDbDeltaIsIdempotentAcrossReactivation(): void
    {
        $this->manager->activate();
        $this->manager->activate();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertCount(24, $queries);
        $this->assertStringNotContainsString('DROP TABLE', \implode("\n", $queries));
    }

    public function testActivateImportsLegacyRosterDataBeforeRetiringOptions(): void
    {
        global $wpdb;

        $this->setOption('acx_roster_entries', [
            [
                'id' => 7,
                'name' => 'Ada Lovelace',
                'tags' => ['analyst'],
            ],
        ]);
        $this->setOption('acx_roster_assignments', [
            'cluster-123' => [
                'roster_entry_id' => 7,
            ],
        ]);
        $wpdb->queryResults["SELECT id FROM `wp_acx_persons` WHERE normalized_name = 'ada lovelace'"] = null;

        $this->manager->activate();

        $personInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_persons');
        $this->assertStringContainsString("'Ada Lovelace'", $personInsert);
        $this->assertStringContainsString('analyst', $personInsert);

        $clusterUpdate = $this->findQueryContaining($wpdb->queries, 'UPDATE wp_acx_clusters SET person_id = 1');
        $this->assertStringContainsString("cluster_uuid = 'cluster-123'", $clusterUpdate);

        $this->assertFalse(get_option('acx_roster_entries'));
        $this->assertFalse(get_option('acx_roster_assignments'));
    }

    public function testActivateKeepsLegacyRosterOptionsWhenAssignmentImportFails(): void
    {
        global $wpdb;

        $legacyEntries = [
            [
                'id' => 9,
                'name' => 'Grace Hopper',
                'tags' => ['navy'],
            ],
        ];
        $legacyAssignments = [
            'cluster-999' => [
                'roster_entry_id' => 9,
            ],
        ];

        $this->setOption('acx_roster_entries', $legacyEntries);
        $this->setOption('acx_roster_assignments', $legacyAssignments);
        $wpdb->queryResults["SELECT id FROM `wp_acx_persons` WHERE normalized_name = 'grace hopper'"] = null;
        $wpdb->defaultUpdateResult = 0;

        $this->manager->activate();

        $personInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_persons');
        $this->assertStringContainsString("'Grace Hopper'", $personInsert);
        $clusterUpdate = $this->findQueryContaining($wpdb->queries, "WHERE cluster_uuid = 'cluster-999'");
        $this->assertStringContainsString('UPDATE wp_acx_clusters SET person_id = 1', $clusterUpdate);

        $this->assertSame($legacyEntries, get_option('acx_roster_entries'));
        $this->assertSame($legacyAssignments, get_option('acx_roster_assignments'));
    }

    public function testActivateRetiresLegacyOptionsWhenAssignmentAlreadyMatchesImportedPerson(): void
    {
        global $wpdb;

        $this->setOption('acx_roster_entries', [
            [
                'id' => 15,
                'name' => 'Katherine Johnson',
                'tags' => ['nasa'],
            ],
        ]);
        $this->setOption('acx_roster_assignments', [
            'cluster-321' => [
                'roster_entry_id' => 15,
            ],
        ]);

        $wpdb->queryResults["SELECT id FROM `wp_acx_persons` WHERE normalized_name = 'katherine johnson'"] = 13;
        $wpdb->queryResults["SELECT person_id FROM `wp_acx_clusters` WHERE cluster_uuid = 'cluster-321' LIMIT 1"] = 13;
        $wpdb->defaultUpdateResult = 0;

        $this->manager->activate();

        $this->assertFalse(get_option('acx_roster_entries'));
        $this->assertFalse(get_option('acx_roster_assignments'));
        $this->assertSame(
            "SELECT person_id FROM `wp_acx_clusters` WHERE cluster_uuid = 'cluster-321' LIMIT 1",
            $this->findQueryContaining($wpdb->queries, 'SELECT person_id FROM `wp_acx_clusters` WHERE cluster_uuid = \'cluster-321\' LIMIT 1')
        );
    }

    public function testActivateSkipsMalformedLegacyRosterDataAndStillRetiresOptions(): void
    {
        global $wpdb;

        $this->setOption('acx_roster_entries', [
            [
                'id' => 21,
                'name' => 'Dorothy Vaughan',
                'tags' => ['nasa'],
            ],
            [
                'id' => 22,
                'name' => '   ',
            ],
        ]);
        $this->setOption('acx_roster_assignments', [
            'cluster-654' => [
                'roster_entry_id' => 21,
            ],
            'cluster-invalid' => 'skip-me',
        ]);
        $wpdb->queryResults["SELECT id FROM `wp_acx_persons` WHERE normalized_name = 'dorothy vaughan'"] = null;

        $this->manager->activate();

        $personInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_persons');
        $this->assertStringContainsString("'Dorothy Vaughan'", $personInsert);
        $clusterUpdate = $this->findQueryContaining($wpdb->queries, "WHERE cluster_uuid = 'cluster-654'");
        $this->assertStringContainsString('UPDATE wp_acx_clusters SET person_id = 1', $clusterUpdate);

        $this->assertFalse(get_option('acx_roster_entries'));
        $this->assertFalse(get_option('acx_roster_assignments'));
    }

    public function testActivateSchedulesLegacyRosterMigrationContinuationUntilChunkedMigrationCompletes(): void
    {
        global $wpdb;

        $chunkSize = (new \ReflectionClass(LifecycleManager::class))->getConstant('MAX_LEGACY_MIGRATION_CHUNK');
        $this->assertIsInt($chunkSize, 'LifecycleManager should declare a typed MAX_LEGACY_MIGRATION_CHUNK cap.');
        $legacyEntries = [];

        for ($index = 1; $index <= $chunkSize + 1; $index++) {
            $legacyEntries[] = [
                'id' => $index,
                'name' => 'Legacy Person ' . $index,
                'tags' => ['tag-' . $index],
            ];
        }

        $this->setOption('acx_roster_entries', $legacyEntries);
        $this->setOption('acx_roster_assignments', [
            'cluster-overflow' => [
                'roster_entry_id' => $chunkSize + 1,
            ],
        ]);

        $this->manager->activate();

        $personInsertQueries = \array_values(\array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_starts_with($query, 'INSERT INTO wp_acx_persons')
        ));
        $assignmentUpdateQueries = \array_values(\array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_starts_with($query, 'UPDATE wp_acx_clusters SET person_id =')
        ));

        $this->assertCount($chunkSize, $personInsertQueries);
        $this->assertCount(0, $assignmentUpdateQueries);
        $this->assertSame($legacyEntries, get_option('acx_roster_entries'));
        $this->assertSame(
            [
                'entry_offset' => $chunkSize,
                'assignment_offset' => 0,
            ],
            get_option('acx_legacy_roster_migration_cursor')
        );
        $this->assertNotFalse(as_next_scheduled_action('acx_continue_legacy_roster_migration', [], 'acx-sync'));

        do_action('acx_continue_legacy_roster_migration');

        $personInsertQueries = \array_values(\array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_starts_with($query, 'INSERT INTO wp_acx_persons')
        ));
        $assignmentUpdateQueries = \array_values(\array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_starts_with($query, 'UPDATE wp_acx_clusters SET person_id =')
        ));

        $this->assertCount($chunkSize + 1, $personInsertQueries);
        $this->assertCount(1, $assignmentUpdateQueries);
        $this->assertFalse(get_option('acx_roster_entries'));
        $this->assertFalse(get_option('acx_roster_assignments'));
        $this->assertFalse(get_option('acx_legacy_roster_migration_cursor'));
        $this->assertFalse(as_next_scheduled_action('acx_continue_legacy_roster_migration', [], 'acx-sync'));
    }

    /**
     * Test uninstall removes version option.
     */
    public function testUninstallRemovesVersionOption(): void
    {
        $this->setOption('acx_version', '1.0.0');
        $this->setOption('acx_installed', \time());

        $this->manager->uninstall();

        $this->assertFalse(
            get_option('acx_version'),
            'Version option should be removed on uninstall'
        );
    }

    /**
     * Test uninstall removes install timestamp.
     */
    public function testUninstallRemovesInstallTimestamp(): void
    {
        $this->setOption('acx_version', '1.0.0');
        $this->setOption('acx_installed', \time());

        $this->manager->uninstall();

        $this->assertFalse(
            get_option('acx_installed'),
            'Install timestamp should be removed on uninstall'
        );
    }

    public function testDeactivateClearsSnapshotSyncSchedule(): void
    {
        wp_schedule_single_event(\time() + 300, 'acx_sync_pull_snapshot');
		wp_schedule_single_event(\time() + 300, 'acx_sync_drain_curation_outbox');
		wp_schedule_event(\time() + 300, 'daily', 'acx_sync_purge_terminal_rows');
        $this->assertNotFalse(wp_next_scheduled('acx_sync_pull_snapshot'));
		$this->assertNotFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));
		$this->assertNotFalse(wp_next_scheduled('acx_sync_purge_terminal_rows'));

        $this->manager->deactivate();

        $this->assertFalse(wp_next_scheduled('acx_sync_pull_snapshot'));
		$this->assertFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));
		$this->assertFalse(wp_next_scheduled('acx_sync_purge_terminal_rows'));
    }

	public function testDeactivateAlsoClearsActionSchedulerDrainHooks(): void
        {
			as_enqueue_async_action('acx_sync_drain_curation_outbox', [], 'acx-sync');
			$this->assertNotFalse(as_next_scheduled_action('acx_sync_drain_curation_outbox', [], 'acx-sync'));

			$this->manager->deactivate();

			$this->assertFalse(as_next_scheduled_action('acx_sync_drain_curation_outbox', [], 'acx-sync'));
	}

    public function testUninstallClearsSnapshotSyncSchedule(): void
    {
        wp_schedule_single_event(\time() + 300, 'acx_sync_pull_snapshot');
		wp_schedule_single_event(\time() + 300, 'acx_sync_drain_curation_outbox');
		wp_schedule_event(\time() + 300, 'daily', 'acx_sync_purge_terminal_rows');
        $this->assertNotFalse(wp_next_scheduled('acx_sync_pull_snapshot'));
		$this->assertNotFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));
		$this->assertNotFalse(wp_next_scheduled('acx_sync_purge_terminal_rows'));

        $this->manager->uninstall();

        $this->assertFalse(wp_next_scheduled('acx_sync_pull_snapshot'));
		$this->assertFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));
		$this->assertFalse(wp_next_scheduled('acx_sync_purge_terminal_rows'));
    }

	public function testUninstallAlsoClearsActionSchedulerDrainHooks(): void
        {
			as_enqueue_async_action('acx_sync_drain_curation_outbox', [], 'acx-sync');
			$this->assertNotFalse(as_next_scheduled_action('acx_sync_drain_curation_outbox', [], 'acx-sync'));

			$this->manager->uninstall();

			$this->assertFalse(as_next_scheduled_action('acx_sync_drain_curation_outbox', [], 'acx-sync'));
	}

    /**
     * Test uninstall drops plugin-owned custom tables.
     */
    public function testUninstallDropsPluginOwnedTables(): void
    {
        global $wpdb;

        $this->manager->uninstall();

        $this->assertContains('DROP TABLE IF EXISTS `wp_acx_clusters`', $wpdb->queries);
        $this->assertContains('DROP TABLE IF EXISTS `wp_acx_identity_members`', $wpdb->queries);
        $this->assertContains('DROP TABLE IF EXISTS `wp_acx_sync_state`', $wpdb->queries);
        $this->assertContains('DROP TABLE IF EXISTS `wp_acx_persons`', $wpdb->queries);
        $this->assertContains('DROP TABLE IF EXISTS `wp_acx_sync_outbox`', $wpdb->queries);
        $this->assertContains('DROP TABLE IF EXISTS `wp_acx_topology_commands`', $wpdb->queries);
        $this->assertContains('DROP TABLE IF EXISTS `wp_acx_sync_conflicts`', $wpdb->queries);
    }

    /**
     * Test full lifecycle: activate -> deactivate -> uninstall.
     */
    public function testFullLifecycle(): void
    {
        // Activate
        $this->manager->activate();
        $this->assertSame(ACX_VERSION, get_option('acx_version'));
        $this->assertNotFalse(get_option('acx_installed'));

        // Deactivate (should not remove options)
        $this->manager->deactivate();
        $this->assertSame(ACX_VERSION, get_option('acx_version'));
        $this->assertNotFalse(get_option('acx_installed'));

        // Uninstall (should remove options)
        $this->manager->uninstall();
        $this->assertFalse(get_option('acx_version'));
        $this->assertFalse(get_option('acx_installed'));
    }

    public function testMaybeUpgradeCreatesTablesAndUpdatesVersionWhenStoredDiffers(): void
    {
        $this->setOption('acx_version', '0.0.1-stale');

        $this->manager->maybe_upgrade();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertIsArray($queries);
        $this->assertNotEmpty($queries, 'Projection tables should be created when version differs');
        $this->assertSame(ACX_VERSION, get_option('acx_version'));
        $this->assertSame(
            $this->manager->compute_projection_schema_fingerprint(),
            get_option('acx_schema_fingerprint'),
            'successful upgrade must stamp schema fingerprint'
        );
    }

    public function testMaybeUpgradeHealsUnboundHumanLabelsIncludingUnderscoreSkip(): void
    {
        $this->setOption('acx_version', '0.0.1-stale');
        global $wpdb;
        $wpdb->insert_id = 3;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-heal',
                'label' => 'Tory Guzman',
                'person_id' => null,
            ],
        ];

        $this->manager->maybe_upgrade();

        $listSql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString("LIKE 'cluster\\_%%'", $listSql);
        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertNotEmpty($personInserts);
    }

    public function testMaybeUpgradeCreatesTablesAndSetsVersionWhenStoredMissing(): void
    {
        $this->assertFalse(get_option('acx_version'));

        $this->manager->maybe_upgrade();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertIsArray($queries);
        $this->assertNotEmpty($queries, 'Projection tables should be created when version is missing');
        $this->assertSame(ACX_VERSION, get_option('acx_version'));
        $this->assertSame(
            $this->manager->compute_projection_schema_fingerprint(),
            get_option('acx_schema_fingerprint')
        );
    }

    public function testMaybeUpgradeOutboxSchemaCarriesRetryBackoffColumns(): void
    {
        // E15-35 Slice 1: existing installs heal the two new outbox retry columns through the
        // plugin version bump -> maybe_upgrade() -> dbDelta($outbox_sql) path (no hand-rolled
        // ALTER TABLE). dbDelta caveats: one column per line, dbDelta-normalized nullable datetime.
        $this->setOption('acx_version', '0.0.1-stale');

        $this->manager->maybe_upgrade();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $outboxSql = '';
        foreach ($queries as $sql) {
            if (str_contains($sql, 'acx_sync_outbox')) {
                $outboxSql = $sql;
                break;
            }
        }

        $this->assertNotSame('', $outboxSql, 'Expected the outbox CREATE TABLE to run on upgrade.');
        $this->assertMatchesRegularExpression('/^\s*next_attempt_at datetime DEFAULT NULL,$/m', $outboxSql);
        $this->assertMatchesRegularExpression('/^\s*first_failed_at datetime DEFAULT NULL,$/m', $outboxSql);
    }

    /**
     * DATA-03 / RLSE-05: fingerprint mismatch alone must re-run dbDelta even when
     * ACX_VERSION is unchanged. This is the gate that would have landed assigned_at
     * without a human version bump. Unlike string-vs-string parity tests, this
     * assertion goes red against the pre-fix version-only early-return.
     */
    public function testMaybeUpgradeRunsWhenSchemaFingerprintDiffersWithMatchingVersion(): void
    {
        $this->setOption('acx_version', ACX_VERSION);
        $this->setOption('acx_schema_fingerprint', 'stale-not-a-real-hash');

        $this->manager->maybe_upgrade();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertNotEmpty(
            $queries,
            'fingerprint mismatch must trigger dbDelta even when version matches'
        );
        $this->assertSame(ACX_VERSION, get_option('acx_version'));
        $stamped = get_option('acx_schema_fingerprint');
        $this->assertNotSame('stale-not-a-real-hash', $stamped);
        $this->assertSame(
            $this->manager->compute_projection_schema_fingerprint(),
            $stamped,
            'successful fingerprint-driven upgrade must stamp the current hash'
        );
        $this->assertSame(40, strlen((string) $stamped), 'fingerprint is sha1 hex');
    }

    public function testMaybeUpgradeIsStrictNoopWhenVersionAndFingerprintMatch(): void
    {
        // Stamp version + fingerprint via a successful upgrade first.
        $this->manager->maybe_upgrade();
        $GLOBALS['__ac_dbdelta_queries'] = [];
        $optionsBefore = $GLOBALS['__ac_options'];

        $this->manager->maybe_upgrade();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertSame([], $queries, 'matching version+fingerprint must not run dbDelta');
        $this->assertSame(
            $optionsBefore,
            $GLOBALS['__ac_options'],
            'matching version+fingerprint must not write options'
        );
    }

    public function testMembersSchemaCarriesAssignedAtDefaultForStrictModeAlter(): void
    {
        $this->manager->maybe_upgrade();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $membersSql = '';
        foreach ($queries as $sql) {
            if (is_string($sql) && str_contains($sql, 'acx_identity_members')) {
                $membersSql = $sql;
                break;
            }
        }

        $this->assertNotSame('', $membersSql, 'Expected identity_members CREATE TABLE on upgrade.');
        $this->assertMatchesRegularExpression(
            "/assigned_at datetime\\(6\\) NOT NULL DEFAULT '1970-01-01 00:00:00\\.000000'/",
            $membersSql,
            'STRICT_TRANS_TABLES / NO_ZERO_DATE requires an explicit DEFAULT on assigned_at'
        );
    }

    public function testMaybeUpgradeSeedsAssignedAtFromCreatedAtForEpochDefault(): void
    {
        global $wpdb;

        $this->manager->maybe_upgrade();

        $backfill = $this->findQueryContaining($wpdb->queries, 'SET assigned_at = created_at');
        $this->assertStringContainsString('1970-01-01 00:00:00.000000', $backfill);
    }

    public function testMaybeUpgradeDoesNotStampVersionWhenSchemaUpgradeIsSkipped(): void
    {
        // When an environment guard skips the dbDelta run (here: no $wpdb),
        // the version must NOT be stamped, so a later request retries the
        // upgrade instead of permanently masking it behind the strict no-op.
        $wpdbBackup = $GLOBALS['wpdb'] ?? null;
        unset($GLOBALS['wpdb']);

        try {
            $this->manager->maybe_upgrade();
        } finally {
            if (null !== $wpdbBackup) {
                // phpcs:ignore WordPress.WP.GlobalVariablesOverride.Prohibited -- Restore the test's original wpdb stub.
                $GLOBALS['wpdb'] = $wpdbBackup;
            }
        }

        $this->assertSame([], $GLOBALS['__ac_dbdelta_queries'] ?? [], 'skipped upgrade must not run dbDelta');
        $this->assertFalse(get_option('acx_version'), 'skipped upgrade must not stamp acx_version');
        $this->assertFalse(get_option('acx_schema_fingerprint'), 'skipped upgrade must not stamp fingerprint');
    }

    public function testUninstallRemovesSchemaFingerprintOption(): void
    {
        $this->setOption('acx_schema_fingerprint', 'some-hash');
        $this->manager->uninstall();
        $this->assertFalse(get_option('acx_schema_fingerprint'));
    }

    /**
     * E21-14-BR-01 / RLSE-05 / OBS-08: dbDelta MySQL failure must not stamp version or
     * fingerprint (that permanently suppresses retry). Next maybe_upgrade must re-run.
     * TEST-15: goes red when maybe_create returns true after last_error.
     */
    public function testMaybeUpgradeDoesNotStampOnDbDeltaFailureAndRetries(): void
    {
        global $wpdb;

        $mysqlError = "Invalid default value for 'assigned_at'";
        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_dbdelta_fail_on_match'] = 'acx_identity_members';
        $GLOBALS['__ac_dbdelta_fail_error'] = $mysqlError;
        $GLOBALS['__ac_error_log'] = [];

        $this->manager->maybe_upgrade();

        $this->assertSame(
            '0.0.1-stale',
            get_option('acx_version'),
            'failed schema apply must not stamp acx_version (would suppress retry)'
        );
        $this->assertFalse(
            get_option('acx_schema_fingerprint'),
            'failed schema apply must not stamp acx_schema_fingerprint'
        );
        $log = $this->getErrorLog();
        $this->assertNotEmpty($log, 'schema apply failure must log via Telemetry (OBS-08)');
        $joined = \implode("\n", $log);
        $this->assertStringContainsString($mysqlError, $joined);
        $this->assertSame('', $wpdb->last_error, 'last_error must be cleared so it is not attributed to later work');

        // Clear the simulated failure; next request must retry the full apply.
        unset($GLOBALS['__ac_dbdelta_fail_on_match'], $GLOBALS['__ac_dbdelta_fail_error']);
        $GLOBALS['__ac_dbdelta_queries'] = [];
        $wpdb->last_error = '';

        $this->manager->maybe_upgrade();

        $retryQueries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertNotEmpty($retryQueries, 'next maybe_upgrade must retry dbDelta after a failed apply');
        $this->assertSame(ACX_VERSION, get_option('acx_version'));
        $this->assertSame(
            $this->manager->compute_projection_schema_fingerprint(),
            get_option('acx_schema_fingerprint')
        );
    }

    public function testMaybeUpgradeDoesNotStampWhenDbDeltaSilentlyOmitsColumn(): void
    {
        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_dbdelta_silent_skip_column'] = 'assigned_at';
        $GLOBALS['__ac_error_log'] = [];

        $this->manager->maybe_upgrade();
        unset($GLOBALS['__ac_dbdelta_silent_skip_column']);

        $this->assertSame('0.0.1-stale', get_option('acx_version'));
        $this->assertFalse(get_option('acx_schema_fingerprint'));
        $this->assertStringContainsString(
            'wp_acx_identity_members',
            \implode("\n", $this->getErrorLog())
        );
        $this->assertStringContainsString('assigned_at', \implode("\n", $this->getErrorLog()));
    }

    public function testMaybeUpgradeVerifiedSchemaStampsExactlyOnce(): void
    {
        $this->manager->maybe_upgrade();
        $appliedCount = \count($GLOBALS['__ac_dbdelta_queries'] ?? []);

        $this->manager->maybe_upgrade();

        $this->assertSame(ACX_VERSION, get_option('acx_version'));
        $this->assertSame($this->manager->compute_projection_schema_fingerprint(), get_option('acx_schema_fingerprint'));
        $this->assertCount($appliedCount, $GLOBALS['__ac_dbdelta_queries'] ?? []);
    }

    /**
     * E21-14-BR-01: seed backfill failure must also refuse to stamp (same permanent-success trap).
     */
    public function testMaybeUpgradeDoesNotStampWhenAssignedAtSeedFails(): void
    {
        global $wpdb;

        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];

        $fallback = '1970-01-01 00:00:00.000000';
        $fallbackSecond = '1970-01-01 00:00:00';
        $seedSql = $wpdb->prepare(
            'UPDATE %i SET assigned_at = created_at WHERE assigned_at = %s OR assigned_at = %s',
            'wp_acx_identity_members',
            $fallback,
            $fallbackSecond
        );
        $this->assertIsString($seedSql);
        $wpdb->queryResults[trim((string) $seedSql)] = false;
        $wpdb->last_error = '';

        $this->manager->maybe_upgrade();

        $this->assertSame(
            '0.0.1-stale',
            get_option('acx_version'),
            'seed failure must not stamp acx_version'
        );
        $this->assertFalse(
            get_option('acx_schema_fingerprint'),
            'seed failure must not stamp fingerprint'
        );
    }

    /**
     * FIX-1 / OBS-08: a successful UPDATE that touches 0 rows while sentinels remain
     * must refuse the fingerprint stamp (zero-row seed is not success).
     * TEST-15: goes red when seed treats $wpdb->query() === 0 as success.
     */
    public function testMaybeUpgradeDoesNotStampWhenAssignedAtSeedTouchesZeroOfExpectedRows(): void
    {
        global $wpdb;

        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];

        $fallback = '1970-01-01 00:00:00.000000';
        $fallbackSecond = '1970-01-01 00:00:00';
        $countSql = $wpdb->prepare(
            'SELECT COUNT(*) FROM %i WHERE assigned_at = %s OR assigned_at = %s',
            'wp_acx_identity_members',
            $fallback,
            $fallbackSecond
        );
        $seedSql = $wpdb->prepare(
            'UPDATE %i SET assigned_at = created_at WHERE assigned_at = %s OR assigned_at = %s',
            'wp_acx_identity_members',
            $fallback,
            $fallbackSecond
        );
        $this->assertIsString($countSql);
        $this->assertIsString($seedSql);

        // Pre-count reports sentinels exist; UPDATE "succeeds" but matches nothing.
        $wpdb->queryResults[trim((string) $countSql)] = 60;
        $wpdb->queryResults[trim((string) $seedSql)] = 0;
        $wpdb->last_error = '';

        $this->manager->maybe_upgrade();

        $this->assertSame(
            '0.0.1-stale',
            get_option('acx_version'),
            'zero-row seed against non-zero sentinel count must not stamp acx_version'
        );
        $this->assertFalse(
            get_option('acx_schema_fingerprint'),
            'zero-row seed against non-zero sentinel count must not stamp fingerprint'
        );
        $joined = \implode("\n", $this->getErrorLog());
        $this->assertStringContainsString('row-count mismatch', $joined);
        $this->assertStringContainsString('expected 60', $joined);
        $this->assertStringContainsString('affected 0', $joined);
    }

    /**
     * FIX-1 happy path: matching pre-count and affected rows still stamps.
     */
    public function testMaybeUpgradeStampsWhenAssignedAtSeedRowCountsMatch(): void
    {
        global $wpdb;

        $this->setOption('acx_version', '0.0.1-stale');
        $GLOBALS['__ac_error_log'] = [];

        $fallback = '1970-01-01 00:00:00.000000';
        $fallbackSecond = '1970-01-01 00:00:00';
        $countSql = $wpdb->prepare(
            'SELECT COUNT(*) FROM %i WHERE assigned_at = %s OR assigned_at = %s',
            'wp_acx_identity_members',
            $fallback,
            $fallbackSecond
        );
        $seedSql = $wpdb->prepare(
            'UPDATE %i SET assigned_at = created_at WHERE assigned_at = %s OR assigned_at = %s',
            'wp_acx_identity_members',
            $fallback,
            $fallbackSecond
        );
        $this->assertIsString($countSql);
        $this->assertIsString($seedSql);

        $wpdb->queryResults[trim((string) $countSql)] = 3;
        $wpdb->queryResults[trim((string) $seedSql)] = 3;
        $wpdb->last_error = '';

        $this->manager->maybe_upgrade();

        $this->assertSame(ACX_VERSION, get_option('acx_version'));
        $this->assertSame(
            $this->manager->compute_projection_schema_fingerprint(),
            get_option('acx_schema_fingerprint')
        );
    }

    /**
     * E21-14-BR-02 / rg-005: every key in build_projection_schema_statements must be applied.
     * Goes red if a table is added to the map but never passed to dbDelta.
     */
    public function testMaybeUpgradeAppliesEveryProjectionSchemaStatementKey(): void
    {
        $statements = $this->manager->build_projection_schema_statements('wp_', 'COLLATE test');
        $this->assertNotEmpty($statements, 'schema statement map must not be empty');

        $this->manager->maybe_upgrade();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertCount(
            \count($statements),
            $queries,
            'dbDelta invocation count must equal statement map size (no orphan keys, no second list)'
        );

        $appliedSql = \implode("\n", $queries);
        foreach (\array_keys($statements) as $key) {
            $tableName = 'wp_' . $key;
            $this->assertStringContainsString(
                $tableName,
                $appliedSql,
                \sprintf('statement key "%s" must be applied via dbDelta (table %s)', $key, $tableName)
            );
        }
    }

    /**
     * E21-14-BR-09: uninstall/reset owned-table list must include every schema map key
     * (including acx_description_usage, previously omitted from OWNED_TABLE_SUFFIXES).
     */
    public function testUninstallDropsEveryProjectionSchemaTableIncludingDescriptionUsage(): void
    {
        global $wpdb;

        $statements = $this->manager->build_projection_schema_statements('wp_', 'COLLATE test');
        $this->manager->uninstall();

        foreach (\array_keys($statements) as $key) {
            $drop = 'DROP TABLE IF EXISTS `wp_' . $key . '`';
            $this->assertContains(
                $drop,
                $wpdb->queries,
                \sprintf('uninstall must drop schema table %s (single source of truth with statement map)', $key)
            );
        }

        $this->assertContains(
            'DROP TABLE IF EXISTS `wp_acx_description_usage`',
            $wpdb->queries,
            'acx_description_usage must not be orphaned on uninstall (BR-09)'
        );
    }

    private function findQueryContaining(array $queries, string $needle): string
    {
        foreach ($queries as $query) {
            if (str_contains($query, $needle)) {
                return $query;
            }
        }

        $this->fail(\sprintf('Could not find query containing "%s".', $needle));
    }
}
