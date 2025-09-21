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

use ContextAltText\Admin\Admin;
use ContextAltText\Admin\Menu;
use ContextAltText\Admin\RosterPage;
use ContextAltText\Api\Api;
use ContextAltText\ContextAltText;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Frontend\Frontend;
use ContextAltText\Security\Security;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Support\LifecycleManager;
use ContextAltText\Template\Template;

if (!defined('ABSPATH')) {
    exit;
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
    $rosterPage = new RosterPage($rosterService, $security, $scanner);

    $instance = new ContextAltText(
        new Admin($scanner),
        new Frontend(),
        new Api(),
        new Menu($rosterPage, $featureFlags),
        $rosterPage,
        new Template(),
        $featureFlags,
        new LifecycleManager($scanner),
        $scanner
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
