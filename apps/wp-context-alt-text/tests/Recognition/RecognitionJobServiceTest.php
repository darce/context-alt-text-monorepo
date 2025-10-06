<?php

declare(strict_types=1);

use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionClientException;
use ContextAltText\Recognition\RecognitionJobRepository;
use ContextAltText\Recognition\RecognitionJobService;
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
        $service = new RecognitionJobService($client, $repository);

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
                    'outputs' => [
                        ['text' => 'description'],
                    ],
                ];
            }
        };

        $repository = new RecognitionJobRepository();
        $service = new RecognitionJobService($client, $repository);

        $GLOBALS['__cat_current_user_capabilities']['edit_post'] = true;

        $this->primeValidAttachment(10, 'image/png', 'http://example.test/photo.png');

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
        $this->assertSame('description', $job['result']['outputs'][0]['text']);
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
        $service = new RecognitionJobService($client, $repository);

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
        $service = new RecognitionJobService($client, $repository);

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
