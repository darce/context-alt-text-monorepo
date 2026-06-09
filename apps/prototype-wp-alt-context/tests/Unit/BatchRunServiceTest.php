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
}
