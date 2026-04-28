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
        $this->assertCount(7, $queries);

        $personsSql = $queries[0];
        $clustersSql = $queries[1];
        $membersSql = $queries[2];
        $syncSql = $queries[3];
        $outboxSql = $queries[4];
        $topologySql = $queries[5];
        $conflictsSql = $queries[6];

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
    }

    public function testActivateProjectionDbDeltaIsIdempotentAcrossReactivation(): void
    {
        $this->manager->activate();
        $this->manager->activate();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertCount(14, $queries);
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
        $wpdb->queryResults["SELECT id FROM `wp_acx_persons` WHERE name = 'Ada Lovelace'"] = null;

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
        $wpdb->queryResults["SELECT id FROM `wp_acx_persons` WHERE name = 'Grace Hopper'"] = null;
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

        $wpdb->queryResults["SELECT id FROM `wp_acx_persons` WHERE name = 'Katherine Johnson'"] = 13;
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
        $wpdb->queryResults["SELECT id FROM `wp_acx_persons` WHERE name = 'Dorothy Vaughan'"] = null;

        $this->manager->activate();

        $personInsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_persons');
        $this->assertStringContainsString("'Dorothy Vaughan'", $personInsert);
        $clusterUpdate = $this->findQueryContaining($wpdb->queries, "WHERE cluster_uuid = 'cluster-654'");
        $this->assertStringContainsString('UPDATE wp_acx_clusters SET person_id = 1', $clusterUpdate);

        $this->assertFalse(get_option('acx_roster_entries'));
        $this->assertFalse(get_option('acx_roster_assignments'));
    }

    public function testActivateChunksLegacyRosterMigrationUntilSubsequentActivationCompletes(): void
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

        $this->manager->activate();

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
        $this->assertNotFalse(wp_next_scheduled('acx_sync_pull_snapshot'));
		$this->assertNotFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));

        $this->manager->deactivate();

        $this->assertFalse(wp_next_scheduled('acx_sync_pull_snapshot'));
		$this->assertFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));
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
        $this->assertNotFalse(wp_next_scheduled('acx_sync_pull_snapshot'));
		$this->assertNotFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));

        $this->manager->uninstall();

        $this->assertFalse(wp_next_scheduled('acx_sync_pull_snapshot'));
		$this->assertFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));
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
