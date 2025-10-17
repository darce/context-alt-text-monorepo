<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Shared\Config\SettingsRepository;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Roster\RosterSyncScheduler;
use ContextAltText\Support\Assets;
use ContextAltText\Roster\RosterPresenter;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Workbench\WorkbenchMediaResolver;
use ContextAltText\Roster\RosterObservationManager;
use function array_map;
use function array_values;
use function current_user_can;
use function get_option;
use function is_array;

class Admin
{
    public const DASHBOARD_HOOK = 'toplevel_page_context-alt-text-dashboard';

    /**
     * Admin page slugs that should load the single-page app bundle.
     */
    private const SUPPORTED_PAGE_SLUGS = [
        'context-alt-text-dashboard',
        'context-alt-text-workbench',
        'context-alt-text-roster',
        'context-alt-text-settings',
    ];

    private MissingAltTextScanner $scanner;
    private DashboardMetricsService $dashboardMetrics;
    private FeatureFlags $featureFlags;
    private WorkbenchMediaResolver $mediaResolver;
    private RosterService $rosterService;
    private RosterSyncScheduler $rosterScheduler;
    private SettingsRepository $settingsRepository;
    private RosterObservationManager $rosterObservations;

    public function __construct(
        MissingAltTextScanner $scanner,
        DashboardMetricsService $dashboardMetrics,
        FeatureFlags $featureFlags,
        WorkbenchMediaResolver $mediaResolver,
        RosterService $rosterService,
        RosterSyncScheduler $rosterScheduler,
        SettingsRepository $settingsRepository,
        RosterObservationManager $rosterObservations
    ) {
        $this->scanner = $scanner;
        $this->dashboardMetrics = $dashboardMetrics;
        $this->featureFlags = $featureFlags;
        $this->mediaResolver = $mediaResolver;
        $this->rosterService = $rosterService;
        $this->rosterScheduler = $rosterScheduler;
        $this->settingsRepository = $settingsRepository;
        $this->rosterObservations = $rosterObservations;
    }

    public function bootstrap(): void
    {
        add_action('admin_enqueue_scripts', [$this, 'enqueue_script']);
        add_filter('script_loader_tag', [$this, 'force_module_type'], 10, 3);
    }

    public function enqueue_script(string $hookSuffix): void
    {
        if (!$this->should_enqueue_assets($hookSuffix)) {
            return;
        }

        $scriptHandle = 'context-alt-text-admin';
        $dependencies = ['wp-element', 'wp-i18n', 'wp-data'];

        if (wp_get_environment_type() === 'development') {
            $devServer = rtrim(CONTEXT_ALT_TEXT_VITE_DEV_SERVER, '/');

            wp_enqueue_script(
                'context-alt-text-admin-dev',
                $devServer . '/@vite/client',
                [],
                null,
                true
            );
            if (function_exists('wp_script_add_data')) {
                \call_user_func('wp_script_add_data', 'context-alt-text-admin-dev', 'type', 'module');
            }

            $scriptHandle = 'context-alt-text-admin-entry';
            wp_enqueue_script(
                $scriptHandle,
                $devServer . '/js/admin/main.tsx',
                array_merge(['context-alt-text-admin-dev'], $dependencies),
                null,
                true
            );
            if (function_exists('wp_script_add_data')) {
                \call_user_func('wp_script_add_data', $scriptHandle, 'type', 'module');
            }
        } else {
            $entry = Assets::getEntry('js/admin/main.tsx');

            if ($entry && isset($entry['file'])) {
                if (!empty($entry['css']) && is_array($entry['css'])) {
                    foreach ($entry['css'] as $index => $cssFile) {
                        wp_enqueue_style(
                            'context-alt-text-admin-' . $index,
                            Assets::assetUrl((string) $cssFile),
                            [],
                            CONTEXT_ALT_TEXT_VERSION
                        );
                    }
                }

                wp_enqueue_script(
                    $scriptHandle,
                    Assets::assetUrl((string) $entry['file']),
                    $dependencies,
                    CONTEXT_ALT_TEXT_VERSION,
                    true
                );
                if (function_exists('wp_script_add_data')) {
                    \call_user_func('wp_script_add_data', $scriptHandle, 'type', 'module');
                }
            } else {
                wp_enqueue_style(
                    'context-alt-text-admin',
                    CONTEXT_ALT_TEXT_PLUGIN_URL . 'public/assets/css/admin.css',
                    [],
                    CONTEXT_ALT_TEXT_VERSION
                );

                wp_enqueue_script(
                    $scriptHandle,
                    CONTEXT_ALT_TEXT_PLUGIN_URL . 'public/assets/js/admin.js',
                    $dependencies,
                    CONTEXT_ALT_TEXT_VERSION,
                    true
                );
                if (function_exists('wp_script_add_data')) {
                    \call_user_func('wp_script_add_data', $scriptHandle, 'type', 'module');
                }
            }
        }

        wp_localize_script(
            $scriptHandle,
            'ContextAltTextAdmin',
            [
                'page' => $this->get_active_route_key(),
                'config' => $this->get_config(),
                'data' => $this->get_data(),
            ]
        );
    }

