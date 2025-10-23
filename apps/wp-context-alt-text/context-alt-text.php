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
use ContextAltText\Recognition\IdentifyController;
use ContextAltText\Recognition\RecognitionCli;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionJobRepository;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Recognition\RecognitionObservationRepository;
use ContextAltText\Recognition\RecognitionSettings;
use ContextAltText\Roster\RosterClient;
use ContextAltText\Roster\RosterCli;
use ContextAltText\Roster\RosterObservationManager;
use ContextAltText\Roster\RosterTaxonomy;
use ContextAltText\Roster\RosterSyncScheduler;
use ContextAltText\Shared\Config\SettingsRepository;
use ContextAltText\Shared\Logger;
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

function context_alt_text_settings_repository(): SettingsRepository
{
    static $repository = null;

    if ($repository instanceof SettingsRepository) {
        return $repository;
    }

    $repository = new SettingsRepository();

    return $repository;
}

function context_alt_text(): ContextAltText
{
    static $instance = null;

    if ($instance instanceof ContextAltText) {
        return $instance;
    }

    $scanner = new MissingAltTextScanner();
    $settingsRepository = context_alt_text_settings_repository();
    $featureFlags = new FeatureFlags($settingsRepository);
    $security = new Security();
    $rosterService = context_alt_text_roster_service($security);
    $rosterScheduler = context_alt_text_roster_sync_scheduler($rosterService);
    $dashboardMetrics = new DashboardMetricsService($scanner);
    $recognitionServices = context_alt_text_recognition_services($settingsRepository);
    /** @var RecognitionClient $recognitionClient */
    $recognitionClient = $recognitionServices['client'];
    /** @var RecognitionJobRepository $recognitionJobRepository */
    $recognitionJobRepository = $recognitionServices['jobRepository'];
    /** @var RecognitionObservationRepository $recognitionObservationRepository */
    $recognitionObservationRepository = $recognitionServices['observationRepository'];
    /** @var RecognitionJobService $recognitionJobService */
    $recognitionJobService = $recognitionServices['jobService'];
    $rosterObservationManager = new RosterObservationManager(
        $recognitionObservationRepository,
        $recognitionJobService,
        $rosterService
    );
    $recognitionJobService->setRosterObservationManager($rosterObservationManager);
    $identifyController = new IdentifyController(
        $recognitionClient,
        $rosterService,
        $security
    );
    context_alt_text_roster_taxonomy();
    $workbenchMediaResolver = new WorkbenchMediaResolver($recognitionObservationRepository);
    $dashboardPage = new DashboardPage($dashboardMetrics);
    $workbenchPage = new AltTextWorkbenchPage();
    $automationQueuePage = new AutomationQueuePage();
    $rosterPage = new RosterPage($rosterService, $security, $scanner, $rosterScheduler);
    $settingsPage = new PluginSettingsPage($settingsRepository);
    $settingsPage->init();
    $accountCenterPage = new AccountCenterPage();
    $mediaPanel = new MediaLibraryPanel($scanner);

    $instance = new ContextAltText(
        new Admin(
            $scanner,
            $dashboardMetrics,
            $featureFlags,
            $workbenchMediaResolver,
            $rosterService,
            $rosterScheduler,
            $settingsRepository,
            $rosterObservationManager
        ),
        new Frontend(),
        new Api(
            $dashboardMetrics,
            $featureFlags,
            $workbenchMediaResolver,
            $recognitionJobService,
            $recognitionObservationRepository,
            $rosterService,
            $rosterScheduler,
            $security,
            $settingsRepository,
            $recognitionClient,
            $rosterObservationManager,
            $identifyController
        ),
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
function context_alt_text_recognition_services(?SettingsRepository $settingsRepository = null): array
{
    static $services = null;

    if ($services !== null) {
        return $services;
    }

    $settingsRepository = $settingsRepository ?? context_alt_text_settings_repository();
    $settings = new RecognitionSettings($settingsRepository);
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

function context_alt_text_roster_taxonomy(): RosterTaxonomy
{
    static $taxonomy = null;

    if ($taxonomy instanceof RosterTaxonomy) {
        return $taxonomy;
    }

    $taxonomy = new RosterTaxonomy();
    $taxonomy->init();

    return $taxonomy;
}

/**
 * Fetch a roster snapshot from the recognition service for synchronization.
 *
 * @return array<int,array<string,mixed>>|null
 */
function context_alt_text_fetch_roster_snapshot(): ?array
{
    $services = context_alt_text_recognition_services();
    /** @var RecognitionSettings $settings */
    $settings = $services['settings'];

    $settingsData = context_alt_text_settings_repository()->getRecognitionSettings();
    if (isset($settingsData['enabled']) && !$settingsData['enabled']) {
        return null;
    }

    if (!$settings->isConfigured()) {
        return null;
    }

    /** @var RecognitionClient $client */
    $client = $services['client'];

    $page = 1;
    $perPage = 50;
    $entries = [];

    $baseUrl = $settings->getBaseUrl();
    $urlParser = function_exists('wp_parse_url') ? 'wp_parse_url' : 'parse_url';
    $targetHost = $baseUrl !== null ? (string) $urlParser($baseUrl, PHP_URL_HOST) : null;
    $httpArgsFilter = null;

    if ($targetHost) {
        $httpArgsFilter = static function (array $args, string $url) use ($targetHost, $urlParser): array {
            $host = (string) $urlParser($url, PHP_URL_HOST);

            if ($host === $targetHost) {
                $timeout = isset($args['timeout']) ? (float) $args['timeout'] : 0.0;
                if ($timeout <= 0.0 || $timeout > 5.0) {
                    $args['timeout'] = 5.0;
                }
            }

            return $args;
        };

        add_filter('http_request_args', $httpArgsFilter, 20, 2);
    }

    try {
        do {
            $response = $client->getRosterList($page, $perPage);

            if (!is_array($response) || empty($response['entries']) || !is_array($response['entries'])) {
                break;
            }

            foreach ($response['entries'] as $entry) {
                if (!is_array($entry)) {
                    continue;
                }

                $mapped = context_alt_text_normalize_roster_snapshot_entry($entry);

                if ($mapped !== null) {
                    $entries[] = $mapped;
                }
            }

            $pagination = isset($response['pagination']) && is_array($response['pagination'])
                ? $response['pagination']
                : [];
            $hasNext = !empty($pagination['has_next']);
            $page++;

            if ($page > 20) {
                // Defensive break to avoid infinite loops on unexpected responses.
                break;
            }
        } while ($hasNext);
    } catch (\Throwable $exception) {
        $state = get_option('cat_roster_sync_state');
        if (!is_array($state)) {
            $state = [];
        }

        $state['lastError'] = [
            'message' => $exception->getMessage(),
            'code' => $exception->getCode(),
        ];

        update_option('cat_roster_sync_state', $state);

        return null;
    } finally {
        if ($httpArgsFilter !== null) {
            remove_filter('http_request_args', $httpArgsFilter, 20);
        }
    }

    return $entries !== [] ? $entries : null;
}

/**
 * Map a recognition roster entry into the snapshot structure expected by the sync service.
 *
 * @param array<string,mixed> $entry
 * @return array<string,mixed>|null
 */
function context_alt_text_normalize_roster_snapshot_entry(array $entry): ?array
{
    $id = null;
    foreach (['unique_id', 'id', 'remote_id'] as $key) {
        if (isset($entry[$key]) && is_scalar($entry[$key])) {
            $candidate = (string) $entry[$key];
            if ($candidate !== '') {
                $id = $candidate;
                break;
            }
        }
    }

    if ($id === null) {
        return null;
    }

    $label = null;
    foreach (['display_name', 'name', 'label'] as $key) {
        if (isset($entry[$key]) && is_scalar($entry[$key])) {
            $candidate = (string) $entry[$key];
            if ($candidate !== '') {
                $label = $candidate;
                break;
            }
        }
    }

    $metadata = [];
    if (isset($entry['metadata']) && is_array($entry['metadata'])) {
        $metadata = $entry['metadata'];
    }

    $type = null;
    foreach (['type', 'entity_type'] as $key) {
        if (isset($metadata[$key]) && is_scalar($metadata[$key])) {
            $candidate = (string) $metadata[$key];
            if ($candidate !== '') {
                $type = $candidate;
                break;
            }
        }
    }

    if ($type === null && isset($entry['type']) && is_scalar($entry['type'])) {
        $candidate = (string) $entry['type'];
        if ($candidate !== '') {
            $type = $candidate;
        }
    }

    $referenceImages = [];
    if (isset($entry['reference_images']) && is_array($entry['reference_images'])) {
        $referenceImages = $entry['reference_images'];
    } elseif (isset($entry['referenceImages']) && is_array($entry['referenceImages'])) {
        $referenceImages = $entry['referenceImages'];
    }

    $updatedAt = null;
    foreach (['updated_timestamp', 'updated_at', 'created_timestamp'] as $key) {
        if (isset($entry[$key]) && is_scalar($entry[$key])) {
            $candidate = (string) $entry[$key];
            if ($candidate !== '') {
                $updatedAt = $candidate;
                break;
            }
        }
    }

    return [
        'id' => $id,
        'label' => $label,
        'type' => $type,
        'metadata' => $metadata,
        'reference_images' => $referenceImages,
        'updated_at' => $updatedAt,
    ];
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
    // Initialize logger silently - only log actual events, not initialization
    if (defined('WP_DEBUG') && WP_DEBUG) {
        Logger::setEnabled(true);
        $logDir = WP_CONTENT_DIR . '/uploads/cat-logs';
        if (!file_exists($logDir)) {
            wp_mkdir_p($logDir);
        }
        $logFile = $logDir . '/debug-' . gmdate('Y-m-d') . '.log';
        Logger::setLogFile($logFile);
    } else {
        Logger::setEnabled(false);
    }

    context_alt_text()->init();
});

add_filter('context_alt_text_roster_remote_snapshot', static function ($snapshot) {
    if (is_array($snapshot) && $snapshot !== []) {
        return $snapshot;
    }

    return context_alt_text_fetch_roster_snapshot();
});

if (defined('WP_CLI') && WP_CLI) {
    add_action('plugins_loaded', static function (): void {
        $services = context_alt_text_recognition_services();
        \WP_CLI::add_command(
            'cat-recognition',
            new RecognitionCli($services['client'], $services['jobService'])
        );

        $rosterService = context_alt_text_roster_service();
        $taxonomy = context_alt_text_roster_taxonomy();
        \WP_CLI::add_command(
            'cat-roster',
            new RosterCli($rosterService, $taxonomy)
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
