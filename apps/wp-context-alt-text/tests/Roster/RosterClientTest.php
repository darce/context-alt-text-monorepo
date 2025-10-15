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
                    'success' => true,
                    'entry' => [
                        'unique_id' => 'remote-abc',
                        'name' => 'Sample Person',
                        'display_name' => 'Sample Person',
                        'metadata' => ['type' => 'person'],
                        'reference_images' => [],
                        'updated_timestamp' => '2024-01-01T00:00:00Z',
                    ],
                ]),
            ],
        ];

        $client = new RosterClient(new RecognitionSettings());
        $result = $client->createEntry([
            'label' => 'Sample Person',
            'type' => 'person',
            'metadata' => [],
            'embeddings' => [[
                'embedding' => [0.1, 0.2],
                'metadata' => ['confidence' => 0.9],
                'image_path' => 'https://example.test/sample.jpg',
            ]],
        ]);

        self::assertTrue($result['success']);
        self::assertSame('remote-abc', $result['entry']['unique_id']);
        self::assertSame('POST', $GLOBALS['__cat_http_calls'][0]['method']);
        self::assertSame(
            'https://recognition.example/api/v0/roster/insightface_w600k/upsert',
            $GLOBALS['__cat_http_calls'][0]['url']
        );

        $decodedBody = json_decode($GLOBALS['__cat_http_calls'][0]['body'], true);
        self::assertSame('Sample Person', $decodedBody['name']);
        self::assertSame([0.1, 0.2], $decodedBody['embedding']);
        self::assertSame('person', $decodedBody['metadata']['type']);
        self::assertSame('context-alt-text', $decodedBody['metadata']['source']);
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
                    'faces' => [
                        ['embedding' => [0.1, 0.2, 0.3]],
                    ],
                ]),
            ],
        ];

        $client = new RosterClient(new RecognitionSettings());
        $result = $client->generateEmbeddings([
            'image' => [
                'image_url' => 'https://example.test/image.png',
            ],
        ]);

        self::assertArrayHasKey('faces', $result);
        self::assertSame('POST', $GLOBALS['__cat_http_calls'][0]['method']);
        self::assertSame(
            'https://recognition.example/api/v0/embeddings',
            $GLOBALS['__cat_http_calls'][0]['url']
        );
    }

    public function test_append_reference_embedding_posts_payload(): void
    {
        $GLOBALS['__cat_http_queue'] = [
            [
                'response' => [
                    'code' => 200,
                    'message' => 'OK',
                ],
                'body' => json_encode(['status' => 'ok']),
            ],
        ];

        $client = new RosterClient(new RecognitionSettings());
        $client->appendReferenceEmbedding('remote-xyz', [
            'embedding' => [0.1, 0.2],
            'image_path' => 'https://example.test/image.png',
        ]);

        self::assertSame('POST', $GLOBALS['__cat_http_calls'][0]['method']);
        self::assertSame(
            'https://recognition.example/api/v0/roster/remote-xyz/embeddings',
            $GLOBALS['__cat_http_calls'][0]['url']
        );
    }
}
