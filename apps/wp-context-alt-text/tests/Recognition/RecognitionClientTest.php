<?php

declare(strict_types=1);

use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionClientException;
use ContextAltText\Recognition\RecognitionSettings;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class RecognitionClientTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();

        $GLOBALS['__cat_http_queue'] = [];
        $GLOBALS['__cat_http_calls'] = [];
        $GLOBALS['__cat_options']['context_alt_text_recognition_settings'] = [
            'base_url' => 'https://recognition.example',
            'timeout_ms' => 15000,
            'model_profile' => '',
        ];
    }

    public function test_analyze_scene_retries_and_succeeds_after_server_error(): void
    {
        $GLOBALS['__cat_http_queue'] = [
            [
                'response' => [
                    'code' => 502,
                    'message' => 'Bad Gateway',
                ],
                'body' => json_encode(['message' => 'temporary outage']),
            ],
            [
                'response' => [
                    'code' => 200,
                    'message' => 'OK',
                ],
                'body' => json_encode(['outputs' => [['text' => 'done']]]),
            ],
        ];

        $client = new RecognitionClient(new RecognitionSettings());
        $result = $client->analyzeScene(['images' => []]);

        $this->assertSame('done', $result['outputs'][0]['text']);
        $this->assertCount(2, $GLOBALS['__cat_http_calls']);
    }

    public function test_analyze_scene_retries_when_wp_error_occurs(): void
    {
        $GLOBALS['__cat_http_queue'] = [
            new WP_Error('http_request_failed', 'timeout'),
            [
                'response' => [
                    'code' => 200,
                    'message' => 'OK',
                ],
                'body' => json_encode(['outputs' => []]),
            ],
        ];

        $client = new RecognitionClient(new RecognitionSettings());
        $result = $client->analyzeScene(['images' => []]);

        $this->assertSame([], $result['outputs']);
        $this->assertCount(2, $GLOBALS['__cat_http_calls']);
    }

    public function test_analyze_scene_throws_structured_exception_message(): void
    {
        $GLOBALS['__cat_http_queue'] = [
            [
                'response' => [
                    'code' => 422,
                    'message' => 'Unprocessable Entity',
                ],
                'body' => json_encode([
                    'error' => 'validation_failed',
                    'errors' => ['image url missing'],
                ]),
            ],
        ];

        $client = new RecognitionClient(new RecognitionSettings());

        try {
            $client->analyzeScene(['images' => []]);
            $this->fail('Expected exception was not thrown');
        } catch (RecognitionClientException $exception) {
            $this->assertSame(422, $exception->getCode());
            $this->assertStringContainsString('validation_failed', $exception->getMessage());
            $this->assertStringContainsString('image url missing', $exception->getMessage());
        }
    }

    public function test_get_health_returns_decoded_payload(): void
    {
        $GLOBALS['__cat_http_queue'] = [
            [
                'response' => [
                    'code' => 200,
                    'message' => 'OK',
                ],
                'body' => json_encode([
                    'status' => 'healthy',
                    'uptime' => 123,
                ]),
            ],
        ];

        $client = new RecognitionClient(new RecognitionSettings());
        $result = $client->getHealth();

        $this->assertSame('healthy', $result['status']);
        $this->assertSame('GET', $GLOBALS['__cat_http_calls'][0]['method']);
    }

    public function test_get_health_throws_exception_on_error_response(): void
    {
        $GLOBALS['__cat_http_queue'] = [
            [
                'response' => [
                    'code' => 503,
                    'message' => 'Service Unavailable',
                ],
                'body' => json_encode([
                    'message' => 'maintenance',
                ]),
            ],
        ];

        $client = new RecognitionClient(new RecognitionSettings());

        $this->expectException(RecognitionClientException::class);
        $client->getHealth();
    }
}
