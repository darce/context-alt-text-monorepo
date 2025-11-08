<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Integration;

use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionSettings;
use ContextAltText\Tests\TestCase;

/**
 * Integration tests for WordPress ↔ Recognition Service communication.
 *
 * These tests require the recognition service to be running locally on port 7860.
 * Skip these tests in CI unless a test service is available.
 *
 * @group integration
 * @group requires-recognition-service
 */
final class RecognitionServiceIntegrationTest extends TestCase
{
    private RecognitionClient $client;
    private RecognitionSettings $settings;

    protected function setUp(): void
    {
        parent::setUp();

        if (!getenv('CAT_RUN_RECOGNITION_TESTS')) {
            $this->markTestSkipped('Recognition service integration tests require CAT_RUN_RECOGNITION_TESTS=1.');
        }

        if (!$this->isRecognitionServiceAvailable()) {
            $this->markTestSkipped(
                'Recognition service not running on localhost:7860. ' .
                    'Start it with: cd apps/recognition-service && ./scripts/start_recognition_local.sh start'
            );
        }

        // Set up recognition settings for local service
        update_option('cat_settings', [
            'recognition' => [
                'baseUrl' => 'http://localhost:7860',
                'timeoutMs' => 30000,
                'enabled' => true,
            ],
        ]);

        $this->settings = new RecognitionSettings();
        $this->client = new RecognitionClient($this->settings);
    }

    protected function tearDown(): void
    {
        delete_option('cat_settings');
        parent::tearDown();
    }

