<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Support\Assets;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Workbench\WorkbenchMediaResolver;

class Admin
{
    public const DASHBOARD_HOOK = 'toplevel_page_context-alt-text-dashboard';

    /**
     * Admin page slugs that should load the single-page app bundle.
     */
    private const SUPPORTED_PAGE_SLUGS = [
        'context-alt-text-dashboard',
        'context-alt-text-workbench',
    ];

    private MissingAltTextScanner $scanner;
    private DashboardMetricsService $dashboardMetrics;
    private FeatureFlags $featureFlags;
    private WorkbenchMediaResolver $mediaResolver;

    public function __construct(
        MissingAltTextScanner $scanner,
        DashboardMetricsService $dashboardMetrics,
        FeatureFlags $featureFlags,
        WorkbenchMediaResolver $mediaResolver
    ) {
        $this->scanner = $scanner;
        $this->dashboardMetrics = $dashboardMetrics;
        $this->featureFlags = $featureFlags;
        $this->mediaResolver = $mediaResolver;
    }

    public function bootstrap(): void
    {
        add_action('admin_enqueue_scripts', [$this, 'enqueue_script']);
    }

    public function enqueue_script(string $hookSuffix): void
    {
        if (!$this->should_enqueue_assets($hookSuffix)) {
            return;
        }

        $scriptHandle = 'context-alt-text-admin';

        if (wp_get_environment_type() === 'development') {
            $devServer = rtrim(CONTEXT_ALT_TEXT_VITE_DEV_SERVER, '/');

            wp_enqueue_script(
                'context-alt-text-admin-dev',
                $devServer . '/@vite/client',
                [],
                null,
                true
            );

            $scriptHandle = 'context-alt-text-admin-entry';
            wp_enqueue_script(
                $scriptHandle,
                $devServer . '/js/admin/main.tsx',
                ['context-alt-text-admin-dev'],
                null,
                true
            );
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
                    [],
                    CONTEXT_ALT_TEXT_VERSION,
                    true
                );
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
                    [],
                    CONTEXT_ALT_TEXT_VERSION,
                    true
                );
            }
        }

        wp_localize_script(
            $scriptHandle,
            'ContextAltTextAdmin',
            [
                'config' => $this->get_config(),
                'data' => $this->get_data(),
            ]
        );
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
        $coverageEndpoint = function_exists('rest_url')
            ? rest_url('context-alt-text/v1/dashboard/coverage')
            : '';
        $workbenchEndpoint = '';
        $workbenchEnabled = $this->featureFlags->workbenchEnabled() || $this->is_workbench_page();

        if ($workbenchEnabled && function_exists('rest_url')) {
            $workbenchEndpoint = rest_url('context-alt-text/v1/workbench/media');
        }

        return [
            'missingAltMediaUrl' => admin_url('upload.php?context_alt_text=missing'),
            'restNonce' => function_exists('wp_create_nonce') ? wp_create_nonce('wp_rest') : '',
            'endpoints' => [
                'coverage' => $coverageEndpoint,
                'workbenchMedia' => $workbenchEndpoint,
            ],
            'featureFlags' => $this->get_feature_flags_config(),
        ];
    }

    public function get_data(): array
    {
        return [
            'summary' => $this->scanner->get_summary(),
            'dashboard' => [
                'hero' => $this->dashboardMetrics->getHeroStatus(),
                'coverage' => $this->dashboardMetrics->getCoverageCard(),
                'latestActivity' => $this->dashboardMetrics->getLatestActivityCard(),
                'recognition' => $this->dashboardMetrics->getRecognitionInsightsCard(),
                'automation' => $this->dashboardMetrics->getAutomationPipelineCard(),
                'footer' => [
                    'actions' => $this->dashboardMetrics->getFooterActions(),
                    'statusText' => $this->dashboardMetrics->getFooterStatusText(),
                ],
            ],
            'workbench' => $this->get_workbench_bootstrap(),
        ];
    }

    private function get_feature_flags_config(): array
    {
        $flags = [
            'coverageTrend' => $this->featureFlags->coverageTrendEnabled(),
            'workbenchEnabled' => $this->featureFlags->workbenchEnabled(),
            'workbenchRecognition' => $this->featureFlags->workbenchRecognitionEnabled(),
            'workbenchBulkAI' => $this->featureFlags->workbenchBulkAIEnabled(),
        ];

        if ($this->is_workbench_page()) {
            $flags['workbenchEnabled'] = true;
        }

        return $flags;
    }

    private function is_workbench_page(): bool
    {
        $page = $_GET['page'] ?? null;

        return is_string($page) && $page === 'context-alt-text-workbench';
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
}
