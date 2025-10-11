<?php

/**
 * Plugin Name: Context Alt Text
 * Plugin URI: https://github.com/darce/context-alt-text-monorepo
 * Description: Batch-generate semantically rich, identity-aware alt text with remote recognition + LLM support.
 * Version: 0.0.1
 * Author: Daniel Arcé
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

require_once __DIR__ . '/src/Support/WpFunctionStubs.php';

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
use ContextAltText\Recognition\RecognitionCli;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionJobRepository;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Recognition\RecognitionObservationRepository;
use ContextAltText\Recognition\RecognitionSettings;
use ContextAltText\Roster\RosterClient;
use ContextAltText\Roster\RosterCli;
use ContextAltText\Roster\RosterSyncScheduler;
use ContextAltText\Workbench\WorkbenchMediaResolver;

if (!defined('ABSPATH')) {
    exit;
}

$pluginMeta = function_exists('get_file_data')
    ? get_file_data(__FILE__, ['Version' => 'Version'])
    : ['Version' => '0.0.1'];

$pluginVersion = trim((string) ($pluginMeta['Version'] ?? ''));

if ($pluginVersion === '') {
    $pluginVersion = '0.0.1';
}

if (!defined('WP_PLUGIN_DIR')) {
    define('WP_PLUGIN_DIR', dirname(__FILE__));
}

define('CONTEXT_ALT_TEXT_VERSION', $pluginVersion);
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

if (!defined('WP_CLI')) {
    define('WP_CLI', false);
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
    $rosterService = context_alt_text_roster_service($security);
    $rosterScheduler = context_alt_text_roster_sync_scheduler($rosterService);
    $dashboardMetrics = new DashboardMetricsService($scanner);
    $dashboardPage = new DashboardPage($dashboardMetrics);
    $workbenchPage = new AltTextWorkbenchPage();
    $automationQueuePage = new AutomationQueuePage();
    $rosterPage = new RosterPage($rosterService, $security, $scanner, $rosterScheduler);
    $settingsPage = new PluginSettingsPage();
    $settingsPage->init();
    $accountCenterPage = new AccountCenterPage();
    $mediaPanel = new MediaLibraryPanel($scanner);
    $workbenchMediaResolver = new WorkbenchMediaResolver();
    $recognitionServices = context_alt_text_recognition_services();
    /** @var RecognitionClient $recognitionClient */
    $recognitionClient = $recognitionServices['client'];
    /** @var RecognitionJobRepository $recognitionJobRepository */
    $recognitionJobRepository = $recognitionServices['jobRepository'];
    /** @var RecognitionObservationRepository $recognitionObservationRepository */
    $recognitionObservationRepository = $recognitionServices['observationRepository'];
    /** @var RecognitionJobService $recognitionJobService */
    $recognitionJobService = $recognitionServices['jobService'];

    $instance = new ContextAltText(
        new Admin($scanner, $dashboardMetrics, $featureFlags, $workbenchMediaResolver),
        new Frontend(),
        new Api($dashboardMetrics, $featureFlags, $workbenchMediaResolver, $recognitionJobService),
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

/**
 * @return array{
 *     settings: RecognitionSettings,
 *     client: RecognitionClient,
 *     jobRepository: RecognitionJobRepository,
 *     observationRepository: RecognitionObservationRepository,
 *     jobService: RecognitionJobService
 * }
 */
function context_alt_text_recognition_services(): array
{
    static $services = null;

    if ($services !== null) {
        return $services;
    }

    $settings = new RecognitionSettings();
    $client = new RecognitionClient($settings);
    $jobRepository = new RecognitionJobRepository();
    $observationRepository = new RecognitionObservationRepository();
    $jobService = new RecognitionJobService($client, $jobRepository, $observationRepository);

    $services = [
        'settings' => $settings,
        'client' => $client,
        'jobRepository' => $jobRepository,
        'observationRepository' => $observationRepository,
        'jobService' => $jobService,
    ];

    return $services;
}

function context_alt_text_roster_service(?Security $security = null): RosterService
{
    static $service = null;

    if ($service instanceof RosterService) {
        return $service;
    }

    $security = $security ?? new Security();
    $recognitionServices = context_alt_text_recognition_services();
    /** @var RecognitionSettings $recognitionSettings */
    $recognitionSettings = $recognitionServices['settings'];
    $rosterClient = new RosterClient($recognitionSettings);

    $service = new RosterService($security, $rosterClient);

    return $service;
}

function context_alt_text_roster_sync_scheduler(?RosterService $service = null): RosterSyncScheduler
{
    static $scheduler = null;

    if ($scheduler instanceof RosterSyncScheduler) {
        return $scheduler;
    }

    $service = $service ?? context_alt_text_roster_service();
    $scheduler = new RosterSyncScheduler($service);
    $scheduler->register();

    return $scheduler;
}

add_action('plugins_loaded', static function (): void {
    context_alt_text()->init();
});

if (defined('WP_CLI') && WP_CLI) {
    add_action('plugins_loaded', static function (): void {
        $services = context_alt_text_recognition_services();
        \WP_CLI::add_command(
            'cat-recognition',
            new RecognitionCli($services['client'], $services['jobService'])
        );

        $rosterService = context_alt_text_roster_service();
        \WP_CLI::add_command(
            'cat-roster',
            new RosterCli($rosterService)
        );
    });
}

function context_alt_text_activate(): void
{
    context_alt_text_roster_sync_scheduler()->activate();
    context_alt_text()->lifecycle()->activate();
}

function context_alt_text_deactivate(): void
{
    context_alt_text_roster_sync_scheduler()->deactivate();
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
