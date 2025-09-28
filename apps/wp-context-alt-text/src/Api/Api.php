<?php

declare(strict_types=1);

namespace ContextAltText\Api;

use ContextAltText\Admin\DashboardMetricsService;
use function current_user_can;
use function register_rest_route;
use function rest_ensure_response;

class Api
{
    private DashboardMetricsService $dashboardMetrics;

    public function __construct(DashboardMetricsService $dashboardMetrics)
    {
        $this->dashboardMetrics = $dashboardMetrics;
    }

    public function init(): void
    {
        add_action('rest_api_init', [$this, 'register_routes']);
    }

    public function register_routes(): void
    {
        register_rest_route(
            'context-alt-text/v1',
            '/dashboard/coverage',
            [
                'methods' => 'GET',
                'callback' => [$this, 'get_dashboard_coverage'],
                'permission_callback' => [$this, 'can_view_dashboard'],
            ]
        );
    }

    /**
     * @return array<string,mixed>
     */
    public function get_dashboard_coverage()
    {
        return rest_ensure_response($this->dashboardMetrics->getCoverageCard());
    }

    public function can_view_dashboard(): bool
    {
        return current_user_can('manage_options');
    }
}
