<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Api;

use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Api\Api;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionJobRepository;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Recognition\RecognitionObservationRepository;
use ContextAltText\Recognition\RecognitionSettings;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Workbench\WorkbenchMediaResolver;
use PHPUnit\Framework\TestCase;
use \WP_Error;
use \WP_REST_Request;

final class ApiTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__cat_rest_routes'] = [];
        $GLOBALS['__cat_current_user_capabilities'] = [];
        $GLOBALS['__cat_posts'] = [];
        $GLOBALS['__cat_attachment_mimes'] = [];
        $GLOBALS['__cat_attachment_urls'] = [];
        $GLOBALS['__cat_post_meta'] = [];
        $GLOBALS['__cat_transients'] = [];
        $GLOBALS['__cat_uuid_counter'] = 0;
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

    public function test_registers_recognition_routes_when_feature_enabled(): void
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
        $flags = $this->createRecognitionEnabledFlags();

        $api = $this->createApi($metrics, $flags);
        $api->register_routes();

        $analyzeRoute = $this->find_route('/recognition/analyze');
        self::assertNotNull($analyzeRoute);
        self::assertSame('POST', $analyzeRoute['args']['methods']);

        $permission = $analyzeRoute['args']['permission_callback'];
        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;
        self::assertTrue($permission());

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = false;
        self::assertFalse($permission());

        $jobRoute = $this->find_route('/recognition/job/(?P<id>[a-zA-Z0-9\\-]+)');
        self::assertNotNull($jobRoute);
        self::assertSame('GET', $jobRoute['args']['methods']);
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

    private function createRecognitionEnabledFlags(): FeatureFlags
    {
        return new class extends FeatureFlags {
            public function workbenchRecognitionEnabled(): bool
            {
                return true;
            }
        };
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

        $jobs = new RecognitionJobService(
            $client,
            new RecognitionJobRepository(),
            new RecognitionObservationRepository()
        );

        return new Api($metrics, $flags, new WorkbenchMediaResolver(), $jobs);
    }

    private function primeAttachment(int $id, string $mime = 'image/jpeg', string $url = ''): void
    {
        $GLOBALS['__cat_posts'][$id] = (object) [
            'ID' => $id,
            'post_type' => 'attachment',
        ];

        $GLOBALS['__cat_attachment_mimes'][$id] = $mime;
        $GLOBALS['__cat_attachment_urls'][$id] = $url !== '' ? $url : sprintf('http://example.test/uploads/%d.jpg', $id);
    }

    public function test_post_recognition_analyze_returns_error_for_invalid_payload(): void
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

        $response = $api->post_recognition_analyze(new WP_REST_Request());

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('attachment_ids must be an array of attachment IDs.', $response->get_error_message());
    }

    public function test_post_recognition_analyze_returns_error_when_no_valid_attachments(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);

        $client = new class extends RecognitionClient {
            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function analyzeScene(array $payload): array
            {
                return ['results' => []];
            }
        };

        $service = new RecognitionJobService(
            $client,
            new RecognitionJobRepository(),
            new RecognitionObservationRepository()
        );

        $api = new Api($metrics, new FeatureFlags(), new WorkbenchMediaResolver(), $service);

        $request = new WP_REST_Request([
            'attachment_ids' => [777],
        ]);

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;
        $GLOBALS['__cat_current_user_capabilities']['edit_post'] = false;

        $response = $api->post_recognition_analyze($request);

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('No valid attachments were provided for recognition.', $response->get_error_message());
        $this->assertSame([777], $response->get_error_data()['rejected'] ?? []);
    }

    public function test_get_recognition_job_returns_not_found_error(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);

        $service = new RecognitionJobService(
            new class extends RecognitionClient {
                public function __construct()
                {
                    parent::__construct(new RecognitionSettings());
                }

                public function analyzeScene(array $payload): array
                {
                    return ['results' => []];
                }
            },
            new RecognitionJobRepository(),
            new RecognitionObservationRepository()
        );

        $api = new Api($metrics, new FeatureFlags(), new WorkbenchMediaResolver(), $service);

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;

        $response = $api->get_recognition_job(new WP_REST_Request(['id' => 'missing-job']));

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('cat_recognition_job_not_found', $response->get_error_code());
        $this->assertSame(404, $response->get_error_data()['status'] ?? null);
    }

    public function test_recognition_endpoints_queue_and_hydrate_job(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);

        $client = new class extends RecognitionClient {
            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function analyzeScene(array $payload): array
            {
                return [
                    'results' => [
                        [
                            'detected_entities' => [
                                [
                                    'label' => 'Face',
                                    'entity_type' => 'person',
                                    'confidence' => 0.9,
                                    'area' => 120,
                                    'bbox' => [0, 0, 10, 10],
                                    'roster_match' => [
                                        'is_match' => true,
                                        'similarity_score' => 0.95,
                                        'match_confidence' => 95,
                                        'confidence_threshold' => 0.5,
                                        'roster_entry' => [
                                            'unique_id' => 'roster-1',
                                            'name' => 'Test User',
                                            'display_name' => 'Test User',
                                        ],
                                    ],
                                    'face_data' => [
                                        'candidates' => [],
                                    ],
                                ],
                            ],
                        ],
                    ],
                ];
            }
        };

        $service = new RecognitionJobService(
            $client,
            new RecognitionJobRepository(),
            new RecognitionObservationRepository()
        );

        $api = new Api($metrics, new FeatureFlags(), new WorkbenchMediaResolver(), $service);

        $this->primeAttachment(101, 'image/jpeg', 'http://example.test/photo.jpg');

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;
        $GLOBALS['__cat_current_user_capabilities']['edit_post'] = true;

        $request = new WP_REST_Request([
            'attachment_ids' => [101],
        ]);

        $response = $api->post_recognition_analyze($request);

        $this->assertIsArray($response);
        $this->assertSame('complete', $response['status']);
        $this->assertSame([ ], $response['rejected']);
        $this->assertSame(1, $response['accepted']);
        $this->assertNotEmpty($response['jobId']);

        $jobResponse = $api->get_recognition_job(new WP_REST_Request(['id' => $response['jobId']]));

        $this->assertIsArray($jobResponse);
        $this->assertSame('complete', $jobResponse['status']);
        $this->assertArrayHasKey('observations', $jobResponse);
        $this->assertCount(1, $jobResponse['observations']);
        $this->assertSame(101, $jobResponse['observations'][0]['attachmentId']);
        $this->assertSame(1, $jobResponse['observations'][0]['summary']['matched']);
    }
}
