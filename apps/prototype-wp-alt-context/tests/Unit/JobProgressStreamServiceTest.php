<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Api\Services\BatchRunService;
use AltContext\Api\Services\JobProgressStreamService;
use AltContext\Api\Services\JobStreamErrorCode;
use AltContext\Api\Services\JobStatusService;
use AltContext\Api\Services\ProjectionSyncService;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\Services\JobProgressStreamService
 */
class JobProgressStreamServiceTest extends TestCase
{
    private TestableJobProgressStreamService $service;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $host = new AnalysisJobsController();
        $batch = new BatchRunService($host);
        $projection = new ProjectionSyncService($host);
        $jobStatus = new JobStatusService($host, $batch, $projection);
        $this->service = new TestableJobProgressStreamService($host, $jobStatus, $batch, $projection);
    }

    public function testStreamJobProgressRejectsMissingJobId(): void
    {
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs//stream');

        $result = $this->service->stream_job_progress($request);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('missing_job_id', $result->get_error_code());
    }

    public function testStreamJobProgressEmitsErrorFrameOnProxyFailure(): void
    {
        $jobId = '77777777-7777-7777-7777-777777777777';
        $this->queueHttpResponse(new WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId . '/stream');
        $request->set_param('job_id', $jobId);

        $output = $this->captureStreamOutput(function () use ($request): void {
            $this->service->stream_job_progress($request);
        });

        $this->assertStringContainsString("event: error\n", $output);
        $this->assertStringContainsString('"code":"proxy_error"', $output);
        $this->assertStringContainsString('Proxy failure.', $output);
    }

    public function testStreamJobProgressEmitsTypedNotFoundErrorFrame(): void
    {
        $jobId = '77777777-7777-7777-7777-777777777778';
        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'localized copy']),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId . '/stream');
        $request->set_param('job_id', $jobId);

        $output = $this->captureStreamOutput(function () use ($request): void {
            $this->service->stream_job_progress($request);
        });

        $this->assertStringContainsString("event: error\n", $output);
        $this->assertStringContainsString('"code":"job_not_found"', $output);
    }

    public function testStreamJobProgressEmitsTypedInvalidResponseErrorFrame(): void
    {
        $jobId = '77777777-7777-7777-7777-777777777779';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode('not-an-object'),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId . '/stream');
        $request->set_param('job_id', $jobId);

        $output = $this->captureStreamOutput(function () use ($request): void {
            $this->service->stream_job_progress($request);
        });

        $this->assertStringContainsString("event: error\n", $output);
        $this->assertStringContainsString('"code":"invalid_job_response"', $output);
    }

    public function testJobStreamErrorCodeIsTheClosedWireVocabulary(): void
    {
        $this->assertSame(
            ['proxy_error', 'job_not_found', 'unexpected_response', 'invalid_job_response'],
            JobStreamErrorCode::cases()
        );
        // String constants preserve the plugin's declared PHP 8.0 floor.
        // TEST-15 (/home/gate/canon/engineering.md:396): this goes red if a
        // PHP 8.1 enum replaces the PHP 8.0-compatible vocabulary again.
        $this->assertSame('job_not_found', JobStreamErrorCode::JOB_NOT_FOUND);
        $this->assertSame(
            array_values((new \ReflectionClass(JobStreamErrorCode::class))->getConstants()),
            JobStreamErrorCode::cases()
        );
    }

    public function testStreamJobProgressEmitsProgressAndDoneForCompletedJob(): void
    {
        $jobId = '66666666-6666-6666-6666-666666666666';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed',
                'type' => 'analyze',
                'progress' => ['completed' => 2, 'total' => 2],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId . '/stream');
        $request->set_param('job_id', $jobId);

        $output = $this->captureStreamOutput(function () use ($request): void {
            $this->service->stream_job_progress($request);
        });

        $this->assertStringContainsString("event: progress\n", $output);
        $this->assertStringContainsString("event: done\n", $output);
        $this->assertStringContainsString('"status":"completed"', $output);
    }

    public function testStreamJobProgressEmitsDoneForCompletedWithErrorsJob(): void
    {
        $jobId = '55555555-5555-5555-5555-555555555555';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed_with_errors',
                'type' => 'analyze',
                'progress' => ['completed' => 1, 'total' => 2],
                'progress_envelope' => [
                    'job_id' => $jobId,
                    'status' => 'completed_with_errors',
                    'phase' => 'complete',
                    'items_total' => 2,
                    'items_done' => 1,
                    'items_failed' => 1,
                    'failure_reason' => 'one or more items failed',
                    'updated_at' => '2026-06-11T12:00:00+00:00',
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId . '/stream');
        $request->set_param('job_id', $jobId);

        $output = $this->captureStreamOutput(function () use ($request): void {
            $this->service->stream_job_progress($request);
        });

        $this->assertStringContainsString("event: done\n", $output);
        $this->assertStringContainsString('"status":"completed_with_errors"', $output);
    }

    public function testStreamJobProgressEmitsDoneForFailedJob(): void
    {
        $jobId = '44444444-4444-4444-4444-444444444444';
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'failed',
                'type' => 'analyze',
                'progress' => ['completed' => 0, 'total' => 2],
                'progress_envelope' => [
                    'job_id' => $jobId,
                    'status' => 'failed',
                    'phase' => 'failed',
                    'items_total' => 2,
                    'items_done' => 0,
                    'items_failed' => 2,
                    'failure_reason' => 'stalled',
                    'updated_at' => '2026-06-11T12:15:00+00:00',
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId . '/stream');
        $request->set_param('job_id', $jobId);

        $output = $this->captureStreamOutput(function () use ($request): void {
            $this->service->stream_job_progress($request);
        });

        $this->assertStringContainsString("event: done\n", $output);
        $this->assertStringContainsString('"status":"failed"', $output);
        $this->assertStringContainsString('"failure_reason":"stalled"', $output);
    }

    public function testBuildStreamProgressPayloadIncludesBatchRunIdWhenTracked(): void
    {
        $jobId = '88888888-8888-8888-8888-888888888888';
        $runId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';

        add_filter('acx_recognition_transport', static fn(string $current): string => 'url');
        $GLOBALS['__ac_attachment_urls'][401] = 'http://example.test/media/401.jpg';

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
        (new AnalysisJobsController())->analyze_media($analyzeRequest);

        $payload = $this->service->build_stream_progress_payload(
            ['completed' => 1, 'total' => 1],
            $jobId,
            'scan_progress',
            'running'
        );

        $this->assertSame($runId, $payload['batch_run_id']);
    }

    /**
     * @param callable():void $stream
     */
    private function captureStreamOutput(callable $stream): string
    {
        ob_start();
        try {
            $stream();
        } catch (JobProgressStreamTestTerminated $terminated) {
            // Expected control-flow exit from the testable stream service.
            unset($terminated);
        }
        return (string) ob_get_clean();
    }
}

class TestableJobProgressStreamService extends JobProgressStreamService
{
    protected function prepare_stream_output_buffers(): void
    {
    }

    protected function flush_stream_output(): void
    {
    }

    protected function terminate_job_progress_stream(): never
    {
        throw new JobProgressStreamTestTerminated();
    }
}

final class JobProgressStreamTestTerminated extends \RuntimeException
{
}
