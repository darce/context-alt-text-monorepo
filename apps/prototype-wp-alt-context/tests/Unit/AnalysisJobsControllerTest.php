<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Api\Services\BatchRunService;
use AltContext\Api\Services\JobProgressStreamService;
use AltContext\Api\Services\JobStatusService;
use AltContext\Api\Services\ProjectionSyncService;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\AnalysisJobsController
 */
class AnalysisJobsControllerTest extends TestCase
{
    private AnalysisJobsController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_tier', 'free');
        $this->controller = new AnalysisJobsController();
    }

    public function testRegisterRoutesIncludesAnalyzeValidationCallback(): void
    {
        $this->controller->register_routes();

        $route = $this->findRegisteredRoute('/recognition/analyze', 'POST');
        $this->assertNotNull($route);
        $this->assertArrayHasKey('args', $route['args']);
        $this->assertArrayHasKey('media_ids', $route['args']['args']);
        $this->assertArrayHasKey('validate_callback', $route['args']['args']['media_ids']);

        $batchRoute = $this->findRegisteredRoute('/recognition/batch-runs/(?P<run_id>[a-f0-9-]+)', 'GET');
        $this->assertNotNull($batchRoute);

        $recentBatchRoute = $this->findRegisteredRoute('/recognition/batch-runs', 'GET');
        $this->assertNotNull($recentBatchRoute);
    }

    public function testGetRecentBatchRunsReturnsDurableItemsForCurrentTenant(): void
    {
        $runId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        $jobId = '11111111-1111-1111-1111-111111111111';
        $failedRunId = 'ffffffff-ffff-4fff-8fff-ffffffffffff';

        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';
        $GLOBALS['__ac_attachment_urls'][102] = 'http://example.test/media/102.jpg';

        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'pending',
                'type' => 'analyze',
                'progress' => ['completed' => 0, 'total' => 2],
            ]),
        ]);

        $analyzeRequest = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $analyzeRequest->set_param('batch_run_id', $runId);
        $analyzeRequest->set_param('batch_index', 0);
        $analyzeRequest->set_param('submitted_total', 2);
        $analyzeRequest->set_param('media_ids', [101, 102]);
        $this->controller->analyze_media($analyzeRequest);

        $failureRequest = new WP_REST_Request('POST', '/acx/v1/recognition/batch-runs/' . $failedRunId . '/client-failures');
        $failureRequest->set_param('run_id', $failedRunId);
        $failureRequest->set_param('batch_index', 0);
        $failureRequest->set_param('submitted_total', 2);
        $failureRequest->set_param('media_ids', [301, 302]);
        $this->controller->record_client_batch_failure($failureRequest);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs');
        $request->set_param('limit', 5);

        $response = $this->controller->get_recent_batch_runs($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertIsArray($data['items'] ?? null);

        $itemsByRunId = [];
        foreach ($data['items'] as $item) {
            $itemsByRunId[$item['run_id']] = $item;
        }

        $this->assertArrayHasKey($runId, $itemsByRunId);
        $this->assertArrayHasKey($failedRunId, $itemsByRunId);
        $this->assertSame($jobId, $itemsByRunId[$runId]['latest_job_id']);
        $this->assertSame([$jobId], $itemsByRunId[$runId]['child_job_ids']);
        $this->assertSame(2, $itemsByRunId[$runId]['submitted_total']);
        $this->assertSame('', $itemsByRunId[$failedRunId]['latest_job_id']);
        $this->assertSame([], $itemsByRunId[$failedRunId]['child_job_ids']);
        $this->assertSame(2, $itemsByRunId[$failedRunId]['failed_total']);
        $this->assertCount(1, $itemsByRunId[$failedRunId]['failed_batches']);
    }

    public function testAnalyzeMediaRecordsBatchRunAndReturnsBatchRunId(): void
    {
        $runId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        $jobId = '11111111-1111-1111-1111-111111111111';

        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';
        $GLOBALS['__ac_attachment_urls'][102] = 'http://example.test/media/102.jpg';

        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'pending',
                'type' => 'analyze',
                'progress' => ['completed' => 0, 'total' => 2],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('batch_run_id', $runId);
        $request->set_param('batch_index', 0);
        $request->set_param('submitted_total', 2);
        $request->set_param('media_ids', [101, 102]);

        $response = $this->controller->analyze_media($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame($runId, $data['batch_run_id'] ?? null);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed',
                'type' => 'analyze',
                'progress' => ['completed' => 2, 'total' => 2],
            ]),
        ]);

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $this->controller->get_batch_run_status($statusRequest);

        $this->assertInstanceOf(\WP_REST_Response::class, $statusResponse);
        $statusData = $statusResponse->get_data();
        $this->assertSame($runId, $statusData['id']);
        $this->assertSame(2, $statusData['submitted_total']);
        $this->assertSame(2, $statusData['accepted_total']);
        $this->assertSame(2, $statusData['completed_total']);
        $this->assertSame(0, $statusData['failed_total']);
        $this->assertSame([$jobId], $statusData['child_job_ids']);
        $this->assertTrue($statusData['terminal_state']);
    }

    public function testGetJobStatusMarksKnownMissingBatchChildAsFailed(): void
    {
        $runId = 'a0a0a0a0-a0a0-4a0a-8a0a-a0a0a0a0a0a0';
        $jobId = '10101010-1010-4010-8010-101010101010';

        $GLOBALS['__ac_attachment_urls'][151] = 'http://example.test/media/151.jpg';
        $GLOBALS['__ac_attachment_urls'][152] = 'http://example.test/media/152.jpg';

        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'pending',
                'type' => 'analyze',
                'progress' => ['completed' => 0, 'total' => 2],
            ]),
        ]);

        $analyzeRequest = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $analyzeRequest->set_param('batch_run_id', $runId);
        $analyzeRequest->set_param('batch_index', 0);
        $analyzeRequest->set_param('submitted_total', 2);
        $analyzeRequest->set_param('media_ids', [151, 152]);
        $this->controller->analyze_media($analyzeRequest);

        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'Job not found']),
        ]);

        $jobStatusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $jobStatusRequest->set_param('job_id', $jobId);
        $jobStatusResponse = $this->controller->get_job_status($jobStatusRequest);

        $this->assertInstanceOf(\WP_REST_Response::class, $jobStatusResponse);
        $this->assertSame(404, $jobStatusResponse->get_status());

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $this->controller->get_batch_run_status($statusRequest);

        $this->assertInstanceOf(\WP_REST_Response::class, $statusResponse);
        $statusData = $statusResponse->get_data();
        $this->assertSame(0, $statusData['completed_total']);
        $this->assertSame(2, $statusData['failed_total']);
        $this->assertTrue($statusData['terminal_state']);
    }

    public function testBatchRunRefreshMarksKnownMissingChildAsFailed(): void
    {
        $runId = 'b0b0b0b0-b0b0-4b0b-8b0b-b0b0b0b0b0b0';
        $jobId = '20202020-2020-4020-8020-202020202020';

        $GLOBALS['__ac_attachment_urls'][161] = 'http://example.test/media/161.jpg';

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
        $analyzeRequest->set_param('media_ids', [161]);
        $this->controller->analyze_media($analyzeRequest);

        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'Job not found']),
        ]);

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $this->controller->get_batch_run_status($statusRequest);

        $this->assertInstanceOf(\WP_REST_Response::class, $statusResponse);
        $statusData = $statusResponse->get_data();
        $this->assertSame(0, $statusData['completed_total']);
        $this->assertSame(1, $statusData['failed_total']);
        $this->assertTrue($statusData['terminal_state']);
    }

    public function testAnalyzeMediaRecordsSubmitFailuresInsideBatchRun(): void
    {
        $runId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
        $GLOBALS['__ac_attachment_urls'][201] = 'http://example.test/media/201.jpg';
        $GLOBALS['__ac_attachment_urls'][202] = 'http://example.test/media/202.jpg';

        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('batch_run_id', $runId);
        $request->set_param('batch_index', 1);
        $request->set_param('submitted_total', 2);
        $request->set_param('media_ids', [201, 202]);

        $result = $this->controller->analyze_media($request);

        $this->assertTrue(is_wp_error($result));

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $this->controller->get_batch_run_status($statusRequest);

        $this->assertInstanceOf(\WP_REST_Response::class, $statusResponse);
        $statusData = $statusResponse->get_data();
        $this->assertSame(2, $statusData['submitted_total']);
        $this->assertSame(0, $statusData['accepted_total']);
        $this->assertSame(2, $statusData['failed_total']);
        $this->assertSame([], $statusData['child_job_ids']);
        $this->assertCount(1, $statusData['failed_batches']);
        $this->assertSame('proxy_failed', $statusData['failed_batches'][0]['error_code']);
        $this->assertTrue($statusData['terminal_state']);
    }

    public function testRecordClientBatchFailurePersistsSyntheticBatchFailure(): void
    {
        $runId = 'f1f1f1f1-f1f1-4f1f-8f1f-f1f1f1f1f1f1';

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/batch-runs/' . $runId . '/client-failures');
        $request->set_param('run_id', $runId);
        $request->set_param('batch_index', 1);
        $request->set_param('submitted_total', 4);
        $request->set_param('media_ids', [601, 602]);

        $response = $this->controller->record_client_batch_failure($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(202, $response->get_status());

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $this->controller->get_batch_run_status($statusRequest);

        $this->assertInstanceOf(\WP_REST_Response::class, $statusResponse);
        $statusData = $statusResponse->get_data();
        $this->assertSame(4, $statusData['submitted_total']);
        $this->assertSame(2, $statusData['failed_total']);
        $this->assertCount(1, $statusData['failed_batches']);
        $this->assertSame('client_transport_error', $statusData['failed_batches'][0]['error_code']);
    }

    public function testGetBatchRunStatusUsesObservedChildStatusWithoutExtraProxyFanout(): void
    {
        $runId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
        $jobId = '33333333-3333-3333-3333-333333333333';

        $GLOBALS['__ac_attachment_urls'][301] = 'http://example.test/media/301.jpg';
        $GLOBALS['__ac_attachment_urls'][302] = 'http://example.test/media/302.jpg';

        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'pending',
                'type' => 'analyze',
                'progress' => ['completed' => 0, 'total' => 2],
            ]),
        ]);

        $analyzeRequest = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $analyzeRequest->set_param('batch_run_id', $runId);
        $analyzeRequest->set_param('batch_index', 0);
        $analyzeRequest->set_param('submitted_total', 2);
        $analyzeRequest->set_param('media_ids', [301, 302]);
        $this->controller->analyze_media($analyzeRequest);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed',
                'type' => 'analyze',
                'progress' => ['completed' => 2, 'total' => 2],
            ]),
        ]);

        $jobStatusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $jobStatusRequest->set_param('job_id', $jobId);
        $jobStatusResponse = $this->controller->get_job_status($jobStatusRequest);
        $this->assertInstanceOf(\WP_REST_Response::class, $jobStatusResponse);

        $httpCallsBeforeAggregateRead = count($this->getHttpCalls());

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $this->controller->get_batch_run_status($statusRequest);

        $this->assertInstanceOf(\WP_REST_Response::class, $statusResponse);
        $statusData = $statusResponse->get_data();
        $this->assertSame(2, $statusData['completed_total']);
        $this->assertTrue($statusData['terminal_state']);
        $this->assertCount(
            $httpCallsBeforeAggregateRead,
            $this->getHttpCalls(),
            'BatchRun aggregate should use cached observed child status instead of proxying every child again.'
        );
    }

    public function testGetBatchRunStatusRejectsRunsRecordedForAnotherTenant(): void
    {
        $runId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
        $jobId = '44444444-4444-4444-4444-444444444444';

        $ownerController = new class() extends AnalysisJobsController {
            public function get_tenant_id(): string
            {
                return 'tenant-a';
            }
        };

        $otherTenantController = new class() extends AnalysisJobsController {
            public function get_tenant_id(): string
            {
                return 'tenant-b';
            }
        };

        $GLOBALS['__ac_attachment_urls'][401] = 'http://example.test/media/401.jpg';

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
        $analyzeRequest->set_param('media_ids', [401]);

        $ownerResponse = $ownerController->analyze_media($analyzeRequest);
        $this->assertInstanceOf(\WP_REST_Response::class, $ownerResponse);

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $otherTenantController->get_batch_run_status($statusRequest);

        $this->assertTrue(is_wp_error($statusResponse));
        $this->assertSame('batch_run_not_found', $statusResponse->get_error_code());
    }

    public function testAnalyzeMediaRejectsMissingPayload(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');

        $result = $this->controller->analyze_media($request);

        $this->assertTrue(is_wp_error($result));
        $this->assertSame('no_media_items', $result->get_error_code());
    }

    public function testAnalyzeMediaReturns409WhenRecognitionDisabled(): void
    {
        $this->setOption('acx_recognition_enabled', false);
        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

        add_filter('acx_recognition_transport', static fn (string $current): string => 'url');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => '11111111-1111-1111-1111-111111111111',
                'status' => 'pending',
                'type' => 'analyze',
                'progress' => ['completed' => 0, 'total' => 1],
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $request->set_param('media_ids', [101]);

        $result = $this->controller->analyze_media($request);

        $this->assertTrue(is_wp_error($result));
        $this->assertSame('recognition_disabled', $result->get_error_code());
        $this->assertSame(409, $result->get_error_data()['status'] ?? null);
        $this->assertSame(
            'People identification is turned off in Settings.',
            $result->get_error_message()
        );
        $this->assertSame([], $this->getHttpCalls());
    }

    public function testGetJobStatusDoesNotDispatchXmpRefresh(): void
    {
        $jobId = '11111111-1111-1111-1111-111111111111';
        $captured = [];

        add_action(
            'acx_xmp_refresh_requested',
            static function ($attachmentId, $dispatchedJobId) use (&$captured): void {
                $captured[] = [(int) $attachmentId, (string) $dispatchedJobId];
            },
            10,
            2
        );

        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';
        $GLOBALS['__ac_attachment_urls'][202] = 'http://example.test/media/202.jpg';

        // E15-11 Slice 2.2: default transport is now 'multipart' which would
        // require attached files on disk; this test only cares about XMP
        // refresh dispatch on the get_job_status path, so pin to 'url'.
        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'pending',
            ]),
        ]);

        $analyzeRequest = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $analyzeRequest->set_param('media_ids', [101, 202]);
        $this->controller->analyze_media($analyzeRequest);

        $completedPayload = [
            'id' => $jobId,
            'status' => 'completed',
            'type' => 'analyze',
            'progress' => ['completed' => 2, 'total' => 2],
        ];

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode($completedPayload),
        ]);

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $statusRequest->set_param('job_id', $jobId);
        $this->controller->get_job_status($statusRequest);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode($completedPayload),
        ]);

        $this->controller->get_job_status($statusRequest);
        $this->assertSame([], $captured);
    }

    public function testGetJobStatusDoesNotDispatchXmpRefreshFromJobPayloadMediaIds(): void
    {
        $jobId = '22222222-2222-2222-2222-222222222222';
        $captured = [];

        add_action(
            'acx_xmp_refresh_requested',
            static function ($attachmentId, $dispatchedJobId) use (&$captured): void {
                $captured[] = [(int) $attachmentId, (string) $dispatchedJobId];
            },
            10,
            2
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed',
                'type' => 'analyze',
                'media_ids' => [303],
                'progress' => ['completed' => 1, 'total' => 1],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $request->set_param('job_id', $jobId);
        $this->controller->get_job_status($request);

        $this->assertSame([], $captured);
    }

    public function testGetJobStatusReturnsOfflineFailurePayloadWhenProxyUnavailable(): void
    {
        $jobId = '33333333-3333-3333-3333-333333333333';
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new \WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $request->set_param('job_id', $jobId);
        $response = $this->controller->get_job_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $data = $response->get_data();
        $this->assertSame($jobId, $data['id'] ?? null);
        $this->assertSame('failed', $data['status'] ?? null);
        $this->assertSame('analyze', $data['type'] ?? null);
        $this->assertSame('Recognition backend unavailable.', $data['message'] ?? null);
    }

    public function testGetJobStatusTriggersProjectionSyncWhenBackendAwaitsAcknowledgement(): void
    {
        $syncSpy = new AnalysisJobsControllerSyncPullSpy();
        $controller = new AnalysisJobsController(null, $syncSpy);

        $jobId = '55555555-5555-5555-5555-555555555555';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed',
                'type' => 'clustering',
                'snapshot_version' => 22,
                'source_job_id' => $jobId,
                'projection_acknowledged_at' => null,
                'progress' => [
                    'completed' => 2,
                    'total' => 2,
                    'phase' => 'awaiting_projection',
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $request->set_param('job_id', $jobId);
        $response = $controller->get_job_status($request);
        $this->assertInstanceOf(\WP_REST_Response::class, $response);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed',
                'type' => 'clustering',
                'snapshot_version' => 22,
                'source_job_id' => $jobId,
                'projection_acknowledged_at' => null,
                'progress' => [
                    'completed' => 2,
                    'total' => 2,
                    'phase' => 'awaiting_projection',
                ],
            ]),
        ]);
        $controller->get_job_status($request);

        $this->assertTrue($syncSpy->performedBypass);
        $this->assertNotSame('', $syncSpy->tenantIdBypass);
        $this->assertSame(1, $syncSpy->performBypassCount);
    }

    public function testGetJobStatusProjectsInlinePayloadWithoutSnapshotRoundTrip(): void
    {
        $syncSpy = new AnalysisJobsControllerSyncPullSpy();
        $controller = new AnalysisJobsController(null, $syncSpy);

        $jobId = '66666666-6666-6666-6666-666666666666';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed',
                'type' => 'clustering',
                'snapshot_version' => 22,
                'source_job_id' => $jobId,
                'projection_acknowledged_at' => null,
                'projection_payload' => [
                    'tenant_id' => 'tenant-inline',
                    'snapshot_version' => 22,
                    'generated_at' => '2026-04-07T00:00:00Z',
                    'clusters' => [],
                    'members' => [],
                ],
                'progress' => [
                    'completed' => 2,
                    'total' => 2,
                    'phase' => 'awaiting_projection',
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $request->set_param('job_id', $jobId);
        $response = $controller->get_job_status($request);
        $this->assertInstanceOf(\WP_REST_Response::class, $response);

        $this->assertSame(1, $syncSpy->performProjectionPayloadCount);
        $this->assertSame(0, $syncSpy->performBypassCount);
        $this->assertSame($jobId, $syncSpy->projectionPayload['source_job_id'] ?? null);
        $this->assertSame(22, $syncSpy->projectionPayload['snapshot_version'] ?? null);
    }

    public function testGetJobStatusForwardsCheckpointFieldsInProgressResponse(): void
    {
        $jobId = '44444444-4444-4444-4444-444444444444';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id'     => $jobId,
                'status' => 'pending',
                'type'   => 'clustering',
                'progress' => [
                    'completed' => 500,
                    'total'     => 937,
                    'phase'     => 'retrying',
                    'retry_count' => 2,
                    'current_stage' => 'hac_refinement',
                    'last_successful_processed_identities' => 500,
                    'last_error_code' => 'TimeoutError',
                    'clusters_created' => 12,
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $request->set_param('job_id', $jobId);
        $response = $this->controller->get_job_status($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertIsArray($data);
        // The proxy passes through the full backend response without stripping fields.
        $progress = $data['progress'] ?? [];
        $this->assertSame('retrying', $progress['phase'] ?? null);
        $this->assertSame(2, $progress['retry_count'] ?? null);
        $this->assertSame('hac_refinement', $progress['current_stage'] ?? null);
        $this->assertSame(500, $progress['last_successful_processed_identities'] ?? null);
        $this->assertSame('TimeoutError', $progress['last_error_code'] ?? null);
        $this->assertSame(12, $progress['clusters_created'] ?? null);
    }

    public function testBuildStreamProgressPayloadIncludesAllCheckpointFields(): void
    {
		$GLOBALS['__ac_transients']['acx_job_batch_run_test-job-id'] = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

        $progress = [
            'completed'                           => 500,
            'total'                               => 937,
            'phase'                               => 'retrying',
            'retry_count'                         => 3,
            'current_stage'                       => 'hac_refinement',
            'last_successful_processed_identities' => 500,
            'last_error_code'                     => 'TimeoutError',
            'clusters_created'                    => 15,
        ];

        $payload = $this->streamService()->build_stream_progress_payload(
            $progress,
            'test-job-id',
            'clustering_progress',
            'pending'
        );

        $this->assertSame('clustering_progress', $payload['type']);
        $this->assertSame('test-job-id', $payload['job_id']);
        $this->assertSame('pending', $payload['status']);
        $this->assertSame(500, $payload['completed']);
        $this->assertSame(937, $payload['total']);
        $this->assertSame('retrying', $payload['phase']);
        $this->assertSame(3, $payload['retry_count']);
        $this->assertSame('hac_refinement', $payload['current_stage']);
        $this->assertSame(500, $payload['last_successful_processed_identities']);
        $this->assertSame('TimeoutError', $payload['last_error_code']);
        $this->assertSame(15, $payload['clusters_created']);
		$this->assertSame('cccccccc-cccc-4ccc-8ccc-cccccccccccc', $payload['batch_run_id']);
    }

    public function testBuildStreamProgressPayloadOmitsAbsentOptionalFields(): void
    {
        $progress = [
            'completed' => 10,
            'total'     => 100,
        ];

        $payload = $this->streamService()->build_stream_progress_payload(
            $progress,
            'job-xyz',
            'scan_progress',
            'running'
        );

        $this->assertSame('scan_progress', $payload['type']);
        $this->assertSame(10, $payload['completed']);
        $this->assertArrayNotHasKey('phase', $payload);
        $this->assertArrayNotHasKey('retry_count', $payload);
        $this->assertArrayNotHasKey('current_stage', $payload);
        $this->assertArrayNotHasKey('last_successful_processed_identities', $payload);
        $this->assertArrayNotHasKey('last_error_code', $payload);
        $this->assertArrayNotHasKey('clusters_created', $payload);
    }

    private function streamService(): JobProgressStreamService
    {
        $host = $this->controller;
        $batch = new BatchRunService($host);
        $projection = new ProjectionSyncService($host);
        $jobStatus = new JobStatusService($host, $batch, $projection);

        return new JobProgressStreamService($host, $jobStatus, $batch, $projection);
    }

    /**
     * @return array<string,mixed>|null
     */
    private function findRegisteredRoute(string $route, string $method): ?array
    {
        foreach ($GLOBALS['__ac_rest_routes'] as $definition) {
            if (!is_array($definition)) {
                continue;
            }

            if (($definition['route'] ?? null) !== $route) {
                continue;
            }

            $registeredMethod = $definition['args']['methods'] ?? null;
            if ($registeredMethod === $method) {
                return $definition;
            }
        }

        return null;
    }
}

class AnalysisJobsControllerSyncPullSpy implements SyncPullJobInterface
{
    public bool $performedBypass = false;
    public string $tenantIdBypass = '';
    public int $performBypassCount = 0;
    public int $performProjectionPayloadCount = 0;
    /** @var array<string,mixed> */
    public array $projectionPayload = [];

    public function perform(string $tenant_id): SyncPullResult
    {
        return SyncPullResult::ok();
    }

    public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
    {
        $this->performedBypass = true;
        $this->tenantIdBypass = $tenant_id;
        ++$this->performBypassCount;
        return SyncPullResult::ok();
    }

    public function perform_projection_payload(string $tenant_id, array $payload): SyncPullResult
    {
        $this->tenantIdBypass = $tenant_id;
        $this->projectionPayload = $payload;
        ++$this->performProjectionPayloadCount;
        return SyncPullResult::ok();
    }
}
