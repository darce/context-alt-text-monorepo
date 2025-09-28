<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Admin;

use ContextAltText\Admin\Admin;
use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use PHPUnit\Framework\TestCase;

use const JSON_THROW_ON_ERROR;
use function array_key_exists;
use function define;
use function defined;
use function file_exists;
use function file_put_contents;
use function is_dir;
use function json_encode;
use function mkdir;
use function unlink;

final class AdminAssetEnqueueTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__cat_scripts'] = [];
        $GLOBALS['__cat_styles'] = [];
        $GLOBALS['__cat_localized_scripts'] = [];
    }

    public function test_enqueue_script_uses_dev_server_when_environment_is_development(): void
    {
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'development';
        if (!defined('CONTEXT_ALT_TEXT_VITE_DEV_SERVER')) {
            define('CONTEXT_ALT_TEXT_VITE_DEV_SERVER', 'http://dev.local:5173');
        }

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return [
                    'total' => 10,
                    'with_alt' => 5,
                    'missing' => 5,
                ];
            }
        };

        $metrics = $this->fakeMetricsService($scanner);
        $admin = new Admin($scanner, $metrics);
        $admin->enqueue_script(Admin::DASHBOARD_HOOK);

        self::assertArrayHasKey('context-alt-text-admin-entry', $GLOBALS['__cat_scripts']);
        $entry = $GLOBALS['__cat_scripts']['context-alt-text-admin-entry'];
        self::assertStringStartsWith('http://dev.local:5173/js/admin/main.tsx', (string) $entry['src']);
        self::assertArrayHasKey('context-alt-text-admin-dev', $GLOBALS['__cat_scripts']);

        $localized = $GLOBALS['__cat_localized_scripts']['context-alt-text-admin-entry']['ContextAltTextAdmin'] ?? null;
        self::assertIsArray($localized);
        self::assertArrayHasKey('dashboard', $localized['data']);
    }

    public function test_enqueue_script_loads_manifest_assets_in_production(): void
    {
        $_ENV['WP_ENVIRONMENT_TYPE'] = 'production';
        if (!defined('CONTEXT_ALT_TEXT_VITE_DEV_SERVER')) {
            define('CONTEXT_ALT_TEXT_VITE_DEV_SERVER', 'http://dev.local:5173');
        }

        $manifestDir = CONTEXT_ALT_TEXT_PLUGIN_DIR . 'public/assets/dist/.vite';
        if (!is_dir($manifestDir)) {
            mkdir($manifestDir, 0777, true);
        }

        $manifestPath = $manifestDir . '/manifest.json';
        file_put_contents($manifestPath, json_encode([
            'js/admin/main.tsx' => [
                'file' => 'js/admin.js',
                'css' => ['css/admin.css'],
            ],
        ], JSON_THROW_ON_ERROR));

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return [
                    'total' => 0,
                    'with_alt' => 0,
                    'missing' => 0,
                ];
            }
        };

        $metrics = $this->fakeMetricsService($scanner);
        $admin = new Admin($scanner, $metrics);
        $admin->enqueue_script(Admin::DASHBOARD_HOOK);

        self::assertArrayHasKey('context-alt-text-admin', $GLOBALS['__cat_scripts']);
        $script = $GLOBALS['__cat_scripts']['context-alt-text-admin'];
        self::assertStringContainsString('public/assets/dist/js/admin.js', (string) $script['src']);

        self::assertTrue(
            array_key_exists('context-alt-text-admin-0', $GLOBALS['__cat_styles']),
            'CSS from manifest should be enqueued'
        );

        if (file_exists($manifestPath)) {
            unlink($manifestPath);
        }
    }

    private function fakeMetricsService(MissingAltTextScanner $scanner): DashboardMetricsService
    {
        return new class($scanner) extends DashboardMetricsService {
            public function __construct(private MissingAltTextScanner $overrideScanner)
            {
                parent::__construct($overrideScanner);
            }

            public function getHeroStatus(): array
            {
                return [
                    'state' => 'ready',
                    'message' => 'Test',
                    'cta_label' => 'Go',
                    'cta_url' => '#',
                ];
            }

            public function getCoverageCard(): array
            {
                return [
                    'total' => 10,
                    'with_alt' => 5,
                    'missing' => 5,
                    'coverage_percent' => 50,
                ];
            }

            public function getLatestActivityCard(): array
            {
                return [
                    'last_recognition' => null,
                    'last_alt_text_generation' => null,
                    'last_roster_sync' => null,
                ];
            }

            public function getRecognitionInsightsCard(): array
            {
                return [
                    'pending_faces' => 0,
                    'pending_brands' => 0,
                    'unresolved_matches' => 0,
                ];
            }

            public function getAutomationPipelineCard(): array
            {
                return [
                    'queued' => 0,
                    'running' => 0,
                    'completed' => 0,
                    'next_run' => null,
                ];
            }

            public function getFooterActions(): array
            {
                return [
                    ['label' => 'Test action', 'url' => '#'],
                ];
            }

            public function getFooterStatusText(): string
            {
                return 'Test status';
            }
        };
    }
}
