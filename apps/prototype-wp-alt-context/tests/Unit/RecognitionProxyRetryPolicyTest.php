<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionController;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;

/**
 * E15-3a-BR-21 Slice 5: WP mutation-proxy policy narrowing.
 *
 * When the backend surfaces `503 Retry-After`, the WP proxy must short-circuit
 * on the first attempt instead of burning 3 retries. Retry behavior for other
 * 5xx and transport failures is preserved.
 *
 * @covers \AltContext\Api\AbstractRecognitionProxyController
 */
class RecognitionProxyRetryPolicyTest extends TestCase
{
    private RecognitionController $controller;

    protected function setUp(): void
    {
        parent::setUp();

        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->setOption('acx_tier', 'free');

        $this->controller = new RecognitionController();
    }

    public function testBackend503WithRetryAfterShortCircuitsOnFirstAttempt(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 503, 'message' => 'Service Unavailable'],
            'headers' => ['Retry-After' => '5'],
            'body' => '{"error": "backend_overloaded"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(503, $result->get_status());
        $this->assertSame('5', $result->get_headers()['Retry-After'] ?? null);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls, '503 with Retry-After must not trigger retries');
    }

    public function testBackend502StillRetriesThreeTimes(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 502, 'message' => 'Bad Gateway'],
            'body' => '{"error": "bad_gateway"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 502, 'message' => 'Bad Gateway'],
            'body' => '{"error": "bad_gateway"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 502, 'message' => 'Bad Gateway'],
            'body' => '{"error": "bad_gateway"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(502, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, '502 must continue to exhaust 3 retries');
    }

    public function testBackend504StillRetriesThreeTimes(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 504, 'message' => 'Gateway Timeout'],
            'body' => '{"error": "gateway_timeout"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 504, 'message' => 'Gateway Timeout'],
            'body' => '{"error": "gateway_timeout"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 504, 'message' => 'Gateway Timeout'],
            'body' => '{"error": "gateway_timeout"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(504, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, '504 must continue to exhaust 3 retries');
    }

    public function testTransportErrorStillRetriesThreeTimes(): void
    {
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertTrue(is_wp_error($result), 'transport failure must return WP_Error after retries');

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, 'transport errors must continue to exhaust 3 retries');
    }

    public function testBackend503WithoutRetryAfterStillRetries(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 503, 'message' => 'Service Unavailable'],
            'body' => '{"error": "service_unavailable"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 503, 'message' => 'Service Unavailable'],
            'body' => '{"error": "service_unavailable"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 503, 'message' => 'Service Unavailable'],
            'body' => '{"error": "service_unavailable"}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/123/cancel');
        $request->set_param('job_id', 'test-123');

        $result = $this->controller->cancel_job($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $result);
        $this->assertSame(503, $result->get_status());

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, '503 without Retry-After must still retry');
    }
}
