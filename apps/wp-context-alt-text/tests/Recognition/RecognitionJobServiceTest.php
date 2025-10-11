<?php

declare(strict_types=1);

use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionClientException;
use ContextAltText\Recognition\RecognitionJobRepository;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Recognition\RecognitionObservationRepository;
use ContextAltText\Recognition\RecognitionSettings;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class RecognitionJobServiceTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();

        $GLOBALS['__cat_current_user_capabilities'] = [];
        $GLOBALS['__cat_posts'] = [];
        $GLOBALS['__cat_attachment_mimes'] = [];
        $GLOBALS['__cat_attachment_urls'] = [];
        $GLOBALS['__cat_transients'] = [];
        $GLOBALS['__cat_uuid_counter'] = 0;
        $GLOBALS['__cat_actions'] = [];
        $GLOBALS['__cat_filters'] = [];
        $GLOBALS['__cat_post_meta'] = [];

        add_filter('cat_recognition_should_log_error', static function (bool $shouldLog): bool {
            return false;
        }, 10, 3);
    }

    private function primeValidAttachment(int $id, string $mime = 'image/jpeg', string $url = ''): void
    {
        $post = (object) [
            'ID' => $id,
            'post_type' => 'attachment',
        ];

        $GLOBALS['__cat_posts'][$id] = $post;
        $GLOBALS['__cat_attachment_mimes'][$id] = $mime;
        $GLOBALS['__cat_attachment_urls'][$id] = $url !== '' ? $url : sprintf('http://example.test/uploads/%d.jpg', $id);
    }

    public function test_submit_rejects_when_no_valid_attachments(): void
    {
        $client = new class extends RecognitionClient {
            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function analyzeScene(array $payload): array
            {
                return ['unused' => true];
            }
        };

        $repository = new RecognitionJobRepository();
        $observations = new RecognitionObservationRepository();
        $service = new RecognitionJobService($client, $repository, $observations);

        $GLOBALS['__cat_current_user_capabilities']['edit_post'] = false;

        $result = $service->submit([42]);

        $this->assertNull($result['job']);
        $this->assertSame('rejected', $result['status']);
        $this->assertSame(0, $result['accepted']);
        $this->assertSame([42], $result['rejected']);
    }

    public function test_submit_creates_job_and_calls_client(): void
    {
        $client = new class extends RecognitionClient {
            /** @var array<int,array<string,mixed>> */
            public array $calls = [];

            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function analyzeScene(array $payload): array
            {
                $this->calls[] = $payload;

                return [
                    'results' => [
                        [
                            'detected_entities' => [
                                [
                                    'label' => 'Face',
                                    'entity_type' => 'person',
                                    'confidence' => 0.95,
                                    'area' => 120.5,
                                    'bbox' => [0, 0, 10, 10],
                                    'roster_match' => [
                                        'is_match' => true,
                                        'similarity_score' => 0.92,
                                        'match_confidence' => 92.0,
                                        'confidence_threshold' => 0.5,
                                        'roster_entry' => [
                                            'unique_id' => 'roster-123',
                                            'name' => 'Test User',
                                            'display_name' => 'Test User',
                                        ],
                                    ],
                                    'face_data' => [
                                        'candidates' => [
                                            [
                                                'name' => 'Test User',
                                                'similarity' => 0.92,
                                                'unique_id' => 'roster-123',
                                                'meets_threshold' => true,
                                            ],
                                        ],
                                    ],
                                ],
                                [
                                    'label' => 'Face',
                                    'entity_type' => 'person',
                                    'confidence' => 0.45,
                                    'area' => 80.0,
                                    'bbox' => [1, 2, 3, 4],
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

        $repository = new RecognitionJobRepository();
        $observations = new RecognitionObservationRepository();
        $service = new RecognitionJobService($client, $repository, $observations);

        $GLOBALS['__cat_current_user_capabilities']['edit_post'] = true;

        $this->primeValidAttachment(10, 'image/png', 'http://example.test/photo.png');

        $capturedObservations = [];
        add_action(
            'cat_recognition_observations_stored',
            static function ($jobId, $attachmentId, array $payload) use (&$capturedObservations): void {
                $capturedObservations[] = [$jobId, $attachmentId, $payload];
            },
            10,
            3
        );

        $result = $service->submit([10]);

        $this->assertSame('complete', $result['status']);
        $this->assertSame(1, $result['accepted']);
        $this->assertSame([], $result['rejected']);
        $this->assertSame('uuid-1', $result['jobId']);

        $this->assertCount(1, $client->calls);
        $payload = $client->calls[0];

        $this->assertSame([
            [
                'filename' => 'photo.png',
                'image_url' => 'http://example.test/photo.png',
            ],
        ], $payload['images']);
        $this->assertTrue($payload['use_roster']);

        $job = $repository->find('uuid-1');
        $this->assertNotNull($job);
        $this->assertSame('complete', $job['status']);
        $this->assertIsInt($job['startedAt']);
        $this->assertIsInt($job['completedAt']);
        $this->assertArrayHasKey('result', $job);
        $this->assertCount(1, $job['result']['results']);
        $this->assertCount(2, $job['result']['results'][0]['detected_entities']);

        $stored = get_post_meta(10, '_context_alt_text_recognition_observations', true);
        $this->assertIsArray($stored);
        $this->assertSame('uuid-1', $stored['jobId']);
        $this->assertSame(10, $stored['attachmentId']);
        $this->assertSame('photo.png', $stored['context']['filename']);
        $this->assertSame('http://example.test/photo.png', $stored['context']['imageUrl']);
        $this->assertCount(2, $stored['observations']);
        $this->assertSame(2, $stored['summary']['total']);
        $this->assertSame(1, $stored['summary']['matched']);
        $this->assertSame(1, $stored['summary']['needs_review']);

        $matched = $stored['observations'][0];
        $this->assertSame('matched', $matched['status']);
        $this->assertSame('roster-123', $matched['roster']['remoteId']);
        $this->assertSame('Test User', $matched['roster']['name']);
        $this->assertTrue($matched['match']['isMatch']);

        $needsReview = $stored['observations'][1];
        $this->assertSame('needs_review', $needsReview['status']);
        $this->assertSame([], $needsReview['candidates']);

        $this->assertCount(1, $capturedObservations);
        $this->assertSame('uuid-1', $capturedObservations[0][0]);
        $this->assertSame(10, $capturedObservations[0][1]);
        $this->assertSame(2, $capturedObservations[0][2]['summary']['total']);

        $jobWithObservations = $service->getJob('uuid-1');
        $this->assertNotNull($jobWithObservations);
        $this->assertArrayHasKey('observations', $jobWithObservations);
        $this->assertCount(1, $jobWithObservations['observations']);
        $this->assertSame(10, $jobWithObservations['observations'][0]['attachmentId']);
    }

    public function test_submit_marks_job_as_error_when_client_fails(): void
    {
        $client = new class extends RecognitionClient {
            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function analyzeScene(array $payload): array
            {
                throw new RecognitionClientException('backend offline');
            }
        };

        $repository = new RecognitionJobRepository();
        $observations = new RecognitionObservationRepository();
        $service = new RecognitionJobService($client, $repository, $observations);

        $GLOBALS['__cat_current_user_capabilities']['edit_post'] = true;
        $this->primeValidAttachment(25);

        $result = $service->submit([25]);

        $this->assertSame('error', $result['status']);
        $this->assertSame(1, $result['accepted']);
        $this->assertSame([], $result['rejected']);

        $job = $repository->find('uuid-1');
        $this->assertNotNull($job);
        $this->assertSame('error', $job['status']);
        $this->assertIsInt($job['startedAt']);
        $this->assertSame('backend offline', $job['error']);
    }

    public function test_submit_dispatches_failure_action_with_job_context(): void
    {
        $client = new class extends RecognitionClient {
            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function analyzeScene(array $payload): array
            {
                throw new RecognitionClientException('service unavailable');
            }
        };

        $repository = new RecognitionJobRepository();
        $observations = new RecognitionObservationRepository();
        $service = new RecognitionJobService($client, $repository, $observations);

        $GLOBALS['__cat_current_user_capabilities']['edit_post'] = true;
        $this->primeValidAttachment(77);

        $captured = [];
        add_action('cat_recognition_job_failed', static function (array $context) use (&$captured): void {
            $captured[] = $context;
        });

        $service->submit([77]);

        $this->assertNotEmpty($captured);
        $this->assertSame('uuid-1', $captured[0]['jobId']);
        $this->assertSame('error', $captured[0]['status']);
        $this->assertSame([77], $captured[0]['attachments']);
    }
}
