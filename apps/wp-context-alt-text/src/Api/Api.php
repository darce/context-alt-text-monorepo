<?php

declare(strict_types=1);

namespace ContextAltText\Api;

use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Workbench\WorkbenchMediaResolver;
use WP_Error;
use WP_REST_Request;
use function __;
use function add_action;
use function current_user_can;
use function is_array;
use function is_object;
use function max;
use function method_exists;
use function min;
use function register_rest_route;
use function rest_ensure_response;

class Api
{
    private DashboardMetricsService $dashboardMetrics;
    private FeatureFlags $featureFlags;
    private WorkbenchMediaResolver $mediaResolver;
    private RecognitionJobService $recognitionJobs;

    public function __construct(
        DashboardMetricsService $dashboardMetrics,
        FeatureFlags $featureFlags,
        WorkbenchMediaResolver $mediaResolver,
        RecognitionJobService $recognitionJobs
    ) {
        $this->dashboardMetrics = $dashboardMetrics;
        $this->featureFlags = $featureFlags;
        $this->mediaResolver = $mediaResolver;
        $this->recognitionJobs = $recognitionJobs;
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

        if ($this->featureFlags->workbenchRecognitionEnabled()) {
            register_rest_route(
                'context-alt-text/v1',
                '/recognition/analyze',
                [
                    'methods' => 'POST',
                    'callback' => [$this, 'post_recognition_analyze'],
                    'permission_callback' => [$this, 'can_manage_recognition'],
                    'args' => $this->get_recognition_analyze_args(),
                ]
            );

            register_rest_route(
                'context-alt-text/v1',
                '/recognition/job/(?P<id>[a-zA-Z0-9\-]+)',
                [
                    'methods' => 'GET',
                    'callback' => [$this, 'get_recognition_job'],
                    'permission_callback' => [$this, 'can_manage_recognition'],
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

    public function can_manage_recognition(): bool
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

    public function post_recognition_analyze(WP_REST_Request $request)
    {
        $attachmentIds = $request->get_param('attachment_ids');

        if (!is_array($attachmentIds)) {
            return new WP_Error(
                'cat_recognition_invalid_request',
                __('attachment_ids must be an array of attachment IDs.', 'context-alt-text'),
                [
                    'status' => 400,
                ]
            );
        }

        $result = $this->recognitionJobs->submit($attachmentIds);

        if (empty($result['job'])) {
            $message = isset($result['message'])
                ? (string) $result['message']
                : __('No valid attachments were provided for recognition.', 'context-alt-text');

            return new WP_Error(
                'cat_recognition_no_valid_attachments',
                $message,
                [
                    'status' => 400,
                    'rejected' => $result['rejected'] ?? [],
                ]
            );
        }

        return rest_ensure_response([
            'jobId' => $result['jobId'],
            'status' => $result['status'],
            'accepted' => $result['accepted'],
            'rejected' => $result['rejected'],
        ]);
    }

    public function get_recognition_job(WP_REST_Request $request)
    {
        $jobId = (string) $request['id'];
        $job = $this->recognitionJobs->getJob($jobId);

        if ($job === null) {
            return new WP_Error(
                'cat_recognition_job_not_found',
                __('Recognition job could not be found or has expired.', 'context-alt-text'),
                [
                    'status' => 404,
                ]
            );
        }

        return rest_ensure_response($job);
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

    private function get_recognition_analyze_args(): array
    {
        return [
            'attachment_ids' => [
                'description' => 'List of attachment IDs to submit for recognition.',
                'type' => 'array',
                'required' => true,
                'items' => [
                    'type' => 'integer',
                ],
            ],
        ];
    }
}
