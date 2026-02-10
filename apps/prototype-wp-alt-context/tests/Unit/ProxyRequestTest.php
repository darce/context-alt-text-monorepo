<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionController;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_Error;

/**
 * Tests for RecognitionController proxy_request behavior.
 *
 * @covers \AltContext\Api\RecognitionController
 */
class ProxyRequestTest extends TestCase
{
    private RecognitionController $controller;

    protected function setUp(): void
    {
        parent::setUp();

        $this->setOption('alt_context_recognition_url', 'http://localhost:8000');
        $this->setOption('alt_context_tier', 'free');

        $this->controller = new RecognitionController();
    }

    /**
     * Test proxy request fails when recognition URL is not configured.
     */
    public function testProxyFailsWhenUrlNotConfigured(): void
    {
        // Create controller with empty URL
        $this->setOption('alt_context_recognition_url', '');
        $controller = new RecognitionController();

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-job-id');

        $result = $controller->get_job_status($request);

        $this->assertTrue(is_wp_error($result), 'Should return WP_Error when URL not configured');
        $this->assertSame('recognition_not_configured', $result->get_error_code());
    }

    /**
     * Test successful proxy request returns response.
     */
    public function testSuccessfulProxyRequestReturnsResponse(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status": "completed", "job_id": "test-123"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());

        $data = $result->get_data();
        $this->assertSame('completed', $data['status']);
        $this->assertSame('test-123', $data['job_id']);
    }

    /**
     * Test proxy request includes API key header when configured.
     */
    public function testProxyRequestIncludesApiKeyHeader(): void
    {
        $this->setOption('alt_context_recognition_api_key', 'secret-key-123');
        $controller = new RecognitionController();

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $controller->get_job_status($request);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('secret-key-123', $calls[0]['args']['headers']['X-API-Key'] ?? null);
    }

    /**
     * Test proxy request retries on 500 error.
     */
    public function testProxyRequestRetriesOn500Error(): void
    {
        // Queue: 500, 500, 200
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error": "temporary failure"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error": "temporary failure"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status": "success"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        // Should eventually succeed
        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());

        // Should have made 3 attempts
        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, 'Should retry twice after initial 500 errors');
    }

    /**
     * Test proxy request does not retry on 4xx client errors.
     */
    public function testProxyRequestDoesNotRetryOn4xxError(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 400, 'message' => 'Bad Request'],
            'body' => '{"error": "invalid request"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        // Should return 400 immediately without retry
        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(400, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls, 'Should not retry on 4xx errors');
    }

    /**
     * Test proxy request retries on WP_Error (network failure).
     */
    public function testProxyRequestRetriesOnNetworkError(): void
    {
        // Queue: WP_Error, WP_Error, success
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection timed out'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection reset'));
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"status": "success"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        // Should eventually succeed
        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, 'Should retry after network errors');
    }

    /**
     * Test proxy request returns error after max retries exhausted.
     */
    public function testProxyRequestReturnsErrorAfterMaxRetries(): void
    {
        // Queue: 500, 500, 500 (3 failures = max retries exhausted)
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error": "server down"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error": "server down"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error": "server down"}',
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        // Should return the 500 response after max retries
        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(500, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, 'Should make exactly 3 attempts (max retries)');
    }

    /**
     * Test proxy request returns WP_Error after max network retries.
     */
    public function testProxyRequestReturnsWpErrorAfterMaxNetworkRetries(): void
    {
        // Queue: 3 network errors
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/123');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->get_job_status($request);

        // Should return the WP_Error after max retries
        $this->assertTrue(is_wp_error($result), 'Should return WP_Error after max network retries');
        $this->assertSame('http_request_failed', $result->get_error_code());

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, 'Should make exactly 3 attempts');
    }
}