    /**
     * Ensure the admin bundle is always executed as an ES module, even if the
     * underlying WordPress helper fails to attach the correct attribute.
     */
    public function force_module_type(string $tag, string $handle, string $src): string
    {
        if ($handle !== 'context-alt-text-admin') {
            return $tag;
        }

        if (str_contains($tag, 'type=')) {
            return $tag;
        }

        return str_replace('<script', '<script type="module"', $tag);
    }

    private function should_enqueue_assets(string $hookSuffix): bool
    {
        if ($hookSuffix === self::DASHBOARD_HOOK) {
            return true;
        }

        return $this->is_supported_page_request();
    }

    private function is_supported_page_request(): bool
    {
        $page = $_GET['page'] ?? null;

        if (!is_string($page)) {
            return false;
        }

        return in_array($page, self::SUPPORTED_PAGE_SLUGS, true);
    }

    public function get_config(): array
    {
        $featureFlags = $this->get_feature_flags_config();

        $coverageEndpoint = function_exists('rest_url')
            ? rest_url('context-alt-text/v1/dashboard/coverage')
            : '';

        $workbenchEnabled = $featureFlags['workbenchEnabled'] ?? false;
        $workbenchEndpoint = '';
        if ($workbenchEnabled && function_exists('rest_url')) {
            $workbenchEndpoint = rest_url('context-alt-text/v1/workbench/media');
        }

        $recognitionEnabled = $this->featureFlags->workbenchRecognitionEnabled();
        $rosterEnabled = $featureFlags['rosterEnabled'] ?? false;

        // Debug: Log the flag values
        if (function_exists('error_log')) {
            error_log(sprintf(
                '[CAT] Config: recognitionEnabled=%s, rosterEnabled=%s',
                $recognitionEnabled ? 'true' : 'false',
                $rosterEnabled ? 'true' : 'false'
            ));
        }

        $recognitionAnalyzeEndpoint = '';
        $recognitionJobEndpoint = '';
        $recognitionObservationsEndpoint = '';
        $recognitionObservationUpdateEndpoint = '';
        $observationsRetryEndpoint = '';
        $rosterEndpoint = '';
        $rosterSyncEndpoint = '';

        if ($recognitionEnabled && function_exists('rest_url')) {
            $recognitionAnalyzeEndpoint = rest_url('context-alt-text/v1/recognition/analyze');
            $recognitionJobEndpoint = rtrim(rest_url('context-alt-text/v1/recognition/job/'), '/') . '/';
        }

        // Observations endpoints available when recognition OR roster is enabled
        if (($recognitionEnabled || $rosterEnabled) && function_exists('rest_url')) {
            $recognitionObservationsEndpoint = rest_url('cat/v1/observations');
            $recognitionObservationUpdateEndpoint = rtrim(rest_url('cat/v1/observations/'), '/') . '/';
        }

        // Retry endpoint available when recognition OR roster is enabled
        if (($recognitionEnabled || $rosterEnabled) && function_exists('rest_url')) {
            $observationsRetryEndpoint = rest_url('cat/v1/observations/retry');
        }

        if ($rosterEnabled && function_exists('rest_url')) {
            $rosterEndpoint = rest_url('context-alt-text/v1/roster');
            $rosterSyncEndpoint = rest_url('context-alt-text/v1/roster/sync');
        }

        $settingsEndpoints = $this->get_settings_endpoints();

        return [
            'missingAltMediaUrl' => admin_url('upload.php?context_alt_text=missing'),
            'restNonce' => function_exists('wp_create_nonce') ? wp_create_nonce('wp_rest') : '',
            'endpoints' => [
                'coverage' => $coverageEndpoint,
                'workbenchMedia' => $workbenchEndpoint,
                'recognitionAnalyze' => $recognitionAnalyzeEndpoint,
                'recognitionJob' => $recognitionJobEndpoint,
                'recognitionObservations' => $recognitionObservationsEndpoint,
                'recognitionObservationUpdate' => $recognitionObservationUpdateEndpoint,
                'observationsRetry' => $observationsRetryEndpoint,
                'rosterEntries' => $rosterEndpoint,
                'rosterSync' => $rosterSyncEndpoint,
                'settingsRecognition' => $settingsEndpoints['recognition'],
                'settingsRecognitionTest' => $settingsEndpoints['recognitionTest'],
            ],
            'featureFlags' => $featureFlags,
            'settings' => $settingsEndpoints['meta'],
        ];
    }

