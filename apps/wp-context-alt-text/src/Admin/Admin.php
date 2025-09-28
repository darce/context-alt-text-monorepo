<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Support\Assets;

class Admin
{
    public const DASHBOARD_HOOK = 'toplevel_page_context-alt-text-dashboard';

    private MissingAltTextScanner $scanner;
    private DashboardMetricsService $dashboardMetrics;

    public function __construct(MissingAltTextScanner $scanner, DashboardMetricsService $dashboardMetrics)
    {
        $this->scanner = $scanner;
        $this->dashboardMetrics = $dashboardMetrics;
    }

    public function bootstrap(): void
    {
        add_action('admin_enqueue_scripts', [$this, 'enqueue_script']);
    }

    public function enqueue_script(string $hookSuffix): void
    {
        if ($hookSuffix !== self::DASHBOARD_HOOK) {
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

    public function get_config(): array
    {
        return [
            'missingAltMediaUrl' => admin_url('upload.php?context_alt_text=missing'),
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
        ];
    }
}
