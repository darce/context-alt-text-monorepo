<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Api\Services\BatchRunService;
use AltContext\Api\Services\JobStatusService;
use AltContext\Api\Services\ProjectionSyncService;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\JobStatusService
 */
class JobStatusServiceTest extends TestCase
{
    private JobStatusService $service;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $host = new AnalysisJobsController();
        $batch = new BatchRunService($host);
        $projection = new ProjectionSyncService($host);
        $this->service = new JobStatusService($host, $batch, $projection);
    }

    public function testGetJobStatusRejectsMissingJobId(): void
    {
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/');

        $result = $this->service->get_job_status($request);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('missing_job_id', $result->get_error_code());
    }

    public function testGetJobStatusReturnsOfflinePayloadWhenProxyUnavailable(): void
    {
        $jobId = '33333333-3333-3333-3333-333333333333';
        $this->queueHttpResponse(new WP_Error('http_request_failed', 'Connection refused'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $request->set_param('job_id', $jobId);

        $response = $this->service->get_job_status($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame($jobId, $data['id']);
        $this->assertSame('failed', $data['status']);
        $this->assertSame('Recognition backend unavailable.', $data['message']);
    }

    public function testRecordObservedJobStatusFromResponseMaps404ToFailed(): void
    {
        $jobId = '44444444-4444-4444-4444-444444444444';
        $runId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';

        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');
        $GLOBALS['__ac_attachment_urls'][301] = 'http://example.test/media/301.jpg';

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
        $analyzeRequest->set_param('media_ids', [301]);
        (new AnalysisJobsController())->analyze_media($analyzeRequest);

        $this->service->record_observed_job_status_from_response(
            $jobId,
            new WP_REST_Response(['detail' => 'Job not found'], 404)
        );

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $batch = new BatchRunService(new AnalysisJobsController());
        $statusResponse = $batch->get_batch_run_status($statusRequest);

        $this->assertInstanceOf(WP_REST_Response::class, $statusResponse);
        $statusData = $statusResponse->get_data();
        $this->assertSame(1, $statusData['failed_total']);
        $this->assertTrue($statusData['terminal_state']);
    }

    public function testAcknowledgeProjectionRejectsInvalidSnapshotVersion(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/55555555-5555-5555-5555-555555555555/acknowledge-projection');
        $request->set_param('job_id', '55555555-5555-5555-5555-555555555555');
        $request->set_body_params(['snapshot_version' => 0]);

        $result = $this->service->acknowledge_projection($request);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('invalid_snapshot_version', $result->get_error_code());
    }
}
