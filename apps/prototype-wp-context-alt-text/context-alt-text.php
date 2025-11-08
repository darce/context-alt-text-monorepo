<?php

/**
 * Plugin Name: Context Alt Text
 * Plugin URI: https://github.com/darce/context-alt-text-monorepo
 * Description: Batch-generate contextually rich alt-text with facial recognition.
 * Version: 0.0.1
 * Author: Daniel Arcé
 * License: GPL v2 or later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: cat
 * Domain Path: /public/languages
 * Requires at least: 6.0
 * Tested up to: 6.3
 * Requires PHP: 8.0
 * Network: false
 *
 * @package CAT
 */

declare(strict_types=1);

use CAT\Admin\Admin;
use CAT\Admin\DashboardPage;
use CAT\Admin\Menu;
use CAT\Api\Api;
use CAT\ContextAltText;
use CAT\Frontend\Frontend;

if (!defined('ABSPATH')) {
    exit;
}

$pluginMeta = get_file_data(__FILE__, ['Version' => 'Version']);

$pluginVersion = trim((string) ($pluginMeta['Version'] ?? ''));

define('WP_PLUGIN_DIR', dirname(__FILE__));
define('CAT_VERSION', $pluginVersion);
define('CAT_PLUGIN_FILE', __FILE__);
define('CAT_PLUGIN_DIR', plugin_dir_path(__FILE__));
define('CAT_PLUGIN_URL', plugin_dir_url(__FILE__));
define('CAT_PLUGIN_BASENAME', plugin_basename(__FILE__));

$catAutoload = CAT_PLUGIN_DIR . 'vendor/autoload.php';
require $catAutoload;

function context_alt_text(): ContextAltText
{
    static $instance = null;

    if ($instance instanceof ContextAltText) {
        return $instance;
    }

    $instance = new ContextAltText(
        new Admin(),
        new Frontend(),
        new Api(),
        new Menu(
            new DashboardPage()
        )
    );

    return $instance;
}

add_action('plugins_loaded', static function (): void {
    context_alt_text()->init();
});
