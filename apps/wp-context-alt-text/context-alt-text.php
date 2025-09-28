<?php

/**
 * Plugin Name: Context Alt Text
 * Plugin URI: https://github.com/darce/context-alt-text-monorepo
 * Description: Batch-generate semantically rich, identity-aware alt text with remote recognition + LLM support.
 * Version: 1.0.0
 * Author: Daniel Darce
 * License: GPL v2 or later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: context-alt-text
 * Domain Path: /public/languages
 * Requires at least: 6.0
 * Tested up to: 6.3
 * Requires PHP: 8.0
 * Network: false
 *
 * @package ContextAltText
 */

declare(strict_types=1);

use ContextAltText\Admin\AccountCenterPage;
use ContextAltText\Admin\Admin;
use ContextAltText\Admin\AltTextWorkbenchPage;
use ContextAltText\Admin\AutomationQueuePage;
use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Admin\DashboardPage;
use ContextAltText\Admin\MediaLibraryPanel;
use ContextAltText\Admin\Menu;
use ContextAltText\Admin\PluginSettingsPage;
use ContextAltText\Admin\RosterPage;
use ContextAltText\Api\Api;
use ContextAltText\ContextAltText;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Frontend\Frontend;
use ContextAltText\Security\Security;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Support\Env;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Support\LifecycleManager;
use ContextAltText\Template\Template;

if (!defined('ABSPATH')) {
    exit;
}

if (!defined('WP_PLUGIN_DIR')) {
    define('WP_PLUGIN_DIR', dirname(__FILE__));
}

if (!function_exists('plugin_dir_path')) {
    function plugin_dir_path(string $file): string
    {
        return rtrim(dirname($file), '/\\') . '/';
    }
}

if (!function_exists('plugin_dir_url')) {
    function plugin_dir_url(string $file): string
    {
        return plugin_dir_path($file);
    }
}

if (!function_exists('plugin_basename')) {
    function plugin_basename(string $file): string
    {
        $pluginRoot = defined('WP_PLUGIN_DIR') ? WP_PLUGIN_DIR : dirname($file);
        return trim(str_replace(rtrim($pluginRoot, '/\\') . '/', '', $file), '/');
    }
}

define('CONTEXT_ALT_TEXT_VERSION', '1.0.0');
define('CONTEXT_ALT_TEXT_PLUGIN_FILE', __FILE__);
define('CONTEXT_ALT_TEXT_PLUGIN_DIR', plugin_dir_path(__FILE__));
define('CONTEXT_ALT_TEXT_PLUGIN_URL', plugin_dir_url(__FILE__));
define('CONTEXT_ALT_TEXT_PLUGIN_BASENAME', plugin_basename(__FILE__));

if (!defined('CAT_ENABLE_ABILITIES')) {
    define('CAT_ENABLE_ABILITIES', false);
}

if (!defined('CAT_ENABLE_MCP')) {
    define('CAT_ENABLE_MCP', false);
}

$contextAltTextAutoload = CONTEXT_ALT_TEXT_PLUGIN_DIR . 'vendor/autoload.php';
if (is_readable($contextAltTextAutoload)) {
    require $contextAltTextAutoload;
} else {
    spl_autoload_register(static function (string $class): void {
        $prefix = 'ContextAltText\\';
        if (!str_starts_with($class, $prefix)) {
            return;
        }

        $relative = substr($class, strlen($prefix));
        $path = CONTEXT_ALT_TEXT_PLUGIN_DIR . 'src/' . str_replace('\\', '/', $relative) . '.php';
        if (is_readable($path)) {
            require $path;
        }
    });
}

require_once CONTEXT_ALT_TEXT_PLUGIN_DIR . 'src/Support/WpFunctionStubs.php';

Env::load(CONTEXT_ALT_TEXT_PLUGIN_DIR . '.env');

if (!defined('CONTEXT_ALT_TEXT_VITE_DEV_SERVER')) {
    $envValue = getenv('CAT_VITE_DEV_SERVER');

    if ($envValue === false && isset($_ENV['CAT_VITE_DEV_SERVER'])) {
        $envValue = (string) $_ENV['CAT_VITE_DEV_SERVER'];
    }

    $devServer = $envValue ? rtrim((string) $envValue, '/') : 'http://localhost:5173';

    define('CONTEXT_ALT_TEXT_VITE_DEV_SERVER', $devServer);
}

function context_alt_text(): ContextAltText
{
    static $instance = null;

    if ($instance instanceof ContextAltText) {
        return $instance;
    }

    $scanner = new MissingAltTextScanner();
    $featureFlags = new FeatureFlags();
    $security = new Security();
    $rosterService = new RosterService($security);
    $dashboardMetrics = new DashboardMetricsService($scanner);
    $dashboardPage = new DashboardPage($dashboardMetrics);
    $workbenchPage = new AltTextWorkbenchPage();
    $automationQueuePage = new AutomationQueuePage();
    $rosterPage = new RosterPage($rosterService, $security, $scanner);
    $settingsPage = new PluginSettingsPage();
    $accountCenterPage = new AccountCenterPage();
    $mediaPanel = new MediaLibraryPanel($scanner);

    $instance = new ContextAltText(
        new Admin($scanner, $dashboardMetrics),
        new Frontend(),
        new Api($dashboardMetrics),
        new Menu(
            $dashboardPage,
            $workbenchPage,
            $automationQueuePage,
            $rosterPage,
            $settingsPage,
            $accountCenterPage,
            $featureFlags
        ),
        $rosterPage,
        new Template(),
        $featureFlags,
        new LifecycleManager($scanner),
        $scanner,
        $mediaPanel
    );

    return $instance;
}

add_action('plugins_loaded', static function (): void {
    context_alt_text()->init();
});

function context_alt_text_activate(): void
{
    context_alt_text()->lifecycle()->activate();
}

function context_alt_text_deactivate(): void
{
    context_alt_text()->lifecycle()->deactivate();
}

function context_alt_text_uninstall(): void
{
    $plugin = context_alt_text();
    $plugin->lifecycle()->uninstall();
}

register_activation_hook(__FILE__, 'context_alt_text_activate');
register_deactivation_hook(__FILE__, 'context_alt_text_deactivate');
register_uninstall_hook(__FILE__, 'context_alt_text_uninstall');
