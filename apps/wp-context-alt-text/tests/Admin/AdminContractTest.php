<?php

declare(strict_types=1);

use ContextAltText\Admin\Admin;
use ContextAltText\Admin\DashboardMetricsService;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';
require_once __DIR__ . '/Support/FakeScanner.php';
require_once __DIR__ . '/Support/FakeFeatureFlags.php';
require_once __DIR__ . '/Support/FakeWorkbenchMediaResolver.php';

final class AdminContractTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__cat_options'] = [];
        $GLOBALS['__cat_filters'] = [];
        $_GET = [];
    }

    public function test_admin_bootstrap_config_and_data_match_contract(): void
    {
        $summary = [
            'total' => 120,
            'with_alt' => 80,
            'missing' => 40,
            'updated_at' => time() - 3600,
        ];

        update_option('context_alt_text_coverage_history', [
            [
                'timestamp' => 1712000000,
                'coverage' => 65.5,
                'total' => 120,
                'with_alt' => 78,
                'missing' => 42,
            ],
        ]);

        $scanner = new FakeScanner($summary);
        $dashboardMetrics = new DashboardMetricsService($scanner);
        $featureFlags = new FakeFeatureFlags([
            'coverageTrend' => true,
            'workbenchEnabled' => true,
            'workbenchRecognition' => true,
            'workbenchBulkAI' => true,
        ]);

        $mediaResolver = new FakeWorkbenchMediaResolver([
            'items' => [
                [
                    'id' => '42',
                    'title' => 'Sample asset',
                    'status' => 'missing',
                    'thumbnailUrl' => 'https://example.test/thumb.jpg',
                    'updatedAt' => '2024-01-01T00:00:00Z',
                    'altText' => null,
                    'mimeType' => 'image/jpeg',
                    'dimensions' => ['width' => 800, 'height' => 600],
                    'editUrl' => 'https://example.test/edit/42',
                ],
            ],
            'total' => 1,
            'totalPages' => 1,
        ]);

        $admin = new Admin($scanner, $dashboardMetrics, $featureFlags, $mediaResolver);

        $config = $admin->get_config();
        self::assertArrayHasKey('missingAltMediaUrl', $config);
        self::assertArrayHasKey('restNonce', $config);
        self::assertSame('nonce-wp_rest', $config['restNonce']);
        self::assertArrayHasKey('endpoints', $config);
        self::assertIsArray($config['endpoints']);
        self::assertSame('http://example.test/wp-json/context-alt-text/v1/dashboard/coverage', $config['endpoints']['coverage']);
        self::assertSame('http://example.test/wp-json/context-alt-text/v1/workbench/media', $config['endpoints']['workbenchMedia']);
        self::assertSame('http://example.test/wp-json/context-alt-text/v1/recognition/analyze', $config['endpoints']['recognitionAnalyze']);
        self::assertSame('http://example.test/wp-json/context-alt-text/v1/recognition/job/', $config['endpoints']['recognitionJob']);
        self::assertArrayHasKey('featureFlags', $config);
        self::assertTrue($config['featureFlags']['coverageTrend']);
        self::assertTrue($config['featureFlags']['workbenchEnabled']);
        self::assertTrue($config['featureFlags']['workbenchRecognition']);
        self::assertTrue($config['featureFlags']['workbenchBulkAI']);

        $data = $admin->get_data();
        self::assertArrayHasKey('dashboard', $data);
        self::assertArrayHasKey('workbench', $data);

        $dashboard = $data['dashboard'];
        self::assertArrayHasKey('hero', $dashboard);
        self::assertArrayHasKey('coverage', $dashboard);
        self::assertArrayHasKey('latestActivity', $dashboard);
        self::assertArrayHasKey('recognition', $dashboard);
        self::assertArrayHasKey('automation', $dashboard);
        self::assertArrayHasKey('footer', $dashboard);

        self::assertSame('ready', $dashboard['hero']['state']);
        self::assertArrayHasKey('cta_label', $dashboard['hero']);
        self::assertArrayHasKey('cta_url', $dashboard['hero']);

        $coverage = $dashboard['coverage'];
        self::assertSame(120, $coverage['total']);
        self::assertSame(80, $coverage['with_alt']);
        self::assertSame(40, $coverage['missing']);
        self::assertIsFloat($coverage['coverage_percent']);
        self::assertNotEmpty($coverage['trend_series']);
        self::assertArrayHasKey('timestamp', $coverage['trend_series'][0]);

        $footer = $dashboard['footer'];
        self::assertNotEmpty($footer['actions']);
        self::assertArrayHasKey('label', $footer['actions'][0]);
        self::assertArrayHasKey('url', $footer['actions'][0]);
        self::assertIsString($footer['statusText']);

        $workbench = $data['workbench'];
        self::assertArrayHasKey('items', $workbench);
        self::assertArrayHasKey('viewMode', $workbench);
        self::assertArrayHasKey('pagination', $workbench);
        self::assertSame('list', $workbench['viewMode']);
        self::assertCount(1, $workbench['items']);

        $item = $workbench['items'][0];
        self::assertSame('42', $item['id']);
        self::assertSame('Sample asset', $item['title']);
        self::assertSame('missing', $item['status']);
        self::assertArrayHasKey('dimensions', $item);
        self::assertSame(['width' => 800, 'height' => 600], $item['dimensions']);
        self::assertArrayHasKey('pagination', $workbench);
        self::assertSame(
            [
                'page' => 1,
                'perPage' => 20,
                'total' => 1,
                'totalPages' => 1,
            ],
            $workbench['pagination']
        );
    }
}
