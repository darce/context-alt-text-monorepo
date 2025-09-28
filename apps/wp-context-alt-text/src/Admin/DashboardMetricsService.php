<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Services\Scan\MissingAltTextScanner;

class DashboardMetricsService
{
    private const FILTER_LATEST_ACTIVITY = 'context_alt_text_dashboard_latest_activity';
    private const FILTER_RECOGNITION_INSIGHTS = 'context_alt_text_dashboard_recognition_insights';
    private const FILTER_AUTOMATION_PIPELINE = 'context_alt_text_dashboard_automation_pipeline';

    private MissingAltTextScanner $scanner;

    public function __construct(MissingAltTextScanner $scanner)
    {
        $this->scanner = $scanner;
    }

    public function getHeroStatus(): array
    {
        $summary = $this->getScanSummary();
        $isScanning = empty($summary['updated_at']);

        $message = $isScanning
            ? __('Scanning media library…', 'context-alt-text')
            : sprintf(
                /* translators: %d is the number of images missing alt text. */
                __('We found %d images missing alt text.', 'context-alt-text'),
                (int) $summary['missing']
            );

        $ctaLabel = __('Open Alt-Text Workbench', 'context-alt-text');
        $ctaUrl = admin_url('admin.php?page=context-alt-text-workbench');

        $lastUpdated = $summary['updated_at']
            ? human_time_diff((int) $summary['updated_at'], time())
            : null;

        return [
            'state' => $isScanning ? 'scanning' : 'ready',
            'message' => $message,
            'cta_label' => $ctaLabel,
            'cta_url' => $ctaUrl,
            'last_updated_human' => $lastUpdated,
        ];
    }

    public function getCoverageCard(): array
    {
        $summary = $this->getScanSummary();
        $total = max(0, (int) $summary['total']);
        $missing = max(0, (int) $summary['missing']);
        $withAlt = max(0, (int) $summary['with_alt']);
        $coverage = $total > 0 ? round(($withAlt / $total) * 100, 1) : 0.0;

        return [
            'total' => $total,
            'missing' => $missing,
            'with_alt' => $withAlt,
            'coverage_percent' => $coverage,
            'trend_series' => $this->getCoverageTrendSeries(),
        ];
    }

    public function getLatestActivityCard(): array
    {
        $defaults = [
            'last_recognition' => null,
            'last_alt_text_generation' => null,
            'last_roster_sync' => null,
            'links' => [],
        ];

        return $this->applyFilters(self::FILTER_LATEST_ACTIVITY, $defaults);
    }

    public function getRecognitionInsightsCard(): array
    {
        $defaults = [
            'pending_faces' => 0,
            'pending_brands' => 0,
            'unresolved_matches' => 0,
            'links' => [],
        ];

        return $this->applyFilters(self::FILTER_RECOGNITION_INSIGHTS, $defaults);
    }

    public function getAutomationPipelineCard(): array
    {
        $defaults = [
            'queued' => 0,
            'running' => 0,
            'completed' => 0,
            'next_run' => null,
            'actions' => [],
        ];

        return $this->applyFilters(self::FILTER_AUTOMATION_PIPELINE, $defaults);
    }

    public function getFooterActions(): array
    {
        return [
            [
                'label' => __('Run scan again', 'context-alt-text'),
                'url' => wp_nonce_url(
                    admin_url('admin-post.php?action=context_alt_text_run_scan'),
                    'context_alt_text_run_scan'
                ),
            ],
            [
                'label' => __('Generate drafts for selection', 'context-alt-text'),
                'url' => wp_nonce_url(
                    admin_url('admin-post.php?action=context_alt_text_generate_drafts'),
                    'context_alt_text_generate_drafts'
                ),
            ],
            [
                'label' => __('Sync roster', 'context-alt-text'),
                'url' => wp_nonce_url(
                    admin_url('admin-post.php?action=context_alt_text_sync_roster'),
                    'context_alt_text_sync_roster'
                ),
            ],
        ];
    }

    public function getFooterStatusText(): string
    {
        $summary = $this->getScanSummary();
        if (!empty($summary['updated_at'])) {
            $timeAgo = human_time_diff((int) $summary['updated_at'], time());
            return sprintf(
                /* translators: %s is a human readable time difference. */
                __('Last scan completed %s ago.', 'context-alt-text'),
                $timeAgo
            );
        }

        return __('Initial scan is in progress.', 'context-alt-text');
    }

    private function getCoverageTrendSeries(): array
    {
        $series = [];
        if (function_exists('get_option')) {
            $series = get_option('context_alt_text_coverage_history', []);
        }

        if (!is_array($series)) {
            return [];
        }

        return $series;
    }

    private function getScanSummary(): array
    {
        $summary = $this->scanner->get_summary();

        return [
            'total' => (int) ($summary['total'] ?? 0),
            'with_alt' => (int) ($summary['with_alt'] ?? 0),
            'missing' => (int) ($summary['missing'] ?? 0),
            'updated_at' => $summary['updated_at'] ?? null,
        ];
    }

    /**
     * @param array<string,mixed> $defaults
     * @return array<string,mixed>
     */
    private function applyFilters(string $hook, array $defaults): array
    {
        if (function_exists('apply_filters')) {
            $filtered = apply_filters($hook, $defaults);
            if (is_array($filtered)) {
                return $filtered;
            }
        }

        return $defaults;
    }
}
