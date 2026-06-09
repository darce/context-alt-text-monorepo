<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Api\Services\BatchRunService;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\BatchRunService
 */
class BatchRunServiceTest extends TestCase
{
    private BatchRunService $service;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->service = new BatchRunService(new AnalysisJobsController());
    }

    public function testRecordClientBatchFailurePersistsSyntheticBatchFailure(): void
    {
        $runId = 'f1f1f1f1-f1f1-4f1f-8f1f-f1f1f1f1f1f1';

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/batch-runs/' . $runId . '/client-failures');
        $request->set_param('run_id', $runId);
        $request->set_param('batch_index', 1);
        $request->set_param('submitted_total', 4);
        $request->set_param('media_ids', [601, 602]);

        $response = $this->service->record_client_batch_failure($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(202, $response->get_status());

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $this->service->get_batch_run_status($statusRequest);

        $this->assertInstanceOf(WP_REST_Response::class, $statusResponse);
        $statusData = $statusResponse->get_data();
        $this->assertSame(4, $statusData['submitted_total']);
        $this->assertSame(2, $statusData['failed_total']);
    }

    public function testRefreshStaleBatchRunChildrenRecords404AsFailed(): void
    {
        $runId = 'c0c0c0c0-c0c0-4c0c-8c0c-c0c0c0c0c0c0';
        $jobId = '30303030-3030-4030-8030-303030303030';

        $GLOBALS['__ac_attachment_urls'][171] = 'http://example.test/media/171.jpg';
        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'pending',
                'type' => 'analyze',
                'progress' => ['completed' => 0, 'total' => 1],
            ]),
        ]);

        $analyzeRequest = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $analyzeRequest->set_param('batch_run_id', $runId);
        $analyzeRequest->set_param('batch_index', 0);
        $analyzeRequest->set_param('submitted_total', 1);
        $analyzeRequest->set_param('media_ids', [171]);
        (new AnalysisJobsController())->analyze_media($analyzeRequest);

        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'Job not found']),
        ]);

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $this->service->get_batch_run_status($statusRequest);

        $this->assertInstanceOf(WP_REST_Response::class, $statusResponse);
        $statusData = $statusResponse->get_data();
        $this->assertSame(1, $statusData['failed_total']);
        $this->assertTrue($statusData['terminal_state']);
    }
}
