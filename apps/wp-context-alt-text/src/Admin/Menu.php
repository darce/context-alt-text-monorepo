<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Support\FeatureFlags;

class Menu
{
    private DashboardPage $dashboardPage;
    private AltTextWorkbenchPage $workbenchPage;
    private AutomationQueuePage $automationQueuePage;
    private RosterPage $rosterPage;
    private PluginSettingsPage $settingsPage;
    private AccountCenterPage $accountCenterPage;
    private FeatureFlags $featureFlags;

    public function __construct(
        DashboardPage $dashboardPage,
        AltTextWorkbenchPage $workbenchPage,
        AutomationQueuePage $automationQueuePage,
        RosterPage $rosterPage,
        PluginSettingsPage $settingsPage,
        AccountCenterPage $accountCenterPage,
        FeatureFlags $featureFlags
    ) {
        $this->dashboardPage = $dashboardPage;
        $this->workbenchPage = $workbenchPage;
        $this->automationQueuePage = $automationQueuePage;
        $this->rosterPage = $rosterPage;
        $this->settingsPage = $settingsPage;
        $this->accountCenterPage = $accountCenterPage;
        $this->featureFlags = $featureFlags;
    }

    public function init(): void
    {
        add_action('admin_menu', [$this, 'menu']);
    }

    public function menu(): void
    {
        add_menu_page(
            __('Context Alt Text', 'context-alt-text'),
            __('Context Alt Text', 'context-alt-text'),
            'manage_options',
            'context-alt-text-dashboard',
            [$this, 'admin_page'],
            'dashicons-universal-access-alt',
            60
        );

        add_submenu_page(
            'context-alt-text-dashboard',
            __('Dashboard Overview', 'context-alt-text'),
            __('Dashboard Overview', 'context-alt-text'),
            'manage_options',
            'context-alt-text-dashboard',
            [$this, 'admin_page']
        );

        add_submenu_page(
            'context-alt-text-dashboard',
            __('Alt-Text Workbench', 'context-alt-text'),
            __('Alt-Text Workbench', 'context-alt-text'),
            'manage_options',
            'context-alt-text-workbench',
            [$this, 'render_workbench_page']
        );

        add_submenu_page(
            'context-alt-text-dashboard',
            __('Automation Queue', 'context-alt-text'),
            __('Automation Queue', 'context-alt-text'),
            'manage_options',
            'context-alt-text-automation',
            [$this, 'render_automation_queue_page']
        );

        add_submenu_page(
            'context-alt-text-dashboard',
            __('Roster Manager', 'context-alt-text'),
            __('Roster Manager', 'context-alt-text'),
            'manage_options',
            'context-alt-text-roster',
            [$this, 'render_roster_page']
        );

        add_submenu_page(
            'context-alt-text-dashboard',
            __('Settings', 'context-alt-text'),
            __('Settings', 'context-alt-text'),
            'manage_options',
            'context-alt-text-settings',
            [$this, 'render_settings_page']
        );

        add_submenu_page(
            'context-alt-text-dashboard',
            __('Account Center', 'context-alt-text'),
            __('Account Center', 'context-alt-text'),
            'manage_options',
            'context-alt-text-account',
            [$this, 'render_account_center_page']
        );

        if (!$this->featureFlags->abilitiesEnabled()) {
            remove_submenu_page('context-alt-text-dashboard', 'context-alt-text-roster');
        }
    }

    public function admin_page(): void
    {
        $this->dashboardPage->render();
    }

    public function render_roster_page(): void
    {
        $this->rosterPage->render_page();
    }

    public function render_workbench_page(): void
    {
        $this->workbenchPage->render();
    }

    public function render_automation_queue_page(): void
    {
        $this->automationQueuePage->render();
    }

    public function render_settings_page(): void
    {
        $this->settingsPage->render();
    }

    public function render_account_center_page(): void
    {
        $this->accountCenterPage->render();
    }
}
