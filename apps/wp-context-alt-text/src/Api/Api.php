<?php

declare(strict_types=1);

namespace ContextAltText\Api;

use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Workbench\WorkbenchMediaResolver;
use function current_user_can;
use function register_rest_route;
use function rest_ensure_response;
use function is_object;
use function method_exists;
use function is_array;
use function max;
use function min;

class Api
{
    private DashboardMetricsService $dashboardMetrics;
    private FeatureFlags $featureFlags;
    private WorkbenchMediaResolver $mediaResolver;

    public function __construct(
        DashboardMetricsService $dashboardMetrics,
        FeatureFlags $featureFlags,
        WorkbenchMediaResolver $mediaResolver
    ) {
        $this->dashboardMetrics = $dashboardMetrics;
        $this->featureFlags = $featureFlags;
        $this->mediaResolver = $mediaResolver;
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

        if ($this->featureFlags->workbenchEnabled()) {
            register_rest_route(
                'context-alt-text/v1',
                '/workbench/media',
                [
                    'methods' => 'GET',
                    'callback' => [$this, 'get_workbench_media'],
                    'permission_callback' => [$this, 'can_view_dashboard'],
                    'args' => $this->get_workbench_media_args(),
                ]
            );
        }
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

    public function get_workbench_media($request)
    {
        $result = $this->mediaResolver->fetch([
            'page' => (int) ($request['page'] ?? 1),
            'per_page' => (int) ($request['per_page'] ?? 20),
            'status' => (string) ($request['status'] ?? 'missing'),
            'search' => $request['search'] ?? null,
        ]);

        $response = rest_ensure_response($result['items']);

        if (is_object($response) && method_exists($response, 'header')) {
            $response->header('X-WP-Total', (string) $result['total']);
            $response->header('X-WP-TotalPages', (string) $result['totalPages']);
        } elseif (is_array($response)) {
            $response['_headers'] = [
                'X-WP-Total' => (string) $result['total'],
                'X-WP-TotalPages' => (string) $result['totalPages'],
            ];
        }

        return $response;
    }

    private function get_workbench_media_args(): array
    {
        return [
            'page' => [
                'description' => 'Page of results to return.',
                'type' => 'integer',
                'default' => 1,
                'sanitize_callback' => static fn($value) => max(1, (int) $value),
            ],
            'per_page' => [
                'description' => 'Number of records per page.',
                'type' => 'integer',
                'default' => 20,
                'sanitize_callback' => static fn($value) => min(100, max(1, (int) $value)),
            ],
            'status' => [
                'description' => 'Filter by alt text status.',
                'type' => 'string',
                'enum' => ['missing', 'draft', 'published', 'all'],
                'default' => 'missing',
            ],
            'search' => [
                'description' => 'Search term for attachment titles.',
                'type' => 'string',
                'default' => null,
            ],
        ];
    }
}
