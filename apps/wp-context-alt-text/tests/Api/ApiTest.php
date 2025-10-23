<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Api;

require_once __DIR__ . '/../Roster/Support/FakeRosterClient.php';
require_once __DIR__ . '/../Roster/Support/RosterTestFactory.php';

use ContextAltText\Admin\DashboardMetricsService;
use ContextAltText\Api\Api;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionJobRepository;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Recognition\RecognitionObservationRepository;
use ContextAltText\Recognition\RecognitionSettings;
use ContextAltText\Shared\Config\SettingsRepository;
use ContextAltText\Roster\RosterSyncScheduler;
use ContextAltText\Roster\RosterObservationManager;
use ContextAltText\Security\Security;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Support\FeatureFlags;
use ContextAltText\Tests\Roster\Support\FakeRosterClient;
use ContextAltText\Tests\Roster\Support\RosterTestFactory;
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
        $GLOBALS['__cat_options'] = [];
        $GLOBALS['__cat_scheduled'] = [];
        $GLOBALS['__cat_actions'] = [];
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

    public function test_recognition_observations_route_returns_summary(): void
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
        $observations = new RecognitionObservationRepository();

        $observations->store(101, [
            'jobId' => 'job-a',
            'attachmentId' => 101,
            'observations' => [
                [
                    'status' => 'matched',
                    'confidence' => 0.8,
                    'match' => ['confidence' => 0.8],
                    'roster' => ['remoteId' => 'remote-a'],
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 1,
                'needs_review' => 0,
            ],
            'confidenceScore' => 0.8,
            'sourceRemoteId' => 'remote-a',
        ]);

        $observations->store(202, [
            'jobId' => 'job-b',
            'attachmentId' => 202,
            'observations' => [
                ['status' => 'needs_review', 'confidence' => 0.5],
                ['status' => 'needs_review', 'confidence' => 0.4],
            ],
            'summary' => [
                'total' => 2,
                'matched' => 0,
                'needs_review' => 2,
            ],
            'confidenceScore' => 0.6,
        ]);

        $api = $this->createApi($metrics, $flags, null, null, null, null, $observations);
        $api->register_routes();

        $route = $this->find_route('/observations', 'GET');
        self::assertNotNull($route);

        $response = $api->get_recognition_observations(new WP_REST_Request());

        self::assertIsArray($response);
        self::assertSame(2, $response['total']);
        self::assertSame(1, $response['page']);
        self::assertSame(20, $response['per_page']);
        self::assertSame(1, $response['total_pages']);
        self::assertSame(2, $response['summary']['attachments']);
        self::assertSame(3, $response['summary']['observations']['total']);
        self::assertSame(1, $response['summary']['observations']['matched']);
        self::assertSame(2, $response['summary']['observations']['needs_review']);

        $ids = array_map(static fn($item) => $item['attachmentId'], $response['items']);
        self::assertContains(101, $ids);
        self::assertContains(202, $ids);
    }

    public function test_recognition_observations_route_supports_pagination(): void
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
        $observations = new RecognitionObservationRepository();

        $observations->store(100, [
            'jobId' => 'job-100',
            'attachmentId' => 100,
            'updatedAt' => 100,
            'observations' => [],
            'summary' => [
                'total' => 0,
                'matched' => 0,
                'needs_review' => 0,
            ],
        ]);

        $observations->store(200, [
            'jobId' => 'job-200',
            'attachmentId' => 200,
            'updatedAt' => 200,
            'observations' => [
                ['status' => 'needs_review', 'confidence' => 0.5],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $observations->store(300, [
            'jobId' => 'job-300',
            'attachmentId' => 300,
            'updatedAt' => 300,
            'observations' => [
                [
                    'status' => 'matched',
                    'confidence' => 0.9,
                    'roster' => ['remoteId' => 'remote-123'],
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 1,
                'needs_review' => 0,
            ],
        ]);

        $api = $this->createApi($metrics, $flags, null, null, null, null, $observations);
        $api->register_routes();

        $request = new WP_REST_Request();
        $request->set_param('per_page', 1);
        $request->set_param('page', 2);

        $response = $api->get_recognition_observations($request);

        self::assertIsArray($response);
        self::assertSame(3, $response['total']);
        self::assertSame(2, $response['page']);
        self::assertSame(1, $response['per_page']);
        self::assertSame(3, $response['total_pages']);
        self::assertSame(1, $response['summary']['attachments']);
        self::assertCount(1, $response['items']);
        self::assertSame(200, $response['items'][0]['attachmentId']);
        self::assertSame('needs_review', $response['items'][0]['status']);
    }

    public function test_registers_recognition_observation_update_route_when_feature_enabled(): void
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

        $route = $this->find_route('/observations/(?P<attachment_id>\d+)/(?P<observation_id>[A-Za-z0-9\-_]+)');
        self::assertNotNull($route);

        $methods = $route['args']['methods'] ?? [];
        self::assertIsArray($methods);
        self::assertContains('PATCH', $methods);
    }

    public function test_patch_recognition_observation_updates_record(): void
    {
        $observations = new RecognitionObservationRepository();

        $observations->store(101, [
            'jobId' => 'job-1',
            'attachmentId' => 101,
            'observations' => [
                [
                    'observationId' => 'obs-1',
                    'status' => 'needs_review',
                    'label' => 'Unknown',
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

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

        $api = $this->createApi($metrics, $flags, null, null, null, null, $observations);

        $request = new WP_REST_Request([
            'attachment_id' => 101,
            'observation_id' => 'obs-1',
            'status' => 'matched',
            'roster' => ['remoteId' => 'remote-55'],
        ]);

        $response = $api->patch_recognition_observation($request);

        self::assertIsArray($response);
        self::assertArrayHasKey('record', $response);

        $record = $response['record'];
        self::assertSame(101, $record['attachmentId'] ?? null);
        self::assertSame(1, $record['summary']['matched'] ?? null);
        self::assertSame(0, $record['summary']['needs_review'] ?? null);

        $updated = $record['observations'][0] ?? [];
        self::assertSame('matched', $updated['status'] ?? null);
        self::assertSame('remote-55', $updated['roster']['remoteId'] ?? null);
    }
    private function find_route(string $path, ?string $method = null): ?array
    {
        foreach ($GLOBALS['__cat_rest_routes'] as $route) {
            if ($route['route'] !== $path) {
                continue;
            }

            if ($method !== null) {
                $registered = $route['args']['methods'] ?? null;

                if (is_array($registered)) {
                    if (!in_array($method, $registered, true)) {
                        continue;
                    }
                } elseif (!is_string($registered) || stripos($registered, $method) === false) {
                    continue;
                }
            }

            return $route;
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

    private function createRosterEnabledFlags(): FeatureFlags
    {
        return new class extends FeatureFlags {
            public function abilitiesEnabled(): bool
            {
                return true;
            }

            public function rosterUiEnabled(): bool
            {
                return true;
            }
        };
    }

    private function createApi(
        DashboardMetricsService $metrics,
        FeatureFlags $flags,
        ?RecognitionJobService $jobs = null,
        ?RosterService $rosterService = null,
        ?RosterSyncScheduler $rosterScheduler = null,
        ?Security $security = null,
        ?RecognitionObservationRepository $observations = null,
        ?SettingsRepository $settingsRepository = null,
        ?RecognitionClient $recognitionClient = null
    ): Api {
        $observations = $observations ?? new RecognitionObservationRepository();
        $settingsRepository = $settingsRepository ?? new SettingsRepository();

        if ($jobs === null) {
            $recognitionClient = $recognitionClient ?? new class($settingsRepository) extends RecognitionClient {
                public function __construct(SettingsRepository $settingsRepository)
                {
                    parent::__construct(new RecognitionSettings($settingsRepository));
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
                $recognitionClient,
                new RecognitionJobRepository(),
                $observations
            );
        } elseif ($recognitionClient === null) {
            $recognitionClient = new RecognitionClient(new RecognitionSettings($settingsRepository));
        }

        $security = $security ?? new Security();

        if ($rosterService === null) {
            $rosterService = new RosterService($security, new FakeRosterClient());
        }

        $rosterScheduler = $rosterScheduler ?? new RosterSyncScheduler($rosterService);
        $rosterObservationManager = new RosterObservationManager($observations, $jobs);
        if (method_exists($jobs, 'setRosterObservationManager')) {
            $jobs->setRosterObservationManager($rosterObservationManager);
        }

        $identifyController = new \ContextAltText\Recognition\IdentifyController(
            $recognitionClient,
            $rosterService,
            $security
        );

        return new Api(
            $metrics,
            $flags,
            new WorkbenchMediaResolver($observations),
            $jobs,
            $observations,
            $rosterService,
            $rosterScheduler,
            $security,
            $settingsRepository,
            $recognitionClient,
            $rosterObservationManager,
            $identifyController
        );
    }

    /**
     * @return array{RosterService,FakeRosterClient}
     */
    private function buildRosterService(?Security $security = null): array
    {
        $security = $security ?? new Security();
        $client = new FakeRosterClient();

        return [new RosterService($security, $client), $client];
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

        $observations = new RecognitionObservationRepository();

        $service = new RecognitionJobService(
            $client,
            new RecognitionJobRepository(),
            $observations
        );

        $api = $this->createApi($metrics, new FeatureFlags(), $service, null, null, null, $observations);

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

    public function test_registers_roster_routes_when_feature_enabled(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        [$rosterService] = $this->buildRosterService();
        $flags = $this->createRosterEnabledFlags();
        $security = new Security();
        $scheduler = new RosterSyncScheduler($rosterService);

        $api = $this->createApi($metrics, $flags, null, $rosterService, $scheduler, $security);
        $api->register_routes();

        self::assertNotNull($this->find_route('/roster', 'GET'));
        $postRoute = $this->find_route('/roster', 'POST');
        self::assertNotNull($postRoute);
        self::assertNotNull($this->find_route('/roster/(?P<id>[a-zA-Z0-9\-_]+)', 'PATCH'));
        self::assertNotNull($this->find_route('/roster/(?P<id>[a-zA-Z0-9\-_]+)', 'DELETE'));
        self::assertNotNull($this->find_route('/roster/sync', 'POST'));

        $permission = $postRoute['args']['permission_callback'];
        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;
        self::assertTrue($permission());
        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = false;
        self::assertFalse($permission());
    }

    public function test_post_roster_entry_creates_entry_and_returns_stats(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $security = new Security();
        [$rosterService, $client] = $this->buildRosterService($security);
        $flags = $this->createRosterEnabledFlags();
        $scheduler = new RosterSyncScheduler($rosterService);

        $api = $this->createApi($metrics, $flags, null, $rosterService, $scheduler, $security);
        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;

        $request = new WP_REST_Request([
            'label' => 'Jane Doe',
            'type' => 'person',
            'metadata' => ['role' => 'Engineer'],
            'referenceImages' => [
                ['image_url' => 'https://example.test/jane.jpg'],
            ],
        ]);

        $response = $api->post_roster_entry($request);

        self::assertIsArray($response);
        self::assertIsArray($response['entry'] ?? null);
        self::assertSame('Jane Doe', $response['entry']['label'] ?? null);
        // referenceImageCount should be 0 since no attachments are tagged yet
        self::assertSame(0, $response['entry']['referenceImageCount'] ?? -1);
        self::assertIsArray($response['stats'] ?? null);
        self::assertIsArray($response['autoMatched'] ?? null);
        self::assertCount(0, $response['autoMatched']);
        self::assertCount(1, $client->created);
    }

    public function test_post_roster_entry_can_resolve_observation(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $security = new Security();
        [$rosterService, $client] = $this->buildRosterService($security);
        $flags = $this->createRosterEnabledFlags();
        $scheduler = new RosterSyncScheduler($rosterService);
        $observations = new RecognitionObservationRepository();

        $observations->store(55, [
            'jobId' => 'job-obs',
            'attachmentId' => 55,
            'observations' => [
                [
                    'observationId' => 'obs-55',
                    'status' => 'needs_review',
                    'label' => 'Unresolved Face',
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $api = $this->createApi($metrics, $flags, null, $rosterService, $scheduler, $security, $observations);
        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;

        $request = new WP_REST_Request([
            'label' => 'Resolved Person',
            'type' => 'person',
            'resolveObservation' => [
                'attachmentId' => 55,
                'observationId' => 'obs-55',
            ],
        ]);

        $response = $api->post_roster_entry($request);

        self::assertIsArray($response);
        self::assertIsArray($response['entry'] ?? null);
        self::assertCount(1, $client->created);

        $observation = $response['observation'] ?? null;
        self::assertIsArray($observation);
        self::assertSame(0, $observation['summary']['needs_review'] ?? null);
        self::assertSame('matched', $observation['observations'][0]['status'] ?? null);
        self::assertSame('remote-1', $observation['observations'][0]['roster']['remoteId'] ?? null);
        self::assertIsArray($response['autoMatched'] ?? null);

        $stored = $observations->get(55);
        self::assertSame('matched', $stored['observations'][0]['status'] ?? null);
    }

    public function test_post_roster_entry_retries_pending_observations(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $security = new Security();
        [$rosterService, $client] = $this->buildRosterService($security);
        $flags = $this->createRosterEnabledFlags();
        $scheduler = new RosterSyncScheduler($rosterService);
        $observations = new RecognitionObservationRepository();

        $observations->store(101, [
            'jobId' => 'job-101',
            'updatedAt' => 100,
            'observations' => [
                [
                    'observationId' => 'obs-101',
                    'status' => 'needs_review',
                    'entityType' => 'person',
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $observations->store(102, [
            'jobId' => 'job-102',
            'updatedAt' => 200,
            'observations' => [
                [
                    'observationId' => 'obs-102',
                    'status' => 'needs_review',
                    'entityType' => 'person',
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $jobs = new class extends RecognitionJobService {
            public array $submittedBatches = [];

            public function __construct()
            {
                // Intentionally bypass parent dependencies; this stub only records submissions.
            }

            public function submit(array $attachmentIds, bool $skipCooldown = false): array
            {
                $this->submittedBatches[] = $attachmentIds;

                return [
                    'job' => null,
                    'jobId' => null,
                    'status' => 'complete',
                    'accepted' => count($attachmentIds),
                    'rejected' => [],
                ];
            }
        };

        $api = $this->createApi($metrics, $flags, $jobs, $rosterService, $scheduler, $security, $observations);

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;

        $request = new WP_REST_Request([
            'label' => 'Ellyn',
            'type' => 'person',
        ]);

        $response = $api->post_roster_entry($request);

        self::assertIsArray($response);
        self::assertCount(1, $client->created);
        self::assertNotEmpty($jobs->submittedBatches);
        self::assertSame([102, 101], $jobs->submittedBatches[0]);
    }

    public function test_post_roster_entry_auto_assigns_candidates(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $security = new Security();
        [$rosterService, $client] = $this->buildRosterService($security);
        $flags = $this->createRosterEnabledFlags();
        $scheduler = new RosterSyncScheduler($rosterService);
        $observations = new RecognitionObservationRepository();

        $observations->store(500, [
            'jobId' => 'job-500',
            'attachmentId' => 500,
            'observations' => [
                [
                    'observationId' => 'obs-500',
                    'status' => 'needs_review',
                    'label' => 'Pending Face',
                    'entityType' => 'person',
                    'match' => [
                        'isMatch' => true,
                        'similarity' => 0.9,
                        'confidence' => 0.9,
                        'threshold' => 0.4,
                        'remoteId' => 'remote-1',
                    ],
                    'roster' => [
                        'remoteId' => 'remote-1',
                    ],
                    'candidates' => [],
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $api = $this->createApi($metrics, $flags, null, $rosterService, $scheduler, $security, $observations);
        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;

        $request = new WP_REST_Request([
            'label' => 'Ellyn',
            'type' => 'person',
            'referenceImages' => [
                ['image_url' => 'https://example.test/ellyn.jpg'],
            ],
        ]);

        $response = $api->post_roster_entry($request);

        self::assertIsArray($response);
        self::assertNotEmpty($response['autoMatched'] ?? []);
        self::assertSame('remote-1', $response['autoMatched'][0]['remoteId'] ?? null);

        $stored = $observations->get(500);
        self::assertSame(0, $stored['summary']['needs_review']);
        self::assertSame('matched', $stored['observations'][0]['status']);
        self::assertSame('remote-1', $stored['observations'][0]['roster']['remoteId'] ?? null);
    }

    public function test_patch_roster_entry_updates_entry(): void
    {
        update_option('cat_roster_entries', [
            'remote-1' => RosterTestFactory::entry([
                'remoteId' => 'remote-1',
                'label' => 'Original',
                'type' => 'person',
            ]),
        ]);

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $security = new Security();
        [$rosterService] = $this->buildRosterService($security);
        $flags = $this->createRosterEnabledFlags();
        $scheduler = new RosterSyncScheduler($rosterService);

        $api = $this->createApi($metrics, $flags, null, $rosterService, $scheduler, $security);

        $request = new WP_REST_Request([
            'label' => 'Updated Label',
            'type' => 'person',
        ]);
        $request['id'] = 'remote-1';

        $response = $api->patch_roster_entry($request);

        self::assertIsArray($response);
        self::assertSame('Updated Label', $response['entry']['label'] ?? null);
        self::assertArrayHasKey('stats', $response);
    }

    public function test_patch_roster_entry_can_resolve_observation(): void
    {
        update_option('cat_roster_entries', [
            'remote-1' => RosterTestFactory::entry([
                'remoteId' => 'remote-1',
                'label' => 'Existing',
                'type' => 'person',
            ]),
        ]);

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $security = new Security();
        [$rosterService] = $this->buildRosterService($security);
        $flags = $this->createRosterEnabledFlags();
        $scheduler = new RosterSyncScheduler($rosterService);
        $observations = new RecognitionObservationRepository();

        $observations->store(77, [
            'jobId' => 'job-resolve',
            'attachmentId' => 77,
            'observations' => [
                [
                    'observationId' => 'obs-1',
                    'status' => 'needs_review',
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $api = $this->createApi($metrics, $flags, null, $rosterService, $scheduler, $security, $observations);
        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;

        $request = new WP_REST_Request([
            'label' => 'Updated Label',
            'type' => 'person',
            'resolveObservation' => [
                'attachmentId' => 77,
                'observationId' => 'obs-1',
                'status' => 'matched',
            ],
        ]);
        $request['id'] = 'remote-1';

        $response = $api->patch_roster_entry($request);

        self::assertIsArray($response);
        self::assertSame('Updated Label', $response['entry']['label'] ?? null);

        $observation = $response['observation'] ?? null;
        self::assertIsArray($observation);
        self::assertSame('matched', $observation['observations'][0]['status'] ?? null);

        $stored = $observations->get(77);
        self::assertSame(0, $stored['summary']['needs_review']);
        self::assertSame('remote-1', $stored['observations'][0]['roster']['remoteId'] ?? null);
    }

    public function test_delete_roster_entry_requires_id(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $security = new Security();
        [$rosterService] = $this->buildRosterService($security);
        $flags = $this->createRosterEnabledFlags();
        $scheduler = new RosterSyncScheduler($rosterService);

        $api = $this->createApi($metrics, $flags, null, $rosterService, $scheduler, $security);

        $response = $api->delete_roster_entry(new WP_REST_Request());

        $this->assertInstanceOf(WP_Error::class, $response);
        $this->assertSame('cat_roster_missing_id', $response->get_error_code());
    }

    public function test_post_roster_sync_returns_snapshot(): void
    {
        update_option('cat_roster_entries', [
            'remote-1' => RosterTestFactory::entry([
                'remoteId' => 'remote-1',
                'label' => 'Snapshot Entry',
            ]),
        ]);

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $security = new Security();
        $client = new FakeRosterClient();
        $rosterService = new class($security, $client) extends RosterService {
            public function __construct(Security $security, FakeRosterClient $client)
            {
                parent::__construct($security, $client);
            }

            public function syncFromRemote(): bool
            {
                \update_option('cat_roster_sync_state', [
                    'lastSyncAt' => '2024-05-01T00:00:00Z',
                    'created' => 1,
                    'updated' => 0,
                    'deleted' => 0,
                    'errors' => 0,
                    'conflicts' => 0,
                ]);

                return true;
            }
        };

        $flags = $this->createRosterEnabledFlags();
        $scheduler = new RosterSyncScheduler($rosterService);

        $api = $this->createApi($metrics, $flags, null, $rosterService, $scheduler, $security);

        $response = $api->post_roster_sync(new WP_REST_Request());

        self::assertIsArray($response);
        self::assertTrue($response['changesApplied'] ?? false);
        self::assertIsArray($response['entries'] ?? null);
        self::assertSame(1, $response['stats']['metrics']['created'] ?? null);
        self::assertSame('2024-05-01T00:00:00Z', $response['syncState']['lastSyncAt'] ?? null);
        self::assertIsArray($response['autoMatched'] ?? null);
    }

    public function test_post_roster_sync_auto_assigns_matches(): void
    {
        update_option('cat_roster_entries', [
            'remote-1' => RosterTestFactory::entry([
                'remoteId' => 'remote-1',
                'label' => 'Snapshot Entry',
                'type' => 'person',
            ]),
        ]);

        $scanner = new class extends MissingAltTextScanner {
            public function get_summary(): array
            {
                return ['total' => 0, 'with_alt' => 0, 'missing' => 0];
            }
        };

        $metrics = new DashboardMetricsService($scanner);
        $security = new Security();
        [$rosterService] = $this->buildRosterService($security);
        $flags = $this->createRosterEnabledFlags();
        $scheduler = new RosterSyncScheduler($rosterService);
        $observations = new RecognitionObservationRepository();

        $observations->store(700, [
            'jobId' => 'job-700',
            'attachmentId' => 700,
            'observations' => [
                [
                    'observationId' => 'obs-700',
                    'status' => 'needs_review',
                    'label' => 'Unmatched',
                    'entityType' => 'person',
                    'candidates' => [
                        [
                            'remoteId' => 'remote-1',
                            'similarity' => 0.9,
                            'confidence' => 0.9,
                            'meetsThreshold' => true,
                        ],
                    ],
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $api = $this->createApi($metrics, $flags, null, $rosterService, $scheduler, $security, $observations);
        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;

        $response = $api->post_roster_sync(new WP_REST_Request());

        self::assertNotEmpty($response['autoMatched'] ?? []);
        $stored = $observations->get(700);
        self::assertSame('matched', $stored['observations'][0]['status']);
        self::assertSame('remote-1', $stored['observations'][0]['roster']['remoteId']);
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

        $observations = new RecognitionObservationRepository();

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
            $observations
        );

        $api = $this->createApi($metrics, new FeatureFlags(), $service, null, null, null, $observations);

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

        $observations = new RecognitionObservationRepository();

        $service = new RecognitionJobService(
            $client,
            new RecognitionJobRepository(),
            $observations
        );

        $api = $this->createApi($metrics, new FeatureFlags(), $service, null, null, null, $observations);

        $this->primeAttachment(101, 'image/jpeg', 'http://example.test/photo.jpg');

        $GLOBALS['__cat_current_user_capabilities']['manage_options'] = true;
        $GLOBALS['__cat_current_user_capabilities']['edit_post'] = true;

        $request = new WP_REST_Request([
            'attachment_ids' => [101],
        ]);

        $response = $api->post_recognition_analyze($request);

        $this->assertIsArray($response);
        $this->assertSame('queued', $response['status']);
        $this->assertSame([], $response['rejected']);
        $this->assertSame(1, $response['accepted']);
        $this->assertSame([], $response['deferred']);
        $this->assertNotEmpty($response['jobId']);

        do_action(RecognitionJobService::PROCESS_HOOK, $response['jobId']);

        $jobResponse = $api->get_recognition_job(new WP_REST_Request(['id' => $response['jobId']]));

        $this->assertIsArray($jobResponse);
        $this->assertSame('complete', $jobResponse['status']);
        $this->assertArrayHasKey('observations', $jobResponse);
        $this->assertCount(1, $jobResponse['observations']);
        $this->assertSame(101, $jobResponse['observations'][0]['attachmentId']);
        $this->assertSame(1, $jobResponse['observations'][0]['summary']['matched']);

        $deferredResponse = $api->post_recognition_analyze($request);
        $this->assertIsArray($deferredResponse);
        $this->assertSame('deferred', $deferredResponse['status']);
        $this->assertSame(0, $deferredResponse['accepted']);
        $this->assertSame([], $deferredResponse['rejected']);
        $this->assertSame([101], $deferredResponse['deferred']);
    }
}
