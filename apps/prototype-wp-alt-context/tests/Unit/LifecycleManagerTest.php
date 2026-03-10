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
        $this->assertStringContainsString('resolution_status', $conflictsSql);
        $this->assertStringContainsString('UNIQUE KEY uq_projection_conflict', $conflictsSql);
    }

    public function testActivateProjectionDbDeltaIsIdempotentAcrossReactivation(): void
    {
        $this->manager->activate();
        $this->manager->activate();

        $queries = $GLOBALS['__ac_dbdelta_queries'] ?? [];
        $this->assertCount(14, $queries);
        $this->assertStringNotContainsString('DROP TABLE', implode("\n", $queries));
    }

    /**
     * Test uninstall removes version option.
     */
    public function testUninstallRemovesVersionOption(): void
    {
        $this->setOption('acx_version', '1.0.0');
        $this->setOption('acx_installed', time());

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
        $this->setOption('acx_installed', time());

        $this->manager->uninstall();

        $this->assertFalse(
            get_option('acx_installed'),
            'Install timestamp should be removed on uninstall'
        );
    }

    public function testDeactivateClearsSnapshotSyncSchedule(): void
    {
        wp_schedule_single_event(time() + 300, 'acx_sync_pull_snapshot');
		wp_schedule_single_event(time() + 300, 'acx_sync_drain_curation_outbox');
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
        wp_schedule_single_event(time() + 300, 'acx_sync_pull_snapshot');
		wp_schedule_single_event(time() + 300, 'acx_sync_drain_curation_outbox');
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
}
