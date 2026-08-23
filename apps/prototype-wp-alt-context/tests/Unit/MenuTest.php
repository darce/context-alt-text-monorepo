<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\DashboardPage;
use AltContext\Admin\Menu;
use AltContext\Admin\RosterPage;
use AltContext\Admin\SettingsPage;
use AltContext\Admin\WorkbenchPage;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Admin\Menu
 */
class MenuTest extends TestCase
{
    public function testRegistersMutuallyExclusiveAdminMenuItemsInTaskOrder(): void
    {
        $menu = new Menu(
            new DashboardPage(),
            new WorkbenchPage(),
            new RosterPage(),
            new SettingsPage()
        );

        $menu->register_menu();

        $menuItems = array_map(
            static fn (array $page): array => [
                $page['menu_slug'],
                $page['menu_title'],
            ],
            $GLOBALS['__ac_submenu_pages']
        );

        $this->assertSame(
            [
                ['alt-context-dashboard', 'Overview'],
                ['alt-context-workbench', 'Review Queue'],
                ['alt-context-roster', 'People'],
                ['alt-context-description-history', 'Description Runs'],
                ['alt-context-retention', 'Data Retention'],
                ['alt-context-settings', 'Settings'],
            ],
            $menuItems
        );
    }

    public function testRegistersDescriptionHistorySubmenu(): void
    {
        $menu = new Menu(
            new DashboardPage(),
            new WorkbenchPage(),
            new RosterPage(),
            new SettingsPage()
        );

        $menu->register_menu();

        $historyPage = null;
        foreach ($GLOBALS['__ac_submenu_pages'] as $page) {
            if (($page['menu_slug'] ?? null) === 'alt-context-description-history') {
                $historyPage = $page;
                break;
            }
        }

        $this->assertIsArray($historyPage);
        $this->assertSame('alt-context-dashboard', $historyPage['parent_slug'] ?? null);
        $this->assertSame('Description Runs', $historyPage['menu_title'] ?? null);
        $this->assertSame('manage_options', $historyPage['capability'] ?? null);
        $this->assertIsArray($historyPage['callback'] ?? null);
        $this->assertSame('render_description_history_page', $historyPage['callback'][1] ?? null);
    }

    public function testRegistersRetentionSubmenu(): void
    {
        $menu = new Menu(
            new DashboardPage(),
            new WorkbenchPage(),
            new RosterPage(),
            new SettingsPage()
        );

        $menu->register_menu();

        $retentionPage = null;
        foreach ($GLOBALS['__ac_submenu_pages'] as $page) {
            if (($page['menu_slug'] ?? null) === 'alt-context-retention') {
                $retentionPage = $page;
                break;
            }
        }

        $this->assertIsArray($retentionPage);
        $this->assertSame('alt-context-dashboard', $retentionPage['parent_slug'] ?? null);
        $this->assertSame('Data Retention', $retentionPage['menu_title'] ?? null);
        $this->assertSame('manage_options', $retentionPage['capability'] ?? null);
        $this->assertIsArray($retentionPage['callback'] ?? null);
        $this->assertSame('render_retention_page', $retentionPage['callback'][1] ?? null);
    }
}
