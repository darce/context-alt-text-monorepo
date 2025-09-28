<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Api;

use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Api\Api;
use ContextAltText\Services\Scan\MissingAltTextScanner;
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
        $api = new Api($metrics);
        $api->register_routes();

        self::assertNotEmpty($GLOBALS['__cat_rest_routes']);
        $route = $GLOBALS['__cat_rest_routes'][0];
        self::assertSame('context-alt-text/v1', $route['namespace']);
        self::assertSame('/dashboard/coverage', $route['route']);

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
        $api = new Api($metrics);
        $api->register_routes();

        $route = $GLOBALS['__cat_rest_routes'][0];
        $permission = $route['args']['permission_callback'];

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;
        self::assertTrue($permission());

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = false;
        self::assertFalse($permission());
    }
}
