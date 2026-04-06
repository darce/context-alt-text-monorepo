<?php

/**
 * Plugin Name: Alt Context
 * Plugin URI: https://github.com/darce/context-alt-text-monorepo
 * Description: Batch-generate contextually rich alt-text with facial recognition.
 * Version: 0.0.2
 * Author: Daniel Arcé
 * License: GPL v2 or later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: alt-context
 * Domain Path: /public/languages
 * Requires at least: 6.0
 * Tested up to: 6.8
 * Requires PHP: 8.0
 * Network: false
 *
 * @package AltContext
 */

declare(strict_types=1);

use AltContext\Admin\Admin;
use AltContext\Admin\Menu;
use AltContext\Api\Api;
use AltContext\Api\XmpEmbedController;
use AltContext\AltContext;
use AltContext\Cli\ResetProjectionCommand;
use AltContext\Cli\XmpBackfillCommand;
use AltContext\Media\XmpPersistenceFactory;
use AltContext\Support\LifecycleManager;
use AltContext\Admin\DashboardPage;
use AltContext\Admin\SettingsPage;
use AltContext\Admin\WorkbenchPage;
use AltContext\Admin\RosterPage;
use Dotenv\Dotenv;

if (!defined('ABSPATH')) {
    exit;
}

/**
 * ------------------------------------------------------------------------
 * Plugin metadata & constants
 * ------------------------------------------------------------------------
 */
$pluginMeta = get_file_data(__FILE__, ['Version' => 'Version']);
$pluginVersion = trim((string) ($pluginMeta['Version'] ?? ''));

if (!defined('ACX_PLUGIN_FILE')) {
    define('ACX_PLUGIN_FILE', __FILE__);
}

if (!defined('ACX_PLUGIN_DIR')) {
    define('ACX_PLUGIN_DIR', plugin_dir_path(__FILE__));
}

if (!defined('ACX_PLUGIN_URL')) {
    define('ACX_PLUGIN_URL', plugin_dir_url(__FILE__));
}

if (!defined('ACX_PLUGIN_BASENAME')) {
    define('ACX_PLUGIN_BASENAME', plugin_basename(__FILE__));
}

if (!defined('ACX_VERSION')) {
    define('ACX_VERSION', $pluginVersion);
}

/**
 * ------------------------------------------------------------------------
 * Autoloader & environment bootstrap
 * ------------------------------------------------------------------------
 */
$altContextAutoload = ACX_PLUGIN_DIR . 'vendor/autoload.php';

if (!is_readable($altContextAutoload)) {
    wp_die(
        esc_html__(
            'Alt Context autoloader is missing. Run composer install inside the plugin directory.',
            'alt-context'
        )
    );
}

require_once $altContextAutoload;

$dotenv = Dotenv::createImmutable(ACX_PLUGIN_DIR, ['.env', '.env.local']);
$dotenv->safeLoad();

function acx_define_env_constant(string $constantName, array $envNames, ?callable $normalizer = null): void
{
    if (defined($constantName)) {
        return;
    }

    foreach ($envNames as $envName) {
        $value = getenv($envName);
        if (false === $value) {
            continue;
        }

        $normalized = trim((string) $value);
        if ('' === $normalized) {
            continue;
        }

        define($constantName, null !== $normalizer ? $normalizer($normalized) : $normalized);
        return;
    }
}

acx_define_env_constant('ACX_VITE_DEV_SERVER', ['ACX_VITE_DEV_SERVER'], static fn (string $value): string => rtrim($value, '/'));
acx_define_env_constant('ACX_RECOGNITION_URL', ['ACX_RECOGNITION_URL', 'ACX_RECOGNITION_BASE_URL'], static fn (string $value): string => rtrim($value, '/'));
acx_define_env_constant('ACX_RECOGNITION_API_KEY', ['ACX_RECOGNITION_API_KEY']);

/**
 * ------------------------------------------------------------------------
 * Plugin lifecycle helpers
 * ------------------------------------------------------------------------
 */
function alt_context(): AltContext
{
    static $instance = null;

	if ($instance instanceof AltContext) {
		return $instance;
	}

	$attachmentXmpMetricsPersistor = XmpPersistenceFactory::create_attachment_xmp_metrics_persistor();

	$instance = new AltContext(
		new Admin(),
		new Api(
			new XmpEmbedController( $attachmentXmpMetricsPersistor )
		),
		new Menu(
			new DashboardPage(),
			new WorkbenchPage(),
			new RosterPage(),
			new SettingsPage()
		),
		new LifecycleManager(),
		$attachmentXmpMetricsPersistor
	);

	return $instance;
}

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
    alt_context()->lifecycle()->uninstall();
}

function acx_load_textdomain(): void
{
    load_plugin_textdomain(
        'alt-context',
        false,
        dirname(plugin_basename(__FILE__)) . '/public/languages'
    );
}

function acx_register_cli_commands(): void
{
    if (!class_exists('WP_CLI')) {
        return;
    }

    WP_CLI::add_command('acx xmp-backfill', new XmpBackfillCommand());
    WP_CLI::add_command('acx reset-projection', new ResetProjectionCommand());
}

/**
 * ------------------------------------------------------------------------
 * WordPress hooks
 * ------------------------------------------------------------------------
 */
add_action('plugins_loaded', static function (): void {
    alt_context()->init();
});
add_action('init', 'acx_load_textdomain');

if (defined('WP_CLI') && WP_CLI) {
    add_action('plugins_loaded', 'acx_register_cli_commands', 11);
}

register_activation_hook(__FILE__, 'alt_context_activate');
register_deactivation_hook(__FILE__, 'alt_context_deactivate');
register_uninstall_hook(__FILE__, 'alt_context_uninstall');