    /**
     * Check if recognition service is available.
     */
    private function isRecognitionServiceAvailable(): bool
    {
        $ch = curl_init('http://localhost:7860/api/v0/health');
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 2);
        curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 2);
        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        return $httpCode === 200 && $response !== false;
    }

    public function test_settings_are_configured_from_option(): void
    {
        $this->assertTrue($this->settings->isConfigured(), 'Settings should be configured');
        $this->assertEquals('http://localhost:7860', $this->settings->getBaseUrl());
        $this->assertEquals(30000, $this->settings->getTimeoutMs());
    }

    public function test_health_check_returns_ok(): void
    {
        $response = $this->client->health();

        $this->assertIsArray($response, 'Health response should be an array');
        $this->assertArrayHasKey('status', $response, 'Health response should have status key');
        $this->assertEquals('ok', $response['status'], 'Health status should be ok');
    }

    public function test_service_info_returns_expected_structure(): void
    {
        $response = $this->client->getServiceInfo();

        $this->assertIsArray($response, 'Service info should be an array');
        $this->assertArrayHasKey('status', $response);
        $this->assertArrayHasKey('data', $response);
        $this->assertEquals('ok', $response['status']);

        $data = $response['data'];
        $this->assertArrayHasKey('model', $data);
        $this->assertArrayHasKey('recognition', $data);
        $this->assertArrayHasKey('embedding_router', $data);

        // Verify model info
        $this->assertArrayHasKey('name', $data['model']);
        $this->assertEquals('buffalo_l', $data['model']['name'], 'Model should be buffalo_l');

        // Verify recognition config
        $this->assertArrayHasKey('default_threshold', $data['recognition']);
        $this->assertArrayHasKey('embedding_dimension', $data['recognition']);
        $this->assertEquals(512, $data['recognition']['embedding_dimension'], 'Embedding dimension should be 512');
    }

    public function test_analyze_scene_with_base64_image(): void
    {
        // Create a 1x1 pixel PNG image (base64 encoded)
        $imageBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAnEB7SBSYQAAAABJRU5ErkJggg==';

        $result = $this->client->analyzeSceneBase64([
            [
                'base64' => $imageBase64,
                'filename' => 'test.png',
            ],
        ]);

        $this->assertIsArray($result, 'Analyze scene result should be an array');
        $this->assertArrayHasKey('results', $result);
        $this->assertArrayHasKey('total_images_processed', $result);
        $this->assertEquals(1, $result['total_images_processed'], 'Should process 1 image');

        $firstResult = $result['results'][0];
        $this->assertArrayHasKey('scene_description', $firstResult);
        $this->assertArrayHasKey('detected_entities', $firstResult);
        $this->assertArrayHasKey('processing_metadata', $firstResult);

        // For a 1x1 pixel image, we expect no faces detected
        $this->assertIsArray($firstResult['detected_entities']);
    }

    public function test_analyze_scene_with_custom_threshold(): void
    {
        $imageBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAnEB7SBSYQAAAABJRU5ErkJggg==';

        $result = $this->client->analyzeSceneBase64(
            [['base64' => $imageBase64, 'filename' => 'test.png']],
            0.7 // Custom threshold
        );

        $this->assertIsArray($result);
        $this->assertArrayHasKey('configuration_used', $result);
        $this->assertEquals(0.7, $result['configuration_used']['threshold']);
    }

    public function test_embeddings_endpoint_returns_faces_structure(): void
    {
        $imageBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAnEB7SBSYQAAAABJRU5ErkJggg==';

        $result = $this->client->generateEmbeddings([
            'base64' => $imageBase64,
            'filename' => 'test.png',
        ]);

        $this->assertIsArray($result, 'Embeddings result should be an array');
        $this->assertArrayHasKey('faces', $result);
        $this->assertArrayHasKey('processing_time_ms', $result);
        $this->assertArrayHasKey('threshold', $result);

        // For a 1x1 pixel image, faces array should be empty
        $this->assertIsArray($result['faces']);
        $this->assertEmpty($result['faces'], 'Should not detect faces in 1x1 pixel image');
    }

    public function test_roster_listing_returns_expected_structure(): void
    {
        $result = $this->client->getRosterList();

        $this->assertIsArray($result, 'Roster list should be an array');
        $this->assertArrayHasKey('model', $result);
        $this->assertArrayHasKey('count', $result);
        $this->assertArrayHasKey('entries', $result);
        $this->assertArrayHasKey('pagination', $result);

        if ($result['count'] > 0) {
            $firstEntry = $result['entries'][0];
            $this->assertArrayHasKey('unique_id', $firstEntry);
            $this->assertArrayHasKey('name', $firstEntry);
            $this->assertArrayHasKey('display_name', $firstEntry);
            $this->assertArrayHasKey('metadata', $firstEntry);
        }
    }

    public function test_roster_pagination_works(): void
    {
        $page1 = $this->client->getRosterList(1, 5);
        $this->assertArrayHasKey('pagination', $page1);
        $this->assertEquals(1, $page1['pagination']['page']);
        $this->assertEquals(5, $page1['pagination']['page_size']);

        if ($page1['pagination']['has_next']) {
            $page2 = $this->client->getRosterList(2, 5);
            $this->assertEquals(2, $page2['pagination']['page']);
        }
    }

    public function test_connection_timeout_handling(): void
    {
        // Create client with very short timeout
        update_option('cat_settings', [
            'recognition' => [
                'baseUrl' => 'http://localhost:7860',
                'timeoutMs' => 1, // 1ms - should timeout
                'enabled' => true,
            ],
        ]);

        $shortTimeoutSettings = new RecognitionSettings();
        $shortTimeoutClient = new RecognitionClient($shortTimeoutSettings);

        $this->expectException(\ContextAltText\Recognition\RecognitionClientException::class);
        $this->expectExceptionMessageMatches('/timeout|timed out/i');

        // This should timeout because analyze-scene takes longer than 1ms
        $imageBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAnEB7SBSYQAAAABJRU5ErkJggg==';
        $shortTimeoutClient->analyzeSceneBase64([
            ['base64' => $imageBase64, 'filename' => 'test.png'],
        ]);
    }

    public function test_invalid_base_url_throws_exception(): void
    {
        update_option('cat_settings', [
            'recognition' => [
                'baseUrl' => 'http://localhost:9999', // Non-existent service
                'timeoutMs' => 2000,
                'enabled' => true,
            ],
        ]);

        $invalidSettings = new RecognitionSettings();
        $invalidClient = new RecognitionClient($invalidSettings);

        $this->expectException(\ContextAltText\Recognition\RecognitionClientException::class);

        $invalidClient->health();
    }

    /**
     * Test that retries work for transient failures.
     *
     * This is hard to test without a mock server, but we can at least
     * verify the retry logic doesn't break normal requests.
     */
    public function test_retry_logic_does_not_break_successful_requests(): void
    {
        // Even with retries enabled, a successful request should work
        $response = $this->client->health();
        $this->assertEquals('ok', $response['status']);
    }

    /**
     * Test round-trip: create attachment, run recognition, verify observations.
     */
    public function test_full_recognition_pipeline_with_attachment(): void
    {
        // Create a test attachment
        $imageData = base64_decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAnEB7SBSYQAAAABJRU5ErkJggg==');
        $upload = wp_upload_bits('test-recognition.png', null, $imageData);

        $this->assertFalse($upload['error'], 'Image upload should succeed');

        $attachmentId = wp_insert_attachment([
            'post_title' => 'Test Recognition Image',
            'post_content' => '',
            'post_status' => 'inherit',
            'post_mime_type' => 'image/png',
        ], $upload['file']);

        $this->assertGreaterThan(0, $attachmentId, 'Attachment should be created');

        try {
            // Get attachment URL
            $attachmentUrl = wp_get_attachment_url($attachmentId);
            $this->assertNotFalse($attachmentUrl, 'Attachment URL should exist');

            // Run recognition (this would normally go through RecognitionJobService)
            $imageBase64 = base64_encode($imageData);
            $result = $this->client->analyzeSceneBase64([
                ['base64' => $imageBase64, 'filename' => basename($upload['file'])],
            ]);

            $this->assertIsArray($result);
            $this->assertArrayHasKey('results', $result);
            $this->assertCount(1, $result['results']);

            // Verify processing metadata
            $firstResult = $result['results'][0];
            $this->assertArrayHasKey('processing_metadata', $firstResult);
            $this->assertArrayHasKey('processing_time_ms', $firstResult['processing_metadata']);
        } finally {
            // Cleanup
            wp_delete_attachment($attachmentId, true);
            @unlink($upload['file']);
        }
    }
}
