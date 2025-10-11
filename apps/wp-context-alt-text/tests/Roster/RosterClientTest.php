<?php

declare(strict_types=1);

use ContextAltText\Recognition\RecognitionSettings;
use ContextAltText\Roster\RosterClient;
use ContextAltText\Roster\RosterClientException;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class RosterClientTest extends TestCase
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

    public function test_create_entry_returns_payload(): void
    {
        $GLOBALS['__cat_http_queue'] = [
            [
                'response' => [
                    'code' => 201,
                    'message' => 'Created',
                ],
                'body' => json_encode([
                    'id' => 'remote-abc',
                    'label' => 'Sample Person',
                ]),
            ],
        ];

        $client = new RosterClient(new RecognitionSettings());
        $result = $client->createEntry([
            'label' => 'Sample Person',
            'type' => 'person',
        ]);

        self::assertSame('remote-abc', $result['id']);
        self::assertSame('POST', $GLOBALS['__cat_http_calls'][0]['method']);
        self::assertSame(
            'https://recognition.example/api/v0/roster',
            $GLOBALS['__cat_http_calls'][0]['url']
        );
    }

    public function test_update_entry_throws_exception_on_failure(): void
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

        $client = new RosterClient(new RecognitionSettings());

        $this->expectException(RosterClientException::class);
        $client->updateEntry('remote-xyz', ['label' => 'Updated']);
    }

    public function test_delete_entry_returns_true(): void
    {
        $GLOBALS['__cat_http_queue'] = [
            [
                'response' => [
                    'code' => 204,
                    'message' => 'No Content',
                ],
                'body' => '',
            ],
        ];

        $client = new RosterClient(new RecognitionSettings());
        self::assertTrue($client->deleteEntry('remote-123'));
        self::assertSame('DELETE', $GLOBALS['__cat_http_calls'][0]['method']);
    }

    public function test_generate_embeddings_returns_payload(): void
    {
        $GLOBALS['__cat_http_queue'] = [
            [
                'response' => [
                    'code' => 200,
                    'message' => 'OK',
                ],
                'body' => json_encode([
                    'vectors' => [
                        [0.1, 0.2, 0.3],
                    ],
                ]),
            ],
        ];

        $client = new RosterClient(new RecognitionSettings());
        $result = $client->generateEmbeddings([
            'images' => [
                [
                    'image_url' => 'https://example.test/image.png',
                ],
            ],
        ]);

        self::assertArrayHasKey('vectors', $result);
        self::assertSame('POST', $GLOBALS['__cat_http_calls'][0]['method']);
        self::assertSame(
            'https://recognition.example/api/v0/embeddings',
            $GLOBALS['__cat_http_calls'][0]['url']
        );
    }
}
