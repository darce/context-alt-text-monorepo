<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\DescribeController
 */
class DescribeRunControllerTest extends TestCase
{
    private DescribeController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->controller = new DescribeController();
    }

    public function testSubmitBulkDescribeRunProxiesToSceneRunEndpoint(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 202, 'message' => 'Accepted'],
            'body' => '{"run_id":"11111111-1111-1111-1111-111111111111","status":"pending","phase":"queued","completed":0,"failed":0,"skipped":0,"total":2,"cancel_requested":false,"gpu_state":null}',
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs');
        $request->set_param('media_ids', [101, 202]);

        $response = $this->controller->submit_describe_run($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $call = $this->getHttpCalls()[0];
        $this->assertStringContainsString('/scene/describe/run', $call['url']);
        $decoded = json_decode((string) $call['args']['body'], true);
        $this->assertSame([101, 202], $decoded['media_ids']);
        $this->assertArrayHasKey('tenant_id', $decoded);
    }

    public function testStatusAndCancelProxyToSceneRunEndpoint(): void
    {
        $runId = '22222222-2222-2222-2222-222222222222';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"run_id":"' . $runId . '","status":"running","phase":"describing","completed":1,"failed":0,"skipped":0,"total":2,"cancel_requested":false,"gpu_state":null}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '{"run_id":"' . $runId . '","status":"cancelled","phase":"cancelled","completed":1,"failed":0,"skipped":1,"total":2,"cancel_requested":true,"gpu_state":null}',
        ]);

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $cancelRequest = new WP_REST_Request('POST', '/acx/v1/recognition/describe/runs/' . $runId . '/cancel');
        $cancelRequest->set_param('run_id', $runId);

        $this->controller->get_describe_run_status($statusRequest);
        $this->controller->cancel_describe_run($cancelRequest);

        $calls = $this->getHttpCalls();
        $this->assertStringContainsString('/scene/describe/run/' . $runId, $calls[0]['url']);
        $this->assertSame('GET', $calls[0]['args']['method']);
        $this->assertStringContainsString('/scene/describe/run/' . $runId, $calls[1]['url']);
        $this->assertSame('DELETE', $calls[1]['args']['method']);
    }

    public function testDescribeRunStreamHoldIsBounded(): void
    {
        $this->assertSame(25, $this->controller->get_describe_run_stream_max_hold_seconds());
    }
}
