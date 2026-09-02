<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\DashboardPage;
use AltContext\Admin\DescriptionHistoryPage;
use AltContext\Admin\Menu;
use AltContext\Admin\RetentionPage;
use AltContext\Admin\RosterPage;
use AltContext\Admin\SettingsPage;
use AltContext\Admin\WorkbenchPage;
use AltContext\Tests\TestCase;
use ReflectionClass;

/**
 * @covers \AltContext\Admin\Menu
 */
class MenuTest extends TestCase
{
    public function testRegistersExpectedAdminMenuLabels(): void
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
                ['alt-context-settings', 'Settings'],
            ],
            $menuItems
        );
    }

    public function testEveryMenuItemPageTitleMatchesItsPageClassTitle(): void
    {
        $dashboardPage = new DashboardPage();
        $workbenchPage = new WorkbenchPage();
        $rosterPage = new RosterPage();
        $settingsPage = new SettingsPage();
        $descriptionHistoryPage = new DescriptionHistoryPage();
        $retentionPage = new RetentionPage();

        $menu = new Menu(
            $dashboardPage,
            $workbenchPage,
            $rosterPage,
            $settingsPage,
            $descriptionHistoryPage,
            $retentionPage
        );

        $menu->register_menu();

        $pagesBySlug = [
            'alt-context-dashboard' => $dashboardPage,
            'alt-context-workbench' => $workbenchPage,
            'alt-context-roster' => $rosterPage,
            'alt-context-description-history' => $descriptionHistoryPage,
            'alt-context-settings' => $settingsPage,
        ];

        $this->assertNotEmpty($GLOBALS['__ac_submenu_pages']);

        foreach ($GLOBALS['__ac_submenu_pages'] as $registered) {
            $slug = $registered['menu_slug'] ?? null;
            $this->assertArrayHasKey($slug, $pagesBySlug, "Unexpected submenu slug: {$slug}");

            $page = $pagesBySlug[$slug];
            $method = (new ReflectionClass($page))->getMethod('getPageTitle');
            $method->setAccessible(true);
            $actualPageTitle = $method->invoke($page);

            $this->assertSame(
                $registered['page_title'] ?? null,
                $actualPageTitle,
                sprintf(
                    "Menu page-title for '%s' does not match %s::getPageTitle().",
                    $slug,
                    get_class($page)
                )
            );
        }
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

    public function testSubmenusAreMeceFrequencyOrderedAndCapabilityStable(): void
    {
        $this->assertTrue(defined(Menu::class . '::SUBMENU_IA'));

        $goals = array_column(Menu::SUBMENU_IA, 'goal');
        $this->assertCount(5, Menu::SUBMENU_IA);
        $this->assertSame(
            ['Overview', 'Review Queue', 'People', 'Description Runs', 'Settings'],
            array_column(Menu::SUBMENU_IA, 'menu_title')
        );
        $this->assertSame($goals, array_unique($goals), 'Each submenu must own exactly one user goal (NAV-05).');

        $byGoal = [];
        foreach (Menu::SUBMENU_IA as $entry) {
            $byGoal[$entry['goal']] = $entry['slug'];
        }

        $this->assertSame('alt-context-dashboard', $byGoal['orient']);
        $this->assertSame('alt-context-workbench', $byGoal['name_person']);
        $this->assertSame('alt-context-roster', $byGoal['manage_named_people']);
        $this->assertSame('alt-context-description-history', $byGoal['see_description_history']);
        $this->assertSame('alt-context-settings', $byGoal['configure_service']);
        $this->assertArrayNotHasKey('control_data_lifecycle', $byGoal);

        $menu = new Menu(
            new DashboardPage(),
            new WorkbenchPage(),
            new RosterPage(),
            new SettingsPage()
        );
        $menu->register_menu();

        $slugs = array_column($GLOBALS['__ac_submenu_pages'], 'menu_slug');
        $this->assertSame(array_column(Menu::SUBMENU_IA, 'slug'), $slugs);

        $iaBySlug = [];
        foreach (Menu::SUBMENU_IA as $entry) {
            $iaBySlug[$entry['slug']] = $entry;
        }

        foreach ($GLOBALS['__ac_submenu_pages'] as $page) {
            $slug = $page['menu_slug'];
            $this->assertSame('manage_options', $page['capability'], "Capability changed for {$slug}");
            $this->assertSame($iaBySlug[$slug]['menu_title'], $page['menu_title']);
        }

        $workbenchIndex = array_search('alt-context-workbench', $slugs, true);
        $settingsIndex = array_search('alt-context-settings', $slugs, true);
        $this->assertNotFalse($workbenchIndex);
        $this->assertNotFalse($settingsIndex);
        $this->assertLessThan($settingsIndex, $workbenchIndex, 'High-frequency Review Queue must sit above rare Settings (NAV-06).');
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

        $this->assertNull($retentionPage, 'Retention is a Settings section, not a top-level submenu (NAV-05).');

        $_GET['page'] = 'alt-context-retention';
        $menu->render_retention_page();
        unset($_GET['page']);

        $this->assertSame(
            '/wp-admin/admin.php?page=alt-context-settings#/settings?section=retention',
            $GLOBALS['__ac_safe_redirect']['location'] ?? null
        );
    }
}
