<?php

/**
 * Plugin Name: Alt Context
 * Plugin URI: https://github.com/darce/context-alt-text-monorepo
 * Description: Batch-generate contextually rich alt-text with facial recognition.
 * Version: 0.0.4
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
use AltContext\Cli\DescriptionCommand;
use AltContext\Cli\DescriptionUsageCommand;
use AltContext\Cli\MirrorIntegrityCommand;
use AltContext\Cli\ResetProjectionCommand;
use AltContext\Cli\XmpBackfillCommand;
use AltContext\Cli\DescriptionRefreshCommand;
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
    $acxPluginUrl = '';
    $pluginsUrlFunction = 'plugins_url';
    if (defined('WPINC') && function_exists($pluginsUrlFunction)) {
        $acxPluginUrl = $pluginsUrlFunction('', 'alt-context/alt-context.php');
    } elseif (function_exists('plugin_dir_url')) {
        $acxPluginUrl = plugin_dir_url(__FILE__);
    }
    define(
        'ACX_PLUGIN_URL',
        '' === $acxPluginUrl
            ? ''
            : (function_exists('trailingslashit') ? trailingslashit($acxPluginUrl) : rtrim((string) $acxPluginUrl, '/') . '/')
    );
}

if (!defined('ACX_PLUGIN_BASENAME')) {
    define('ACX_PLUGIN_BASENAME', 'alt-context/alt-context.php');
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

// E15-11 BR-13: Telemetry uses the WordPress-style filename convention
// (src/support/class-telemetry.php); per the project's rg-016 rule, classes
// in that scheme are not PSR-4 autoloadable and rely on a Composer classmap
// that may be stale after `git pull` until `composer dump-autoload` runs.
// Explicit require_once guarantees the class is available on every request
// regardless of classmap staleness.
require_once ACX_PLUGIN_DIR . 'src/support/class-telemetry.php';
if (defined('WP_CLI') && WP_CLI) {
    require_once ACX_PLUGIN_DIR . 'src/api/class-describe-controller.php';
    require_once ACX_PLUGIN_DIR . 'src/api/services/class-description-candidate-service.php';
    require_once ACX_PLUGIN_DIR . 'src/cli/class-description-command.php';
    require_once ACX_PLUGIN_DIR . 'src/cli/class-description-usage-command.php';
    require_once ACX_PLUGIN_DIR . 'src/cli/class-mirror-integrity-command.php';
    require_once ACX_PLUGIN_DIR . 'src/cli/class-description-refresh-command.php';
}

$dotenv = Dotenv::createImmutable(ACX_PLUGIN_DIR, ['.env', '.env.local']);
$dotenv->safeLoad();

function acx_define_env_constant(string $constantName, array $envNames, ?callable $normalizer = null): void
{
    if (defined($constantName)) {
        return;
    }

    // Two-pass resolution to handle the split between PHP's two env stores:
    //
    // - getenv() reflects the OS process environment (putenv(), Apache SetEnv,
    //   systemd Environment=, parent shell exports). Dotenv createImmutable
    //   does NOT call putenv(), so getenv() will not see values loaded from
    //   .env / .env.local files.
    // - $_ENV / $_SERVER are populated by Dotenv createImmutable and (when
    //   variables_order includes E/S) by PHP at startup from the OS env.
    //
    // Precedence: real process env wins over file-loaded values, so an
    // operator override via SetEnv or putenv beats whatever is in .env.local.
    // Within each store we honor the alias order (canonical name first, then
    // legacy aliases) so that fallbacks still work when no canonical value
    // is set.

    // Pass 1: real process env via getenv() (putenv, Apache, systemd, shell exports).
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

    // Pass 2: Dotenv-loaded values in $_ENV / $_SERVER (.env, .env.local).
    //
    // $_ENV and $_SERVER are superglobals, so the WordPress
    // Security.ValidatedSanitizedInput sniff flags reads from them as
    // untrusted input. In this helper they are NOT user input: the values
    // come from the plugin's own .env / .env.local files loaded by Dotenv
    // createImmutable a few lines above, or from operator-controlled
    // process env (Apache SetEnv, systemd Environment=, parent shell
    // exports). Trim() casts to string and normalizes whitespace, which is
    // the only normalization these config values need; we deliberately do
    // not call sanitize_text_field() / wp_unslash() because (1) this helper
    // runs during early plugin bootstrap and the test fixtures stub WP
    // functions selectively, and (2) trimming would corrupt API keys or
    // base URLs that legitimately contain characters those filters strip.
    foreach ($envNames as $envName) {
        // phpcs:ignore WordPress.Security.ValidatedSanitizedInput.InputNotSanitized,WordPress.Security.ValidatedSanitizedInput.MissingUnslash -- env-loaded config, see comment above
        $value = $_ENV[$envName] ?? $_SERVER[$envName] ?? null;
        if (null === $value) {
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
        dirname(ACX_PLUGIN_BASENAME) . '/public/languages'
    );
}

function acx_register_cli_commands(): void
{
    if (!class_exists('WP_CLI')) {
        return;
    }

    WP_CLI::add_command('acx mirror-integrity', new MirrorIntegrityCommand());
    WP_CLI::add_command('acx description-refresh', new DescriptionRefreshCommand());
    WP_CLI::add_command('acx description-usage', new DescriptionUsageCommand());
    WP_CLI::add_command('acx xmp-backfill', new XmpBackfillCommand());
    WP_CLI::add_command('acx reset-projection', new ResetProjectionCommand());
    WP_CLI::add_command('alt-context describe', new DescriptionCommand());
}

/**
 * ------------------------------------------------------------------------
 * WordPress hooks
 * ------------------------------------------------------------------------
 */
add_action('plugins_loaded', static function (): void {
    // Schema upgrades before init: repositories may query new columns during init.
    alt_context()->lifecycle()->maybe_upgrade();
    alt_context()->init();
});
add_action('init', 'acx_load_textdomain');

if (defined('WP_CLI') && WP_CLI) {
    add_action('plugins_loaded', 'acx_register_cli_commands', 11);
}

register_activation_hook(__FILE__, 'alt_context_activate');
register_deactivation_hook(__FILE__, 'alt_context_deactivate');
register_uninstall_hook(__FILE__, 'alt_context_uninstall');