    public function get_data(): array
    {
        $rosterBootstrap = $this->get_roster_bootstrap();
        $recognitionCard = $this->decorateRecognitionInsights(
            $this->dashboardMetrics->getRecognitionInsightsCard(),
            $rosterBootstrap['stats'] ?? []
        );

        return [
            'summary' => $this->scanner->get_summary(),
            'dashboard' => [
                'hero' => $this->dashboardMetrics->getHeroStatus(),
                'coverage' => $this->dashboardMetrics->getCoverageCard(),
                'latestActivity' => $this->dashboardMetrics->getLatestActivityCard(),
                'recognition' => $recognitionCard,
                'automation' => $this->dashboardMetrics->getAutomationPipelineCard(),
                'footer' => [
                    'actions' => $this->dashboardMetrics->getFooterActions(),
                    'statusText' => $this->dashboardMetrics->getFooterStatusText(),
                ],
            ],
            'workbench' => $this->get_workbench_bootstrap(),
            'roster' => $rosterBootstrap,
            'settings' => $this->get_settings_bootstrap(),
        ];
    }

    private function get_feature_flags_config(): array
    {
        $abilitiesEnabled = $this->featureFlags->abilitiesEnabled();
        $rosterEnabled = $abilitiesEnabled && $this->featureFlags->rosterUiEnabled();

        $flags = [
            'coverageTrend' => $this->featureFlags->coverageTrendEnabled(),
            'workbenchEnabled' => $this->featureFlags->workbenchEnabled(),
            'workbenchRecognition' => $this->featureFlags->workbenchRecognitionEnabled(),
            'workbenchBulkAI' => $this->featureFlags->workbenchBulkAIEnabled(),
            'abilitiesEnabled' => $abilitiesEnabled,
            'rosterEnabled' => $rosterEnabled,
        ];

        if ($this->is_workbench_page()) {
            $flags['workbenchEnabled'] = true;
        }

        if ($this->is_roster_page()) {
            $flags['abilitiesEnabled'] = true;
            $flags['rosterEnabled'] = true;
        }

        return $flags;
    }

    /**
     * Determine which admin SPA route should be active on initial load.
     */
    private function get_active_route_key(): string
    {
        if ($this->is_roster_page()) {
            return 'roster';
        }

        if ($this->is_workbench_page()) {
            return 'workbench';
        }

        return 'dashboard';
    }

    private function is_workbench_page(): bool
    {
        $page = $_GET['page'] ?? null;

        return is_string($page) && $page === 'context-alt-text-workbench';
    }

    private function is_roster_page(): bool
    {
        $page = $_GET['page'] ?? null;

        return is_string($page) && $page === 'context-alt-text-roster';
    }

