<?php

declare(strict_types=1);

namespace ContextAltText;

use ContextAltText\Admin\Admin;
use ContextAltText\Admin\DashboardPage;
use ContextAltText\Admin\Menu;
use ContextAltText\Admin\RosterPage;
use ContextAltText\Admin\MediaLibraryPanel;
use ContextAltText\Api\Api;
use ContextAltText\Frontend\Frontend;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Support\LifecycleManager;
use ContextAltText\Template\Template;

class ContextAltText
{
    private Admin $admin;
    private Frontend $frontend;
    private Api $api;
    private Menu $menu;
    private RosterPage $rosterPage;
    private MediaLibraryPanel $mediaLibraryPanel;
    private Template $template;
    private FeatureFlags $featureFlags;
    private LifecycleManager $lifecycle;
    private MissingAltTextScanner $missingAltTextScanner;

    public function __construct(
        Admin $admin,
        Frontend $frontend,
        Api $api,
        Menu $menu,
        RosterPage $rosterPage,
        Template $template,
        FeatureFlags $featureFlags,
        LifecycleManager $lifecycle,
        MissingAltTextScanner $missingAltTextScanner,
        MediaLibraryPanel $mediaLibraryPanel
    ) {
        $this->admin = $admin;
        $this->frontend = $frontend;
        $this->api = $api;
        $this->menu = $menu;
        $this->rosterPage = $rosterPage;
        $this->template = $template;
        $this->featureFlags = $featureFlags;
        $this->lifecycle = $lifecycle;
        $this->missingAltTextScanner = $missingAltTextScanner;
        $this->mediaLibraryPanel = $mediaLibraryPanel;
    }

    public function init(): void
    {
        $this->i18n();
        add_action('init', [$this, 'register_blocks']);

        $this->admin->bootstrap();
        $this->frontend->bootstrap();
        $this->api->init();
        $this->menu->init();
        $this->rosterPage->init();
        $this->template->init();
        $this->missingAltTextScanner->register();
        $this->mediaLibraryPanel->init();
    }

    public function register_blocks(): void
    {
        // Block registration will be added with the admin SPA bundle.
    }

    public function i18n(): void
    {
        load_plugin_textdomain(
            'context-alt-text',
            false,
            dirname(CONTEXT_ALT_TEXT_PLUGIN_BASENAME) . '/public/languages'
        );
    }

    public function lifecycle(): LifecycleManager
    {
        return $this->lifecycle;
    }

    public function featureFlags(): FeatureFlags
    {
        return $this->featureFlags;
    }
}
