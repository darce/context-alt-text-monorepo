<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Api;

use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Api\Api;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionJobRepository;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Recognition\RecognitionSettings;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Workbench\WorkbenchMediaResolver;
use PHPUnit\Framework\TestCase;

final class ApiTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__cat_rest_routes'] = [];
        $GLOBALS['__cat_current_user_capabilities'] = [];
    }

    public function test_registers_dashboard_coverage_route(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return [
                    'total' => 20,
                    'with_alt' => 12,
                    'missing' => 8,
                ];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $api = $this->createApi($metrics, new FeatureFlags());
        $api->register_routes();

        self::assertNotEmpty($GLOBALS['__cat_rest_routes']);
        $route = $this->find_route('/dashboard/coverage');
        self::assertNotNull($route);

        $callback = $route['args']['callback'];
        $response = $callback();
        self::assertIsArray($response);
        self::assertSame(20, $response['total']);
        self::assertSame(12, $response['with_alt']);
    }

    public function test_dashboard_route_checks_manage_options_capability(): void
    {
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

        $metrics = new DashboardMetricsService($scanner);
        $api = $this->createApi($metrics, new FeatureFlags());
        $api->register_routes();

        $route = $this->find_route('/dashboard/coverage');
        self::assertNotNull($route);
        $permission = $route['args']['permission_callback'];

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;
        self::assertTrue($permission());

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = false;
        self::assertFalse($permission());
    }

    public function test_registers_workbench_media_route_when_feature_enabled(): void
    {
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

        $metrics = new DashboardMetricsService($scanner);
        $api = $this->createApi($metrics, new FeatureFlags());
        $api->register_routes();

        $route = $this->find_route('/workbench/media');
        self::assertNotNull($route);
        self::assertSame('GET', $route['args']['methods']);
    }

    public function test_skips_workbench_media_route_when_feature_disabled(): void
    {
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

        $metrics = new DashboardMetricsService($scanner);
        $flags = new class extends FeatureFlags {
            public function workbenchEnabled(): bool
            {
                return false;
            }
        };

        $api = $this->createApi($metrics, $flags);
        $api->register_routes();

        self::assertNull($this->find_route('/workbench/media'));
    }

    private function find_route(string $path): ?array
    {
        foreach ($GLOBALS['__cat_rest_routes'] as $route) {
            if ($route['route'] === $path) {
                return $route;
            }
        }

        return null;
    }

    private function createApi(DashboardMetricsService $metrics, FeatureFlags $flags): Api
    {
        $client = new class extends RecognitionClient {
            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function analyzeScene(array $payload): array
            {
                return ['outputs' => []];
            }

            public function embeddings(array $payload): array
            {
                return [];
            }
        };

        $jobs = new RecognitionJobService($client, new RecognitionJobRepository());

        return new Api($metrics, $flags, new WorkbenchMediaResolver(), $jobs);
    }
}
