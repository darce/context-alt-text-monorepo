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
            ALT_CONTEXT_VERSION,
            get_option('alt_context_version'),
            'Version should be stored on activation'
        );
    }

    /**
     * Test activate stores install timestamp on first activation.
     */
    public function testActivateSetsInstallTimestampOnFirstRun(): void
    {
        $this->manager->activate();

        $installed = get_option('alt_context_installed');
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
        $this->setOption('alt_context_installed', $originalTimestamp);

        $this->manager->activate();

        $this->assertSame(
            $originalTimestamp,
            get_option('alt_context_installed'),
            'Existing install timestamp should not be overwritten'
        );
    }

    /**
     * Test uninstall removes version option.
     */
    public function testUninstallRemovesVersionOption(): void
    {
        $this->setOption('alt_context_version', '1.0.0');
        $this->setOption('alt_context_installed', time());

        $this->manager->uninstall();

        $this->assertFalse(
            get_option('alt_context_version'),
            'Version option should be removed on uninstall'
        );
    }

    /**
     * Test uninstall removes install timestamp.
     */
    public function testUninstallRemovesInstallTimestamp(): void
    {
        $this->setOption('alt_context_version', '1.0.0');
        $this->setOption('alt_context_installed', time());

        $this->manager->uninstall();

        $this->assertFalse(
            get_option('alt_context_installed'),
            'Install timestamp should be removed on uninstall'
        );
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
    }

    /**
     * Test full lifecycle: activate -> deactivate -> uninstall.
     */
    public function testFullLifecycle(): void
    {
        // Activate
        $this->manager->activate();
        $this->assertSame(ALT_CONTEXT_VERSION, get_option('alt_context_version'));
        $this->assertNotFalse(get_option('alt_context_installed'));

        // Deactivate (should not remove options)
        $this->manager->deactivate();
        $this->assertSame(ALT_CONTEXT_VERSION, get_option('alt_context_version'));
        $this->assertNotFalse(get_option('alt_context_installed'));

        // Uninstall (should remove options)
        $this->manager->uninstall();
        $this->assertFalse(get_option('alt_context_version'));
        $this->assertFalse(get_option('alt_context_installed'));
    }
}
