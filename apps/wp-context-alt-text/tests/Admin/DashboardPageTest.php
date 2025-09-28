<?php

declare(strict_types=1);

use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Admin\DashboardPage;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class DashboardPageTest extends TestCase
{
    public function test_render_outputs_dashboard_cards(): void
    {
        $metrics = new class extends DashboardMetricsService {
            public function __construct()
            {
                // Skip parent constructor; stub methods provide data.
            }

            public function getHeroStatus(): array
            {
                return [
                    'state' => 'ready',
                    'message' => 'We found 5 images missing alt text.',
                    'cta_label' => 'Open Alt-Text Workbench',
                    'cta_url' => '/wp-admin/admin.php?page=context-alt-text-workbench',
                    'last_updated_human' => '2 minutes',
                ];
            }

            public function getCoverageCard(): array
            {
                return [
                    'total' => 12,
                    'missing' => 5,
                    'with_alt' => 7,
                    'coverage_percent' => 58.3,
                    'trend_series' => [[
                        'timestamp' => 1,
                        'coverage' => 50,
                    ]],
                ];
            }

            public function getLatestActivityCard(): array
            {
                return [
                    'last_recognition' => time() - 60,
                    'last_alt_text_generation' => 'just now',
                    'last_roster_sync' => null,
                ];
            }

            public function getRecognitionInsightsCard(): array
            {
                return [
                    'pending_faces' => 3,
                    'pending_brands' => 1,
                    'unresolved_matches' => 2,
                ];
            }

            public function getAutomationPipelineCard(): array
            {
                return [
                    'queued' => 1,
                    'running' => 2,
                    'completed' => 4,
                    'next_run' => '5 minutes',
                ];
            }

            public function getFooterActions(): array
            {
                return [
                    ['label' => 'Run scan again', 'url' => '/wp-admin/admin-post.php?action=scan'],
                ];
            }

            public function getFooterStatusText(): string
            {
                return 'Last scan completed 2 minutes ago.';
            }
        };

        $page = new DashboardPage($metrics);

        ob_start();
        $page->render();
        $output = ob_get_clean();

        $this->assertStringContainsString('context-alt-text-dashboard', $output);
        $this->assertStringContainsString('We found 5 images missing alt text.', $output);
        $this->assertStringContainsString('Coverage Progress', $output);
        $this->assertStringContainsString('Latest Activity', $output);
        $this->assertStringContainsString('Run scan again', $output);
    }
}
