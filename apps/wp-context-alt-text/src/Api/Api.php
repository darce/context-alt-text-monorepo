<?php

declare(strict_types=1);

namespace ContextAltText\Api;

use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Recognition\ClusterController;
use ContextAltText\Recognition\IdentifyController;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\ScanController;
use ContextAltText\Recognition\RecognitionClientException;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Recognition\RecognitionObservationRepository;
use ContextAltText\Roster\RosterPresenter;
use ContextAltText\Roster\RosterSyncScheduler;
use ContextAltText\Roster\RosterObservationManager;
use ContextAltText\Security\Security;
use ContextAltText\Shared\Config\SettingsRepository;
use ContextAltText\Shared\Logger;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Workbench\WorkbenchMediaResolver;
use WP_Error;
use WP_REST_Request;
use function __;
use function add_action;
use function current_user_can;
use function array_filter;
use function array_key_exists;
use function array_map;
use function array_slice;
use function array_unique;
use function array_values;
use function ceil;
use function count;
use function explode;
use function filter_var;
use function get_option;
use function is_array;
use function is_bool;
use function is_object;
use function in_array;
use function is_string;
use function is_scalar;
use function max;
use function method_exists;
use function min;
use function mb_strtolower;
use function register_rest_route;
use function reset;
use function rest_ensure_response;
use function sanitize_text_field;
use function sprintf;
use function str_contains;
use function trim;

use const FILTER_VALIDATE_BOOLEAN;
use const FILTER_VALIDATE_URL;
use const FILTER_NULL_ON_FAILURE;

class Api
{
    private DashboardMetricsService $dashboardMetrics;
    private FeatureFlags $featureFlags;
    private WorkbenchMediaResolver $mediaResolver;
    private RecognitionJobService $recognitionJobs;
    private RecognitionObservationRepository $recognitionObservations;
    private RosterService $rosterService;
    private RosterSyncScheduler $rosterScheduler;
    private Security $security;
    private SettingsRepository $settingsRepository;
    private RecognitionClient $recognitionClient;
    private RosterObservationManager $rosterObservationManager;
    private IdentifyController $identifyController;
    private ScanController $scanController;
    private ClusterController $clusterController;

    public function __construct(
        DashboardMetricsService $dashboardMetrics,
        FeatureFlags $featureFlags,
        WorkbenchMediaResolver $mediaResolver,
        RecognitionJobService $recognitionJobs,
        RecognitionObservationRepository $recognitionObservations,
        RosterService $rosterService,
        RosterSyncScheduler $rosterScheduler,
        Security $security,
        SettingsRepository $settingsRepository,
        RecognitionClient $recognitionClient,
        RosterObservationManager $rosterObservationManager,
        IdentifyController $identifyController,
        ScanController $scanController,
        ClusterController $clusterController
    ) {
        $this->dashboardMetrics = $dashboardMetrics;
        $this->featureFlags = $featureFlags;
        $this->mediaResolver = $mediaResolver;
        $this->recognitionJobs = $recognitionJobs;
        $this->recognitionObservations = $recognitionObservations;
        $this->rosterService = $rosterService;
        $this->rosterScheduler = $rosterScheduler;
        $this->security = $security;
        $this->settingsRepository = $settingsRepository;
        $this->recognitionClient = $recognitionClient;
        $this->rosterObservationManager = $rosterObservationManager;
        $this->identifyController = $identifyController;
        $this->scanController = $scanController;
        $this->clusterController = $clusterController;
    }

    public function init(): void
    {
        add_action('rest_api_init', [$this, 'register_routes']);
    }

    /**
     * Register an endpoint under cat/v1 with a deprecated context-alt-text/v1 alias
     *
     * @param string $route The route pattern (e.g., '/settings/recognition')
     * @param array<string,mixed> $args The endpoint configuration
     */
    private function register_endpoint_with_alias(string $route, array $args): void
    {
        // Register primary endpoint under cat/v1
        register_rest_route('cat/v1', $route, $args);

        // Register deprecated alias under context-alt-text/v1
        $deprecatedArgs = $args;
        $originalCallback = $args['callback'] ?? null;

        if ($originalCallback !== null) {
            $deprecatedArgs['callback'] = function ($request) use ($originalCallback) {
                // Log deprecation notice
                if (function_exists('error_log')) {
                    error_log(sprintf(
                        '[CAT] Deprecated API call: context-alt-text/v1%s - Use cat/v1%s instead',
                        $request->get_route(),
                        str_replace('/context-alt-text/v1', '', $request->get_route())
                    ));
                }

                // Call original callback
                return call_user_func($originalCallback, $request);
            };
        }

        register_rest_route('context-alt-text/v1', $route, $deprecatedArgs);
    }

