<?php

/**
 * Plugin Name: Alt Context
 * Plugin URI: https://github.com/darce/context-alt-text-monorepo
 * Description: Batch-generate contextually rich alt-text with facial recognition.
 * Version: 0.0.1
 * Author: Daniel Arcé
 * License: GPL v2 or later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: alt-context
 * Domain Path: /public/languages
 * Requires at least: 6.0
 * Tested up to: 6.3
 * Requires PHP: 8.0 
 * Network: false
 *
 * @package AltContext
 */

declare(strict_types=1);

use AltContext\Admin\Admin;
use AltContext\Admin\DashboardPage;
use AltContext\Admin\Menu;
use AltContext\Api\Api;
use AltContext\AltContext;
use AltContext\Frontend\Frontend;
use AltContext\Support\LifecycleManager;

use Dotenv\Dotenv;

if (!defined('ABSPATH')) {
    exit;
}

if (!defined('ALT_CONTEXT_PLUGIN_FILE')) {
    define('ALT_CONTEXT_PLUGIN_FILE', __FILE__);
}

if (!defined('ALT_CONTEXT_PLUGIN_DIR')) {
    define('ALT_CONTEXT_PLUGIN_DIR', plugin_dir_path(__FILE__));
}

if (!defined('ALT_CONTEXT_PLUGIN_URL')) {
    define('ALT_CONTEXT_PLUGIN_URL', plugin_dir_url(__FILE__));
}

$pluginMeta = get_file_data(__FILE__, ['Version' => 'Version']);
$pluginVersion = trim((string) ($pluginMeta['Version'] ?? ''));
$altContextAutoload = ALT_CONTEXT_PLUGIN_DIR . 'vendor/autoload.php';

if (!defined('ALT_CONTEXT_VERSION')) {
    define('ALT_CONTEXT_VERSION', $pluginVersion);
}

if (!defined('ALT_CONTEXT_PLUGIN_BASENAME')) {
    define('ALT_CONTEXT_PLUGIN_BASENAME', plugin_basename(__FILE__));
}

if (!is_readable($altContextAutoload)) {
    wp_die(
        esc_html__(
            'Alt Context autoloader is missing. Run composer install inside the plugin directory.',
            'alt-context'
        )
    );
}

require_once $altContextAutoload;

$dotenv = Dotenv::createImmutable(ALT_CONTEXT_PLUGIN_DIR);
$dotenv->safeLoad();

$viteServer = getenv('ALT_CONTEXT_VITE_DEV_SERVER');
if ($viteServer && !defined('ALT_CONTEXT_VITE_DEV_SERVER')) {
    define('ALT_CONTEXT_VITE_DEV_SERVER', rtrim((string) $viteServer, '/'));
}

function alt_context(): AltContext
{
    static $instance = null;

    if ($instance instanceof AltContext) {
        return $instance;
    }

    $instance = new AltContext(
        new Admin(),
        new Frontend(),
        new Api(),
        new Menu(
            new DashboardPage()
        ),
        new LifecycleManager()
    );

    return $instance;
}

add_action('plugins_loaded', static function (): void {
    alt_context()->init();
});

function alt_context_activate(): void
{
    alt_context()->lifecycle()->activate();
}

function alt_context_deactivate(): void
{
    alt_context()->lifecycle()->deactivate();
}

function alt_context_uninstall(): void
{
    $plugin = alt_context();
    $plugin->lifecycle()->uninstall();
}

register_activation_hook(__FILE__, 'alt_context_activate');
register_deactivation_hook(__FILE__, 'alt_context_deactivate');
register_uninstall_hook(__FILE__, 'alt_context_uninstall');
