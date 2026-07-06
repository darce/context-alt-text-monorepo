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
        $this->assertSame('Review History', $historyPage['menu_title'] ?? null);
        $this->assertSame('manage_options', $historyPage['capability'] ?? null);
        $this->assertIsArray($historyPage['callback'] ?? null);
        $this->assertSame('render_description_history_page', $historyPage['callback'][1] ?? null);
    }
}