    public function register_routes(): void
    {
        // Settings endpoints
        $this->register_endpoint_with_alias(
            '/settings/recognition',
            [
                'methods' => 'GET',
                'callback' => [$this, 'get_recognition_settings'],
                'permission_callback' => [$this, 'can_manage_recognition'],
            ]
        );

        $this->register_endpoint_with_alias(
            '/settings/recognition',
            [
                'methods' => ['POST', 'PUT', 'PATCH'],
                'callback' => [$this, 'post_recognition_settings'],
                'permission_callback' => [$this, 'can_manage_recognition'],
                'args' => $this->get_recognition_settings_args(),
            ]
        );

        $this->register_endpoint_with_alias(
            '/settings/recognition/test',
            [
                'methods' => 'POST',
                'callback' => [$this, 'post_recognition_settings_test'],
                'permission_callback' => [$this, 'can_manage_recognition'],
            ]
        );

        $this->register_endpoint_with_alias(
            '/recognition/scan',
            [
                'methods' => 'POST',
                'callback' => [$this->scanController, 'scanBatch'],
                'permission_callback' => [$this, 'can_trigger_face_scan'],
            ]
        );

        // Dashboard endpoints
        $this->register_endpoint_with_alias(
            '/dashboard/coverage',
            [
                'methods' => 'GET',
                'callback' => [$this, 'get_dashboard_coverage'],
                'permission_callback' => [$this, 'can_view_dashboard'],
            ]
        );

        if ($this->featureFlags->workbenchEnabled()) {
            $this->register_endpoint_with_alias(
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
            $this->register_endpoint_with_alias(
                '/recognition/analyze',
                [
                    'methods' => 'POST',
                    'callback' => [$this, 'post_recognition_analyze'],
                    'permission_callback' => [$this, 'can_manage_recognition'],
                    'args' => $this->get_recognition_analyze_args(),
                ]
            );

            $this->register_endpoint_with_alias(
                '/recognition/job/(?P<id>[a-zA-Z0-9\-]+)',
                [
                    'methods' => 'GET',
                    'callback' => [$this, 'get_recognition_job'],
                    'permission_callback' => [$this, 'can_manage_recognition'],
                ]
            );

            $this->register_endpoint_with_alias(
                '/recognition/identify',
                [
                    'methods' => 'POST',
                    'callback' => [$this->identifyController, 'identify'],
                    'permission_callback' => '__return_true', // Controller handles auth internally
                ]
            );

            $this->register_endpoint_with_alias(
                '/clusters',
                [
                    'methods' => 'GET',
                    'callback' => [$this->clusterController, 'listClusters'],
                    'permission_callback' => '__return_true',
                ]
            );

            $this->register_endpoint_with_alias(
                '/clusters/(?P<id>[^/]+)',
                [
                    'methods' => 'GET',
                    'callback' => [$this->clusterController, 'getClusterDetailPage'],
                    'permission_callback' => '__return_true',
                    'args' => [
                        'page' => [
                            'description' => 'Page number for paginated cluster faces.',
                            'type' => 'integer',
                            'default' => 1,
                        ],
                        'per_page' => [
                            'description' => 'Number of faces per page.',
                            'type' => 'integer',
                            'default' => 20,
                        ],
                    ],
                ]
            );

            $this->register_endpoint_with_alias(
                '/clusters/(?P<id>[^/]+)/suggestions',
                [
                    'methods' => 'GET',
                    'callback' => [$this->clusterController, 'getClusterSuggestions'],
                    'permission_callback' => '__return_true',
                ]
            );

            $this->register_endpoint_with_alias(
                '/clusters/(?P<id>[^/]+)/confirm',
                [
                    'methods' => 'POST',
                    'callback' => [$this->clusterController, 'confirmCluster'],
                    'permission_callback' => '__return_true',
                ]
            );

            // Move faces between clusters
            $this->register_endpoint_with_alias(
                '/unknown-clusters/move',
                [
                    'methods' => 'POST',
                    'callback' => [$this->clusterController, 'moveFaces'],
                    'permission_callback' => '__return_true',
                ]
            );

            // Delete individual face
            $this->register_endpoint_with_alias(
                '/unknown-faces/(?P<id>\d+)',
                [
                    'methods' => 'DELETE',
                    'callback' => [$this->clusterController, 'deleteFace'],
                    'permission_callback' => '__return_true',
                ]
            );

            // Clear all unresolved faces
            $this->register_endpoint_with_alias(
                '/unknown-clusters/clear-all',
                [
                    'methods' => 'POST',
                    'callback' => [$this->clusterController, 'clearAllFaces'],
                    'permission_callback' => '__return_true',
                ]
            );

            // Observations endpoints (already on cat/v1, no alias needed)
            register_rest_route(
                'cat/v1',
                '/observations',
                [
                    'methods' => 'GET',
                    'callback' => [$this, 'get_recognition_observations'],
                    'permission_callback' => [$this, 'can_manage_recognition'],
                    'args' => $this->get_recognition_observations_args(),
                ]
            );

            register_rest_route(
                'cat/v1',
                '/observations/(?P<attachment_id>\d+)/(?P<observation_id>[A-Za-z0-9\-_]+)',
                [
                    'methods' => ['POST', 'PUT', 'PATCH'],
                    'callback' => [$this, 'patch_recognition_observation'],
                    'permission_callback' => [$this, 'can_manage_recognition'],
                ]
            );

            register_rest_route(
                'cat/v1',
                '/observations/retry',
                [
                    'methods' => 'POST',
                    'callback' => [$this, 'post_retry_observations'],
                    'permission_callback' => [$this, 'can_manage_recognition'],
                    'args' => [
                        'entityType' => [
                            'description' => __('Filter observations by entity type (e.g., person, face).', 'context-alt-text'),
                            'type' => 'string',
                            'required' => false,
                        ],
                    ],
                ]
            );
        }

        if ($this->featureFlags->abilitiesEnabled() && $this->featureFlags->rosterUiEnabled()) {
            $this->register_roster_routes();
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

    public function can_trigger_face_scan(): bool
    {
        return current_user_can('upload_files');
    }

    public function get_recognition_settings()
    {
        $settings = $this->settingsRepository->getRecognitionSettings();

        return rest_ensure_response([
            'settings' => $settings,
            'featureFlags' => [
                'workbenchRecognition' => $this->featureFlags->workbenchRecognitionEnabled(),
                'rosterEnabled' => $this->featureFlags->rosterUiEnabled(),
            ],
        ]);
    }

    public function post_recognition_settings(WP_REST_Request $request)
    {
        $payload = $this->prepare_recognition_settings_payload($request);

        if ($payload instanceof WP_Error) {
            return $payload;
        }

        $settings = $this->settingsRepository->saveRecognitionSettings($payload);

        return rest_ensure_response([
            'settings' => $settings,
            'featureFlags' => [
                'workbenchRecognition' => $this->featureFlags->workbenchRecognitionEnabled(),
                'rosterEnabled' => $this->featureFlags->rosterUiEnabled(),
            ],
            'message' => __('Recognition settings updated.', 'context-alt-text'),
        ]);
    }

    public function post_recognition_settings_test()
    {
        try {
            $result = $this->recognitionClient->getHealth();
        } catch (RecognitionClientException $exception) {
            return new WP_Error(
                'cat_recognition_health_unavailable',
                $exception->getMessage(),
                ['status' => 502]
            );
        }

        return rest_ensure_response([
            'ok' => true,
            'status' => $result['status'] ?? 'ok',
            'details' => $result,
        ]);
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
            if (($result['status'] ?? '') === 'deferred') {
                return rest_ensure_response([
                    'jobId' => null,
                    'status' => 'deferred',
                    'accepted' => 0,
                    'rejected' => $result['rejected'] ?? [],
                    'deferred' => $result['deferred'] ?? [],
                ]);
            }

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
            'deferred' => $result['deferred'] ?? [],
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

    public function get_recognition_observations(WP_REST_Request $request)
    {
        $perPage = min(100, max(1, (int) ($request->get_param('per_page') ?? 20)));
        $page = max(1, (int) ($request->get_param('page') ?? 1));
        $status = $this->sanitize_string_param($request->get_param('status'));
        $status = $status !== '' ? $status : null;

        if ($status !== null && !in_array($status, ['matched', 'needs_review'], true)) {
            return new WP_Error(
                'cat_recognition_invalid_status',
                __('Invalid status filter supplied.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        $attachmentIds = $this->extractAttachmentIds($request->get_param('attachment_ids'));

        $items = [];
        $summary = [
            'attachments' => 0,
            'observations' => [
                'total' => 0,
                'matched' => 0,
                'needs_review' => 0,
            ],
        ];

        $filtered = [];
        $total = 0;
        $totalPages = 1;
        $page = max(1, $page);

        if ($attachmentIds === []) {
            $allAttachmentIds = $this->recognitionObservations->getRecentAttachmentIds(100);
            $records = $allAttachmentIds !== []
                ? $this->recognitionObservations->getMany($allAttachmentIds)
                : [];

            foreach ($records as $record) {
                if (!is_array($record)) {
                    continue;
                }

                $recordStatus = ($record['summary']['needs_review'] ?? 0) > 0 ? 'needs_review' : 'matched';

                if ($status !== null && $recordStatus !== $status) {
                    continue;
                }

                $filtered[] = [
                    'record' => $record,
                    'status' => $recordStatus,
                ];
            }

            $total = count($filtered);
            $totalPages = $total > 0 ? (int) ceil($total / $perPage) : 1;
            $page = min($page, $totalPages);
            $page = max(1, $page);
            $offset = ($page - 1) * $perPage;
            $filtered = array_slice($filtered, $offset, $perPage);
        } else {
            $records = $this->recognitionObservations->getMany($attachmentIds);
            foreach ($records as $record) {
                if (!is_array($record)) {
                    continue;
                }

                $recordStatus = ($record['summary']['needs_review'] ?? 0) > 0 ? 'needs_review' : 'matched';

                if ($status !== null && $recordStatus !== $status) {
                    continue;
                }

                $filtered[] = [
                    'record' => $record,
                    'status' => $recordStatus,
                ];
            }

            $total = count($filtered);
            $totalPages = 1;
            $page = 1;
        }

        foreach ($filtered as $entry) {
            $record = $entry['record'];
            $recordStatus = $entry['status'];

            $items[] = [
                'attachmentId' => $record['attachmentId'] ?? null,
                'jobId' => $record['jobId'] ?? null,
                'updatedAt' => $record['updatedAt'] ?? null,
                'summary' => $record['summary'] ?? [],
                'context' => $record['context'] ?? [],
                'observations' => $record['observations'] ?? [],
                'confidenceScore' => $record['confidenceScore'] ?? 0.0,
                'sourceRemoteId' => $record['sourceRemoteId'] ?? null,
                'status' => $recordStatus,
            ];

            $summary['attachments']++;
            $summary['observations']['total'] += (int) ($record['summary']['total'] ?? 0);
            $summary['observations']['matched'] += (int) ($record['summary']['matched'] ?? 0);
            $summary['observations']['needs_review'] += (int) ($record['summary']['needs_review'] ?? 0);
        }

        return rest_ensure_response([
            'items' => $items,
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
            'total_pages' => $totalPages,
            'summary' => $summary,
        ]);
    }

    public function patch_recognition_observation(WP_REST_Request $request)
    {
        $attachmentId = (int) $request['attachment_id'];
        $observationId = (string) $request['observation_id'];

        if ($attachmentId <= 0 || $observationId === '') {
            return new WP_Error(
                'cat_recognition_invalid_observation_request',
                __('A valid attachment and observation identifier are required.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        $payload = [];
        foreach (['status', 'label', 'entityType', 'roster', 'match', 'candidates'] as $key) {
            $value = $request->get_param($key);
            if ($value !== null) {
                $payload[$key] = $value;
            }
        }

        $updates = [];

        if (array_key_exists('status', $payload)) {
            $status = $this->sanitize_string_param($payload['status']);

            if (!in_array($status, ['matched', 'needs_review'], true)) {
                return new WP_Error(
                    'cat_recognition_invalid_status',
                    __('Invalid observation status supplied.', 'context-alt-text'),
                    ['status' => 400]
                );
            }

            $updates['status'] = $status;
        }

        if (array_key_exists('label', $payload)) {
            $updates['label'] = $this->sanitize_string_param($payload['label']);
        }

        if (array_key_exists('entityType', $payload)) {
            $updates['entityType'] = $this->sanitize_string_param($payload['entityType']);
        }

        if (array_key_exists('roster', $payload)) {
            $updates['roster'] = is_array($payload['roster']) ? $payload['roster'] : null;
        }

        if (array_key_exists('match', $payload)) {
            $updates['match'] = is_array($payload['match']) ? $payload['match'] : null;
        }

        if (array_key_exists('candidates', $payload) && is_array($payload['candidates'])) {
            $updates['candidates'] = $payload['candidates'];
        }

        if ($updates === []) {
            return new WP_Error(
                'cat_recognition_no_updates',
                __('No valid updates were provided for the observation.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        $record = $this->recognitionObservations->updateObservation($attachmentId, $observationId, $updates);

        if ($record === null) {
            return new WP_Error(
                'cat_recognition_observation_not_found',
                __('Observation could not be found for the provided attachment.', 'context-alt-text'),
                ['status' => 404]
            );
        }

        return rest_ensure_response([
            'record' => [
                'attachmentId' => $record['attachmentId'] ?? $attachmentId,
                'jobId' => $record['jobId'] ?? null,
                'updatedAt' => $record['updatedAt'] ?? null,
                'summary' => $record['summary'] ?? [],
                'context' => $record['context'] ?? [],
                'observations' => $record['observations'] ?? [],
                'confidenceScore' => $record['confidenceScore'] ?? 0.0,
                'sourceRemoteId' => $record['sourceRemoteId'] ?? null,
            ],
        ]);
    }

    public function post_retry_observations(WP_REST_Request $request)
    {
        $entityType = $this->sanitize_string_param($request->get_param('entityType'));
        $entityType = $entityType !== '' ? $entityType : null;

        Logger::info('Retry observations request', ['entityType' => $entityType]);

        $attachmentIds = $this->recognitionObservations->findAttachmentIdsNeedingReview(
            $entityType,
            100
        );

        Logger::debug('Found attachments needing review', [
            'count' => count($attachmentIds),
            'ids' => $attachmentIds,
        ]);

        if ($attachmentIds === []) {
            Logger::info('No observations found needing review');
            return rest_ensure_response([
                'success' => true,
                'submitted' => 0,
                'message' => __('No observations found that need review.', 'context-alt-text'),
            ]);
        }

        // Skip cooldown for manual retries via the API
        $result = $this->recognitionJobs->submit($attachmentIds, true);

        Logger::info('Job submission result', [
            'status' => $result['status'] ?? 'unknown',
            'accepted' => $result['accepted'] ?? 0,
            'rejected' => count($result['rejected'] ?? []),
            'deferred' => count($result['deferred'] ?? []),
            'jobId' => $result['jobId'] ?? null,
        ]);

        $deferredCount = count($result['deferred'] ?? []);
        $acceptedCount = $result['accepted'] ?? 0;

        if ($deferredCount > 0 && $acceptedCount === 0) {
            return rest_ensure_response([
                'success' => false,
                'submitted' => 0,
                'deferred' => $deferredCount,
                'message' => sprintf(
                    __('%d attachments deferred due to cooldown period (5 min). Please wait before retrying.', 'context-alt-text'),
                    $deferredCount
                ),
            ]);
        }

        $message = $acceptedCount > 0
            ? sprintf(
                __('%d attachments submitted for re-recognition.', 'context-alt-text'),
                $acceptedCount
            )
            : __('No attachments were submitted.', 'context-alt-text');

        if ($deferredCount > 0) {
            $message .= ' ' . sprintf(
                __('%d deferred due to cooldown.', 'context-alt-text'),
                $deferredCount
            );
        }

        return rest_ensure_response([
            'success' => $acceptedCount > 0,
            'submitted' => $acceptedCount,
            'deferred' => $deferredCount,
            'message' => $message,
        ]);
    }

    private function register_roster_routes(): void
    {
        $this->register_endpoint_with_alias(
            '/roster',
            [
                'methods' => 'GET',
                'callback' => [$this, 'get_roster_entries'],
                'permission_callback' => [$this, 'can_manage_roster'],
                'args' => $this->get_roster_list_args(),
            ]
        );

        $this->register_endpoint_with_alias(
            '/roster',
            [
                'methods' => 'POST',
                'callback' => [$this, 'post_roster_entry'],
                'permission_callback' => [$this, 'can_manage_roster'],
                'args' => $this->get_roster_mutation_args(),
            ]
        );

        $this->register_endpoint_with_alias(
            '/roster/sync',
            [
                'methods' => 'POST',
                'callback' => [$this, 'post_roster_sync'],
                'permission_callback' => [$this, 'can_manage_roster'],
            ]
        );

        $this->register_endpoint_with_alias(
            '/roster/(?P<id>[a-zA-Z0-9\-_]+)',
            [
                'methods' => ['PATCH', 'POST', 'PUT'],
                'callback' => [$this, 'patch_roster_entry'],
                'permission_callback' => [$this, 'can_manage_roster'],
                'args' => $this->get_roster_mutation_args(),
            ]
        );

        $this->register_endpoint_with_alias(
            '/roster/(?P<id>[a-zA-Z0-9\-_]+)',
            [
                'methods' => 'DELETE',
                'callback' => [$this, 'delete_roster_entry'],
                'permission_callback' => [$this, 'can_manage_roster'],
            ]
        );
    }

    public function can_manage_roster(): bool
    {
        return $this->security->can_manage_roster();
    }

    public function get_roster_entries(WP_REST_Request $request)
    {
        $type = $this->sanitize_string_param($request->get_param('type'));
        $search = $this->sanitize_string_param($request->get_param('search'));
        $page = max(1, (int) ($request['page'] ?? 1));
        $perPage = min(100, max(1, (int) ($request['per_page'] ?? 20)));

        $filters = [];
        if ($type !== '') {
            $filters['type'] = $type;
        }

        $allEntries = $this->get_normalized_roster($filters);
        $filtered = $allEntries;

        if ($search !== '') {
            $needle = mb_strtolower($search);
            $filtered = array_values(
                array_filter(
                    $allEntries,
                    static function ($entry) use ($needle) {
                        if (!is_array($entry)) {
                            return false;
                        }

                        $label = mb_strtolower((string) ($entry['label'] ?? ''));
                        $typeValue = mb_strtolower((string) ($entry['type'] ?? ''));

                        return str_contains($label, $needle) || str_contains($typeValue, $needle);
                    }
                )
            );
        }

        $total = count($filtered);
        $offset = ($page - 1) * $perPage;
        $entries = array_slice($filtered, $offset, $perPage);

        $syncState = $this->get_roster_sync_state();

        return rest_ensure_response([
            'entries' => $entries,
            'total' => $total,
            'page' => $page,
            'perPage' => $perPage,
            'totalPages' => $total > 0 ? (int) ceil($total / $perPage) : 0,
            'stats' => RosterPresenter::buildStats($allEntries, $syncState),
            'syncState' => $syncState,
            'filters' => [
                'search' => $search,
                'type' => $type,
            ],
        ]);
    }

    public function post_roster_entry(WP_REST_Request $request)
    {
        $resolution = $this->extract_observation_resolution($request);
        $payload = $this->prepare_roster_payload($request);
        $errors = $this->rosterService->validate($payload['data']);

        if ($errors !== []) {
            $message = (string) reset($errors);

            return new WP_Error(
                'cat_roster_invalid_request',
                $message !== '' ? $message : __('Roster entry is invalid.', 'context-alt-text'),
                [
                    'status' => 400,
                    'errors' => $errors,
                ]
            );
        }

        $result = $this->rosterService->createAndSync($payload['data'], $payload['options']);

        if ($result === null) {
            return $this->roster_operation_failed(
                'cat_roster_create_failed',
                __('The roster entry could not be created.', 'context-alt-text')
            );
        }

        $remoteId = $this->extract_remote_id($result);

        $entry = $remoteId !== null ? $this->get_normalized_roster_entry($remoteId) : null;
        $observationRecord = null;

        if ($entry !== null) {
            $this->rosterObservationManager->retryPendingForEntry($entry, $resolution);
        }

        if ($resolution !== null && $entry !== null) {
            $observationRecord = $this->rosterObservationManager->resolveObservationWithRoster($resolution, $entry);
        }

        // Update all observations matched to this roster entry with the current label
        if ($entry !== null) {
            $this->rosterObservationManager->updateObservationsForRosterEntry($entry);
        }

        // Auto-assign observations that already have this entry as a candidate
        // Note: Observations need updated candidates (from re-recognition) to be matched
        $autoMatches = $entry !== null
            ? $this->rosterObservationManager->autoAssignPending([$entry])
            : [];

        // Refresh entry after operations to get updated reference image count
        if ($remoteId !== null) {
            $entry = $this->get_normalized_roster_entry($remoteId);
        }

        $snapshot = $this->build_roster_snapshot();

        return rest_ensure_response([
            'entry' => $entry,
            'stats' => $snapshot['stats'],
            'syncState' => $snapshot['syncState'],
            'observation' => $observationRecord,
            'autoMatched' => $autoMatches,
        ]);
    }

    public function patch_roster_entry(WP_REST_Request $request)
    {
        $remoteId = $this->sanitize_string_param($request['id'] ?? '');

        if ($remoteId === '') {
            return new WP_Error(
                'cat_roster_missing_id',
                __('A roster entry ID is required.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        $resolution = $this->extract_observation_resolution($request);
        $payload = $this->prepare_roster_payload($request);
        $errors = $this->rosterService->validate($payload['data']);

        if ($errors !== []) {
            $message = (string) reset($errors);

            return new WP_Error(
                'cat_roster_invalid_request',
                $message !== '' ? $message : __('Roster entry is invalid.', 'context-alt-text'),
                [
                    'status' => 400,
                    'errors' => $errors,
                ]
            );
        }

        $result = $this->rosterService->updateAndSync($remoteId, $payload['data'], $payload['options']);

        if ($result === null) {
            return $this->roster_operation_failed(
                'cat_roster_update_failed',
                __('The roster entry could not be updated.', 'context-alt-text')
            );
        }

        $entry = $this->get_normalized_roster_entry($remoteId);
        $observationRecord = null;

        if ($entry !== null) {
            $this->rosterObservationManager->retryPendingForEntry($entry, $resolution);
        }

        if ($resolution !== null && $entry !== null) {
            $observationRecord = $this->rosterObservationManager->resolveObservationWithRoster($resolution, $entry);
        }

        // Update all observations matched to this roster entry with the current label
        if ($entry !== null) {
            $this->rosterObservationManager->updateObservationsForRosterEntry($entry);
        }

        $autoMatches = $entry !== null
            ? $this->rosterObservationManager->autoAssignPending([$entry])
            : [];

        // Refresh entry after auto-matching to get updated reference image count
        $entry = $this->get_normalized_roster_entry($remoteId);

        $snapshot = $this->build_roster_snapshot();

        return rest_ensure_response([
            'entry' => $entry,
            'stats' => $snapshot['stats'],
            'syncState' => $snapshot['syncState'],
            'observation' => $observationRecord,
            'autoMatched' => $autoMatches,
        ]);
    }

    public function delete_roster_entry(WP_REST_Request $request)
    {
        $remoteId = $this->sanitize_string_param($request['id'] ?? '');

        if ($remoteId === '') {
            return new WP_Error(
                'cat_roster_missing_id',
                __('A roster entry ID is required.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        $deleted = $this->rosterService->deleteAndArchive($remoteId);

        if (!$deleted) {
            return $this->roster_operation_failed(
                'cat_roster_delete_failed',
                __('The roster entry could not be deleted.', 'context-alt-text')
            );
        }

        $snapshot = $this->build_roster_snapshot();

        return rest_ensure_response([
            'deleted' => true,
            'deletedId' => $remoteId,
            'stats' => $snapshot['stats'],
            'syncState' => $snapshot['syncState'],
        ]);
    }

    public function post_roster_sync(WP_REST_Request $request)
    {
        $result = $this->rosterScheduler->runManualSync();
        $snapshot = $this->build_roster_snapshot();

        $this->rosterObservationManager->retryPendingForEntries($snapshot['entries']);
        $autoMatches = $this->rosterObservationManager->autoAssignPending($snapshot['entries']);

        return rest_ensure_response([
            'changesApplied' => (bool) ($result['changesApplied'] ?? false),
            'state' => $result['state'] ?? [],
            'entries' => $snapshot['entries'],
            'stats' => $snapshot['stats'],
            'syncState' => $snapshot['syncState'],
            'autoMatched' => $autoMatches,
        ]);
    }

    private function get_roster_list_args(): array
    {
        return [
            'search' => [
                'description' => __('Search term for roster label or type.', 'context-alt-text'),
                'type' => 'string',
                'required' => false,
            ],
            'type' => [
                'description' => __('Filter roster entries by type.', 'context-alt-text'),
                'type' => 'string',
                'required' => false,
            ],
            'page' => [
                'description' => __('Page of results to return.', 'context-alt-text'),
                'type' => 'integer',
                'default' => 1,
            ],
            'per_page' => [
                'description' => __('Number of records per page.', 'context-alt-text'),
                'type' => 'integer',
                'default' => 20,
            ],
        ];
    }

    private function get_roster_mutation_args(): array
    {
        return [
            'label' => [
                'description' => __('Display label for the roster entry.', 'context-alt-text'),
                'type' => 'string',
                'required' => true,
            ],
            'type' => [
                'description' => __('Entity type for the roster entry.', 'context-alt-text'),
                'type' => 'string',
                'required' => true,
            ],
            'metadata' => [
                'description' => __('Arbitrary metadata to persist with the roster entry.', 'context-alt-text'),
                'type' => 'object',
                'required' => false,
            ],
            'referenceImages' => [
                'description' => __('Reference images used for recognition embeddings.', 'context-alt-text'),
                'type' => 'array',
                'required' => false,
            ],
        ];
    }

    private function sanitize_string_param($value): string
    {
        if (!is_scalar($value)) {
            return '';
        }

        return sanitize_text_field((string) $value);
    }

    /**
     * @return array{data:array<string,mixed>,options:array<string,mixed>}
     */
    private function prepare_roster_payload(WP_REST_Request $request): array
    {
        $data = [
            'label' => $this->sanitize_string_param($request->get_param('label')),
            'type' => $this->sanitize_string_param($request->get_param('type')),
        ];

        $metadata = $request->get_param('metadata');
        if (is_array($metadata)) {
            $data['metadata'] = $metadata;
        }

        $options = [];
        $referenceImages = $request->get_param('referenceImages');
        if (is_array($referenceImages)) {
            $options['referenceImages'] = array_values(
                array_filter(
                    $referenceImages,
                    static fn($candidate) => is_array($candidate)
                )
            );
        }

        return [
            'data' => $data,
            'options' => $options,
        ];
    }

    /**
     * @return array<string,mixed>|null
     */
    private function extract_observation_resolution(WP_REST_Request $request): ?array
    {
        $raw = $request->get_param('resolveObservation');
        $payload = is_array($raw) ? $raw : [];

        $attachmentId = 0;
        foreach (['attachmentId', 'attachment_id'] as $key) {
            if (isset($payload[$key]) && is_scalar($payload[$key])) {
                $attachmentId = (int) $payload[$key];
                break;
            }
        }

        if ($attachmentId <= 0) {
            $fallbacks = [
                $request->get_param('observationAttachmentId'),
                $request->get_param('attachmentId'),
            ];

            foreach ($fallbacks as $candidate) {
                if (is_scalar($candidate)) {
                    $attachmentId = (int) $candidate;
                    if ($attachmentId > 0) {
                        break;
                    }
                }
            }
        }

        $observationId = '';
        foreach (['observationId', 'observation_id'] as $key) {
            if (isset($payload[$key]) && is_scalar($payload[$key])) {
                $observationId = $this->sanitize_string_param($payload[$key]);
                break;
            }
        }

        if ($observationId === '') {
            $candidate = $request->get_param('observationId');
            if (is_scalar($candidate)) {
                $observationId = $this->sanitize_string_param($candidate);
            }
        }

        if ($attachmentId <= 0 || $observationId === '') {
            return null;
        }

        $status = '';
        if (isset($payload['status']) && is_scalar($payload['status'])) {
            $status = $this->sanitize_string_param($payload['status']);
        } else {
            $candidate = $request->get_param('observationStatus');
            if (is_scalar($candidate)) {
                $status = $this->sanitize_string_param($candidate);
            }
        }

        if (!in_array($status, ['matched', 'needs_review'], true)) {
            $status = 'matched';
        }

        $resolution = [
            'attachmentId' => $attachmentId,
            'observationId' => $observationId,
            'status' => $status,
        ];

        if (isset($payload['label']) && is_scalar($payload['label'])) {
            $resolution['label'] = $this->sanitize_string_param($payload['label']);
        } else {
            $candidate = $request->get_param('observationLabel');
            if (is_scalar($candidate)) {
                $resolution['label'] = $this->sanitize_string_param($candidate);
            }
        }

        if (isset($payload['entityType']) && is_scalar($payload['entityType'])) {
            $resolution['entityType'] = $this->sanitize_string_param($payload['entityType']);
        } else {
            $candidate = $request->get_param('observationEntityType');
            if (is_scalar($candidate)) {
                $resolution['entityType'] = $this->sanitize_string_param($candidate);
            }
        }

        return $resolution;
    }

    private function extract_remote_id($result): ?string
    {
        if (!is_array($result)) {
            return null;
        }

        $candidates = [];

        foreach (['id', 'remoteId', 'remote_id', 'uniqueId', 'unique_id'] as $key) {
            if (isset($result[$key]) && is_scalar($result[$key])) {
                $candidates[] = $result[$key];
            }
        }

        if (isset($result['entry']) && is_array($result['entry'])) {
            foreach (['id', 'remoteId', 'remote_id', 'uniqueId', 'unique_id'] as $key) {
                if (isset($result['entry'][$key]) && is_scalar($result['entry'][$key])) {
                    $candidates[] = $result['entry'][$key];
                }
            }
        }

        foreach ($candidates as $candidate) {
            $value = $this->sanitize_string_param($candidate);
            if ($value !== '') {
                return $value;
            }
        }

        return null;
    }

    /**
     * @param array<string,mixed> $resolution
     * @param array<string,mixed> $entry
     * @return array<string,mixed>|null
     */
    private function resolve_observation_with_roster(array $resolution, array $entry): ?array
    {
        $attachmentId = (int) ($resolution['attachmentId'] ?? 0);
        $observationId = $this->sanitize_string_param($resolution['observationId'] ?? '');

        if ($attachmentId <= 0 || $observationId === '') {
            return null;
        }

        $status = $this->sanitize_string_param($resolution['status'] ?? 'matched');
        if (!in_array($status, ['matched', 'needs_review'], true)) {
            $status = 'matched';
        }

        $updates = ['status' => $status];

        if (isset($resolution['label']) && is_scalar($resolution['label'])) {
            $label = $this->sanitize_string_param($resolution['label']);
        } elseif (isset($entry['label']) && is_scalar($entry['label'])) {
            $label = $this->sanitize_string_param($entry['label']);
        } else {
            $label = '';
        }

        if ($label !== '') {
            $updates['label'] = $label;
        }

        if (isset($resolution['entityType']) && is_scalar($resolution['entityType'])) {
            $entityType = $this->sanitize_string_param($resolution['entityType']);
        } elseif (isset($entry['type']) && is_scalar($entry['type'])) {
            $entityType = $this->sanitize_string_param($entry['type']);
        } else {
            $entityType = '';
        }

        if ($entityType !== '') {
            $updates['entityType'] = $entityType;
        }

        $roster = [];

        if (isset($entry['remoteId']) && is_scalar($entry['remoteId'])) {
            $remoteId = $this->sanitize_string_param($entry['remoteId']);
            if ($remoteId !== '') {
                $roster['remoteId'] = $remoteId;
            }
        }

        if ($label !== '') {
            $roster['name'] = $label;
            $roster['displayName'] = $label;
        }

        if ($entityType !== '') {
            $roster['type'] = $entityType;
        }

        if ($roster !== []) {
            $updates['roster'] = $roster;
        }

        if ($status === 'matched') {
            $updates['match'] = [
                'isMatch' => true,
                'confidence' => 1.0,
                'similarity' => 1.0,
                'threshold' => 0.0,
            ];
        }

        return $this->recognitionObservations->updateObservation($attachmentId, $observationId, $updates);
    }

    private function roster_operation_failed(string $code, string $defaultMessage, int $status = 400): WP_Error
    {
        $state = $this->get_roster_sync_state();
        $lastError = $state['lastError'] ?? null;
        $message = $defaultMessage;

        if (is_array($lastError) && !empty($lastError['message'])) {
            $message = (string) $lastError['message'];
        }

        return new WP_Error(
            $code,
            $message,
            [
                'status' => $status,
                'state' => $state,
            ]
        );
    }

    /**
     * @return array{entries:array<int,array<string,mixed>>,stats:array<string,mixed>,syncState:array<string,mixed>}
     */
    private function build_roster_snapshot(): array
    {
        $entries = $this->get_normalized_roster();
        $syncState = $this->get_roster_sync_state();

        return [
            'entries' => $entries,
            'stats' => RosterPresenter::buildStats($entries, $syncState),
            'syncState' => $syncState,
        ];
    }

    /**
     * @param array<string,mixed> $filters
     * @return array<int,array<string,mixed>>
     */
    private function get_normalized_roster(array $filters = []): array
    {
        $entries = $this->rosterService->getLocalRoster($filters);

        return array_values(array_map([RosterPresenter::class, 'normalizeEntry'], $entries));
    }

    private function get_normalized_roster_entry(string $remoteId): ?array
    {
        $entry = $this->rosterService->getEntryById($remoteId);

        if ($entry === null) {
            return null;
        }

        return RosterPresenter::normalizeEntry($entry);
    }

    /**
     * @return array<string,mixed>
     */
    private function get_roster_sync_state(): array
    {
        $state = get_option('cat_roster_sync_state');

        return is_array($state) ? $state : [];
    }

    private function get_recognition_settings_args(): array
    {
        return [
            'baseUrl' => [
                'description' => __('Base URL for the recognition service.', 'context-alt-text'),
                'type' => 'string',
                'required' => false,
            ],
            'apiKey' => [
                'description' => __('API key used to authenticate with the recognition service.', 'context-alt-text'),
                'type' => 'string',
                'required' => false,
            ],
            'timeoutMs' => [
                'description' => __('Timeout for recognition requests in milliseconds.', 'context-alt-text'),
                'type' => 'integer',
                'required' => false,
            ],
            'modelProfile' => [
                'description' => __('Optional model/profile identifier to request.', 'context-alt-text'),
                'type' => 'string',
                'required' => false,
            ],
            'enabled' => [
                'description' => __('Enable or disable the recognition integration.', 'context-alt-text'),
                'type' => 'boolean',
                'required' => false,
            ],
        ];
    }

    /**
     * @return array<string,mixed>|WP_Error
     */
    private function prepare_recognition_settings_payload(WP_REST_Request $request)
    {
        $params = $request->get_params();

        $payload = [];

        if (array_key_exists('baseUrl', $params)) {
            $rawBaseUrl = $params['baseUrl'];

            if ($rawBaseUrl === null) {
                $baseUrl = '';
            } elseif (is_string($rawBaseUrl)) {
                $baseUrl = trim($rawBaseUrl);
            } else {
                $baseUrl = trim((string) $rawBaseUrl);
            }

            if ($baseUrl !== '' && filter_var($baseUrl, FILTER_VALIDATE_URL) === false) {
                return new WP_Error(
                    'cat_settings_invalid_base_url',
                    __('The recognition service base URL must be a valid URL.', 'context-alt-text'),
                    ['status' => 400]
                );
            }

            $payload['baseUrl'] = $baseUrl;
        }

        if (array_key_exists('timeoutMs', $params)) {
            $rawTimeout = $params['timeoutMs'];

            if (is_string($rawTimeout)) {
                $rawTimeout = trim($rawTimeout);
            }

            $timeout = (int) $rawTimeout;

            if ($timeout !== 0 && ($timeout < 1000 || $timeout > 120000)) {
                return new WP_Error(
                    'cat_settings_invalid_timeout',
                    __('Timeout must be between 1,000 ms and 120,000 ms.', 'context-alt-text'),
                    ['status' => 400]
                );
            }

            $payload['timeoutMs'] = $timeout;
        }

        if (array_key_exists('modelProfile', $params)) {
            $rawModelProfile = $params['modelProfile'];
            $payload['modelProfile'] = is_string($rawModelProfile)
                ? trim($rawModelProfile)
                : trim((string) $rawModelProfile);
        }

        if (array_key_exists('apiKey', $params)) {
            $rawApiKey = $params['apiKey'];

            if ($rawApiKey === null) {
                $payload['apiKey'] = '';
            } elseif (is_string($rawApiKey)) {
                $payload['apiKey'] = trim($rawApiKey);
            } else {
                $payload['apiKey'] = trim((string) $rawApiKey);
            }
        }

        if (array_key_exists('enabled', $params)) {
            $rawEnabled = $params['enabled'];

            if (is_bool($rawEnabled)) {
                $payload['enabled'] = $rawEnabled;
            } else {
                $coerced = filter_var($rawEnabled, FILTER_VALIDATE_BOOLEAN, FILTER_NULL_ON_FAILURE);

                if ($coerced === null) {
                    return new WP_Error(
                        'cat_settings_invalid_flag',
                        __('The recognition enabled flag must be a boolean.', 'context-alt-text'),
                        ['status' => 400]
                    );
                }

                $payload['enabled'] = (bool) $coerced;
            }
        }

        return $payload;
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

    private function get_recognition_observations_args(): array
    {
        return [
            'attachment_ids' => [
                'description' => 'Optional list of attachment IDs to fetch observations for.',
                'type' => 'array',
                'required' => false,
                'items' => [
                    'type' => 'integer',
                ],
            ],
            'per_page' => [
                'description' => 'Number of observation records to return.',
                'type' => 'integer',
                'default' => 20,
            ],
            'status' => [
                'description' => 'Filter observations by status (matched|needs_review).',
                'type' => 'string',
                'required' => false,
            ],
        ];
    }

    /**
     * @param mixed $value
     * @return array<int>
     */
    private function extractAttachmentIds($value): array
    {
        if ($value === null) {
            return [];
        }

        if (is_string($value) && $value !== '') {
            $value = array_map('trim', explode(',', $value));
        }

        if (!is_array($value)) {
            return [];
        }

        $ids = [];

        foreach ($value as $candidate) {
            if (!is_scalar($candidate)) {
                continue;
            }

            $ids[] = (int) $candidate;
        }

        $ids = array_values(array_filter($ids, static fn(int $id): bool => $id > 0));

        return array_values(array_unique($ids));
    }
}
