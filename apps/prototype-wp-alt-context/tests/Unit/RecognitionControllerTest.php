<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * Tests for RecognitionController batch limit validation.
 *
 * @covers \AltContext\Api\RecognitionController
 */
class RecognitionControllerTest extends TestCase
{
    private RecognitionController $controller;

    protected function setUp(): void
    {
        parent::setUp();

        // Set up recognition URL so controller doesn't fail on missing config
        $this->setOption('alt_context_recognition_url', 'http://localhost:8000');
        $this->setOption('alt_context_tier', 'free');

        $this->controller = new RecognitionController();
    }

    /**
     * Test that batch limits allow up to 10000 items for MVP.
     *
     * This test ensures we don't regress to the old 50-item limit.
     * See: docs/tasks/4.0/4.11.0/stability-audit-2026-01-20.md
     */
    public function testBatchLimitAllows100Items(): void
    {
        // Generate 100 media IDs
        $mediaIds = range(1, 100);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        // Validate should pass (not return WP_Error)
        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(
            $result === true,
            'Batch of 100 items should pass validation (old limit was 50)'
        );
    }

    /**
     * Test that batch limits allow significantly more than old 50 limit.
     */
    public function testBatchLimitAllows500Items(): void
    {
        $mediaIds = range(1, 500);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(
            $result === true,
            'Batch of 500 items should pass validation for MVP'
        );
    }

    /**
     * Integration test: analyze_media should accept 100 items end-to-end.
     */
    public function testAnalyzeAccepts100MediaIds(): void
    {
        $mediaIds = range(1, 100);

        foreach ($mediaIds as $mediaId) {
            $GLOBALS['__ac_attachment_urls'][$mediaId] = sprintf('http://example.test/media/%d.jpg', $mediaId);
        }

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status": "queued"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $response = $this->controller->analyze_media($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $payload = json_decode($calls[0]['body'] ?? '', true);
        $this->assertIsArray($payload);
        $this->assertCount(100, $payload['media_items'] ?? []);
    }

    /**
     * Test that empty media_ids array is rejected.
     */
    public function testEmptyMediaIdsRejected(): void
    {
        $mediaIds = [];

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(is_wp_error($result), 'Empty media_ids should be rejected');
        $this->assertSame('missing_media_ids', $result->get_error_code());
    }

    /**
     * Test that non-array media_ids is rejected.
     */
    public function testNonArrayMediaIdsRejected(): void
    {
        $mediaIds = 'not-an-array';

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(is_wp_error($result), 'Non-array media_ids should be rejected');
        $this->assertSame('invalid_media_ids', $result->get_error_code());
    }

    /**
     * Test that exceeding 10000 limit is rejected.
     */
    public function testExceedingMaxLimitRejected(): void
    {
        // Generate more than max allowed
        $mediaIds = range(1, 10001);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', $mediaIds);

        $result = $this->controller->validate_media_ids($mediaIds, $request, 'media_ids');

        $this->assertTrue(is_wp_error($result), 'Exceeding 10000 items should be rejected');
        $this->assertSame('too_many_media_ids', $result->get_error_code());
    }

    public function testTopUnlabeledClustersHydrateThumbnailFallbacks(): void
    {
        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                [
                    'id' => 'cluster-1',
                    'representatives' => [
                        [
                            'id' => 'rep-1',
                            'media_id' => 101,
                            'thumb_url' => null,
                        ],
                        [
                            'id' => 'rep-2',
                            'media_id' => 202,
                            'thumbnail_url' => 'http://example.test/media/legacy-202.jpg',
                        ],
                    ],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $this->controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        $this->assertSame('http://example.test/media/101.jpg', $data[0]['representatives'][0]['thumb_url']);
        $this->assertSame('http://example.test/media/legacy-202.jpg', $data[0]['representatives'][1]['thumb_url']);
    }

    public function testDismissClusterProxiesToBackend(): void
    {
        $clusterId = 'eb3d26d3-dbb6-4c99-be66-068e1f3b82ae';
        $this->queueHttpResponse([
            'response' => ['code' => 204, 'message' => 'No Content'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/clusters/' . $clusterId . '/dismiss');
        $request->set_param('cluster_id', $clusterId);

        $response = $this->controller->dismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(204, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('POST', $calls[0]['method']);
        $this->assertStringContainsString('/recognition/clusters/' . $clusterId . '/dismiss', $calls[0]['url']);
        $this->assertStringContainsString('tenant_id=', $calls[0]['url']);

        $this->assertTrue($calls[0]['body'] === null || $calls[0]['body'] === '');
    }

    public function testUndismissClusterProxiesToBackend(): void
    {
        $clusterId = 'eb3d26d3-dbb6-4c99-be66-068e1f3b82ae';
        $this->queueHttpResponse([
            'response' => ['code' => 204, 'message' => 'No Content'],
            'body' => '',
        ]);

        $request = new WP_REST_Request('DELETE', '/acx/v1/recognition/clusters/' . $clusterId . '/dismiss');
        $request->set_param('cluster_id', $clusterId);

        $response = $this->controller->undismiss_cluster($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(204, $response->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('DELETE', $calls[0]['method']);
        $this->assertStringContainsString('/recognition/clusters/' . $clusterId . '/dismiss', $calls[0]['url']);
        $this->assertStringContainsString('tenant_id=', $calls[0]['url']);

        $this->assertTrue($calls[0]['body'] === null || $calls[0]['body'] === '');
    }
}
