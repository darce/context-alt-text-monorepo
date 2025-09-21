<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Support\FeatureFlags;

class Menu
{
    private RosterPage $rosterPage;
    private FeatureFlags $featureFlags;

    public function __construct(RosterPage $rosterPage, FeatureFlags $featureFlags)
    {
        $this->rosterPage = $rosterPage;
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
            __('Roster', 'context-alt-text'),
            __('Roster', 'context-alt-text'),
            'manage_options',
            'context-alt-text-roster',
            [$this, 'render_roster_page']
        );

        if (!$this->featureFlags->abilitiesEnabled()) {
            remove_submenu_page('context-alt-text-dashboard', 'context-alt-text-roster');
        }
    }

    public function admin_page(): void
    {
        $this->rosterPage->render_page();
    }

    public function render_roster_page(): void
    {
        $this->rosterPage->render_page();
    }
}
