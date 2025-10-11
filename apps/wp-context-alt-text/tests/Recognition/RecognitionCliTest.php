<?php

declare(strict_types=1);

use ContextAltText\Recognition\RecognitionCli;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionClientException;
use ContextAltText\Recognition\RecognitionJobRepository;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Recognition\RecognitionObservationRepository;
use ContextAltText\Recognition\RecognitionSettings;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class RecognitionCliTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();

        WP_CLI::reset_cli_messages();
        $GLOBALS['__cat_current_user_capabilities'] = [];
        $GLOBALS['__cat_posts'] = [];
        $GLOBALS['__cat_attachment_mimes'] = [];
        $GLOBALS['__cat_attachment_urls'] = [];
        $GLOBALS['__cat_post_meta'] = [];
        $GLOBALS['__cat_transients'] = [];
        $GLOBALS['__cat_uuid_counter'] = 0;
    }

    public function test_health_logs_success_message(): void
    {
        $client = new class extends RecognitionClient {
            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function getHealth(): array
            {
                return [
                    'status' => 'ok',
                    'uptime' => 42,
                ];
            }

            public function analyzeScene(array $payload): array
            {
                return [];
            }
        };

        $service = new RecognitionJobService(
            $client,
            new RecognitionJobRepository(),
            new RecognitionObservationRepository()
        );

        $cli = new RecognitionCli($client, $service);
        $cli->health([], []);

        self::assertNotEmpty(WP_CLI::$messages['success']);
        self::assertStringContainsString('status: ok', WP_CLI::$messages['success'][0]);
        self::assertStringContainsString('"uptime":42', WP_CLI::$messages['log'][0]);
    }

    public function test_health_errors_when_client_fails(): void
    {
        $client = new class extends RecognitionClient {
            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function getHealth(): array
            {
                throw new RecognitionClientException('timed out');
            }

            public function analyzeScene(array $payload): array
            {
                return [];
            }
        };

        $service = new RecognitionJobService(
            $client,
            new RecognitionJobRepository(),
            new RecognitionObservationRepository()
        );

        $cli = new RecognitionCli($client, $service);

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('timed out');
        $cli->health([], []);
    }

    public function test_analyze_submits_job_and_logs_summary(): void
    {
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
                            'detected_entities' => [],
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

        $cli = new RecognitionCli($client, $service);

        $this->primeAttachment(123, 'image/png', 'http://example.test/uploads/123.png');
        $GLOBALS['__cat_current_user_capabilities']['edit_post'] = true;

        $cli->analyze(['123'], []);

        self::assertNotEmpty(WP_CLI::$messages['success']);
        self::assertStringContainsString('Recognition job', WP_CLI::$messages['success'][0]);
        self::assertStringContainsString('Accepted: 1', WP_CLI::$messages['log'][0]);
        self::assertStringContainsString('Rejected: 0', WP_CLI::$messages['log'][1]);
        self::assertStringContainsString('Current job status', WP_CLI::$messages['log'][2]);
    }

    public function test_analyze_errors_when_no_valid_attachment(): void
    {
        $client = new class extends RecognitionClient {
            public function __construct()
            {
                parent::__construct(new RecognitionSettings());
            }

            public function analyzeScene(array $payload): array
            {
                return [];
            }
        };

        $service = new RecognitionJobService(
            $client,
            new RecognitionJobRepository(),
            new RecognitionObservationRepository()
        );

        $cli = new RecognitionCli($client, $service);

        $this->expectException(RuntimeException::class);
        $this->expectExceptionMessage('No valid attachments were provided for recognition.');
        $cli->analyze(['999'], []);
    }

    private function primeAttachment(int $id, string $mime, string $url): void
    {
        $GLOBALS['__cat_posts'][$id] = (object) [
            'ID' => $id,
            'post_type' => 'attachment',
        ];

        $GLOBALS['__cat_attachment_mimes'][$id] = $mime;
        $GLOBALS['__cat_attachment_urls'][$id] = $url;
    }
}