    private function get_workbench_bootstrap(): array
    {
        $workbenchEnabled = $this->featureFlags->workbenchEnabled() || $this->is_workbench_page();

        if (!$workbenchEnabled) {
            return [
                'items' => [],
                'viewMode' => 'grid',
            ];
        }

        $result = $this->mediaResolver->fetch([
            'page' => 1,
            'per_page' => 20,
            'status' => 'missing',
        ]);

        return [
            'items' => $result['items'],
            'viewMode' => 'list',
            'pagination' => [
                'page' => 1,
                'perPage' => 20,
                'total' => $result['total'],
                'totalPages' => $result['totalPages'],
            ],
        ];
    }

    /**
     * @param array<string,mixed> $card
     * @param array<string,mixed> $rosterStats
     * @return array<string,mixed>
     */
    private function decorateRecognitionInsights(array $card, array $rosterStats): array
    {
        $pending = isset($rosterStats['local']) ? max(0, (int) $rosterStats['local']) : 0;
        $conflicts = isset($rosterStats['conflicts']) ? max(0, (int) $rosterStats['conflicts']) : 0;
        $total = isset($rosterStats['total']) ? max(0, (int) $rosterStats['total']) : 0;
        $lastHuman = isset($rosterStats['lastSyncHuman']) ? (string) $rosterStats['lastSyncHuman'] : null;
        $lastSyncAt = isset($rosterStats['lastSyncAt']) ? (string) $rosterStats['lastSyncAt'] : null;

        $card['roster_pending'] = $pending;
        $card['roster_conflicts'] = $conflicts;
        $card['roster_total'] = $total;
        $card['last_roster_sync_human'] = ($lastHuman !== '') ? $lastHuman : null;
        $card['last_roster_sync_at'] = ($lastSyncAt !== '') ? $lastSyncAt : null;

        if (!isset($card['links']) || !is_array($card['links'])) {
            $card['links'] = [];
        }

        $card['links']['roster'] = function_exists('admin_url')
            ? admin_url('admin.php?page=context-alt-text-roster')
            : '#';

        return $card;
    }

    private function get_roster_bootstrap(): array
    {
        if (!$this->can_view_roster_data()) {
            return [
                'entries' => [],
                'stats' => RosterPresenter::buildStats([], $this->get_roster_sync_state()),
            ];
        }

        $this->rosterScheduler->runManualSync();

        $entries = $this->rosterService->getLocalRoster();
        $normalized = array_values(array_map([RosterPresenter::class, 'normalizeEntry'], $entries));

        if ($normalized !== []) {
            $this->rosterObservations->retryPendingForEntries($normalized);
            $this->rosterObservations->autoAssignPending($normalized);
        }

        return [
            'entries' => $normalized,
            'stats' => RosterPresenter::buildStats($normalized, $this->get_roster_sync_state()),
        ];
    }

    private function get_settings_bootstrap(): array
    {
        $recognition = $this->settingsRepository->getRecognitionSettings();

        return [
            'recognition' => [
                'baseUrl' => $recognition['baseUrl'],
                'apiKey' => $recognition['apiKey'],
                'timeoutMs' => $recognition['timeoutMs'],
                'modelProfile' => $recognition['modelProfile'],
                'enabled' => $recognition['enabled'],
            ],
        ];
    }

    private function get_settings_endpoints(): array
    {
        $recognitionEndpoint = '';
        $recognitionTestEndpoint = '';

        if (function_exists('rest_url')) {
            $recognitionEndpoint = rest_url('context-alt-text/v1/settings/recognition');
            $recognitionTestEndpoint = rest_url('context-alt-text/v1/settings/recognition/test');
        }

        return [
            'recognition' => $recognitionEndpoint,
            'recognitionTest' => $recognitionTestEndpoint,
            'meta' => [
                'recognition' => [
                    'canManage' => current_user_can('manage_options'),
                ],
            ],
        ];
    }

    private function can_view_roster_data(): bool
    {
        if ($this->is_roster_page()) {
            return true;
        }

        return $this->featureFlags->abilitiesEnabled() && $this->featureFlags->rosterUiEnabled();
    }

    /**
     * @return array<string,mixed>
     */
    private function get_roster_sync_state(): array
    {
        $state = get_option('cat_roster_sync_state');

        return is_array($state) ? $state : [];
    }
}
