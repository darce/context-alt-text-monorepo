<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Api\AnalysisJobsHostInterface;
use AltContext\Api\Services\BatchRunService;
use AltContext\Api\Services\JobProgressStreamService;
use AltContext\Api\Services\JobStatusService;
use AltContext\Api\Services\ProjectionSyncService;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

/**
 * Golden-JSON + SSE characterization safety net for all 8 analysis-jobs routes.
 *
 * Shared-helper ownership (Slice 1 lock):
 * - record_observed_job_status_from_response: owned by JobStatusService (Slice 3)
 * - validate_media_ids: controller-resident validate_callback (PA-02)
 * - can_manage_recognition: inherited from AbstractRecognitionProxyController
 *
 * @covers \AltContext\Api\AnalysisJobsController
 */
class AnalysisJobsControllerCharacterizationTest extends TestCase
{
    private const FIXTURE_ROOT = __DIR__ . '/../fixtures/analysis-jobs';

    private AnalysisJobsController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__ac_connection_aborted_call_count'] = 0;
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_tier', 'free');
        $this->controller = new AnalysisJobsController();
    }

    public function testControllerImplementsAnalysisJobsHostInterface(): void
    {
        $this->assertInstanceOf(AnalysisJobsHostInterface::class, $this->controller);
    }

    public function testAnalyzeMediaGolden(): void
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

        $this->assertGolden('analyze_media', $response, [
            'http_call_count' => count($this->getHttpCalls()),
            'job_batch_run_transient' => $GLOBALS['__ac_transients']['acx_job_batch_run_' . $jobId] ?? null,
            'projection_sync_performed' => false,
        ]);
    }

    public function testGetRecentBatchRunsGolden(): void
    {
        $runId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        $failedRunId = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
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

        $this->assertGolden('get_recent_batch_runs', $response, [
            'item_run_ids' => array_map(
                static fn(array $item): string => (string) ($item['run_id'] ?? ''),
                $response->get_data()['items'] ?? []
            ),
        ]);
    }

    public function testGetBatchRunStatusGolden(): void
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
        $this->controller->get_job_status($jobStatusRequest);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $request->set_param('run_id', $runId);

        $response = $this->controller->get_batch_run_status($request);

        $this->assertGolden('get_batch_run_status', $response, [
            'terminal_state' => $response->get_data()['terminal_state'] ?? null,
            'child_job_ids' => $response->get_data()['child_job_ids'] ?? null,
        ]);
    }

    public function testRecordClientBatchFailureGolden(): void
    {
        $runId = 'f1f1f1f1-f1f1-4f1f-8f1f-f1f1f1f1f1f1';

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/batch-runs/' . $runId . '/client-failures');
        $request->set_param('run_id', $runId);
        $request->set_param('batch_index', 1);
        $request->set_param('submitted_total', 4);
        $request->set_param('media_ids', [601, 602]);

        $response = $this->controller->record_client_batch_failure($request);

        $statusRequest = new WP_REST_Request('GET', '/acx/v1/recognition/batch-runs/' . $runId);
        $statusRequest->set_param('run_id', $runId);
        $statusResponse = $this->controller->get_batch_run_status($statusRequest);
        $statusData = $statusResponse instanceof WP_REST_Response ? $statusResponse->get_data() : [];

        $this->assertGolden('record_client_batch_failure', $response, [
            'failed_total' => $statusData['failed_total'] ?? null,
            'failed_batches_count' => count($statusData['failed_batches'] ?? []),
        ]);
    }

    public function testGetJobStatusGolden(): void
    {
        $runId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
        $jobId = '22222222-2222-2222-2222-222222222222';

        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

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
        $analyzeRequest->set_param('media_ids', [101]);
        $this->controller->analyze_media($analyzeRequest);

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed',
                'type' => 'analyze',
                'progress' => ['completed' => 1, 'total' => 1],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $request->set_param('job_id', $jobId);

        $response = $this->controller->get_job_status($request);

        $this->assertGolden('get_job_status', $response, [
            'http_call_count' => 1,
            'projection_sync_performed' => false,
        ]);
    }

    public function testGetJobStatusOfflineGolden(): void
    {
        $jobId = '33333333-3333-3333-3333-333333333333';
        $this->queueHttpResponse(new WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new WP_Error('proxy_failed', 'Proxy failure.'));
        $this->queueHttpResponse(new WP_Error('proxy_failed', 'Proxy failure.'));

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/jobs/' . $jobId);
        $request->set_param('job_id', $jobId);

        $response = $this->controller->get_job_status($request);

        $this->assertGolden('get_job_status_offline', $response, [
            'http_call_count' => 3,
        ]);
    }

    public function testCancelJobGolden(): void
    {
        $jobId = '44444444-4444-4444-4444-444444444444';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'cancelled',
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/' . $jobId . '/cancel');
        $request->set_param('job_id', $jobId);

        $response = $this->controller->cancel_job($request);

        $this->assertGolden('cancel_job', $response, [
            'http_call_count' => 1,
            'http_path' => '/recognition/jobs/' . $jobId . '/cancel',
        ]);
    }

    public function testAcknowledgeProjectionGolden(): void
    {
        $jobId = '55555555-5555-5555-5555-555555555555';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'id' => $jobId,
                'status' => 'completed',
                'projection_acknowledged_at' => '2026-06-08T12:00:00+00:00',
            ]),
        ]);

        $request = new WP_REST_Request('POST', '/acx/v1/recognition/jobs/' . $jobId . '/acknowledge-projection');
        $request->set_param('job_id', $jobId);
        $request->set_body_params([
            'snapshot_version' => 22,
            'snapshot_generation_id' => 'gen-abc',
        ]);

        $response = $this->controller->acknowledge_projection($request);

        $this->assertGolden('acknowledge_projection', $response, [
            'http_call_count' => 1,
            'http_path' => '/recognition/jobs/' . $jobId . '/acknowledge-projection',
        ]);
    }

    public function testBuildStreamProgressPayloadGoldenCheckpointFields(): void
    {
        $GLOBALS['__ac_transients']['acx_job_batch_run_test-job-id'] = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

        $progress = [
            'completed' => 500,
            'total' => 937,
            'phase' => 'retrying',
            'retry_count' => 3,
            'current_stage' => 'hac_refinement',
            'last_successful_processed_identities' => 500,
            'last_error_code' => 'TimeoutError',
            'clusters_created' => 15,
        ];

        $payload = $this->streamService()->build_stream_progress_payload(
            $progress,
            'test-job-id',
            'clustering_progress',
            'pending'
        );

        $this->assertGoldenPayload('build_stream_progress_payload_checkpoint', $payload);
    }

    public function testBuildStreamProgressPayloadGoldenMinimal(): void
    {
        $progress = [
            'completed' => 10,
            'total' => 100,
        ];

        $payload = $this->streamService()->build_stream_progress_payload(
            $progress,
            'job-xyz',
            'scan_progress',
            'running'
        );

        $this->assertGoldenPayload('build_stream_progress_payload_minimal', $payload);
    }

    public function testStreamJobProgressBoundedEmitLoopGolden(): void
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

        $output = '';
        ob_start();
        try {
            $this->characterizationStreamService()->stream_job_progress($request);
            $output = (string) ob_get_clean();
        } catch (JobProgressStreamTerminated) {
            $output = (string) ob_get_clean();
        }

        $this->assertGoldenStreamFrames('stream_job_progress_completed', $output);
    }

    /**
     * @param array<string,mixed> $sideEffects
     */
    private function assertGolden(string $handler, WP_REST_Response|WP_Error $response, array $sideEffects): void
    {
        $fixtureDir = self::FIXTURE_ROOT . '/' . $handler;
        $responseFixture = $fixtureDir . '/response.json';
        $sideEffectsFixture = $fixtureDir . '/side-effects.json';

        $actualResponse = $this->serializeResponse($response);
        $actualSideEffects = $this->serializeSideEffects($sideEffects);

        if (getenv('UPDATE_ANALYSIS_JOBS_FIXTURES') === '1') {
            if (! is_dir($fixtureDir)) {
                mkdir($fixtureDir, 0777, true);
            }
            file_put_contents($responseFixture, $actualResponse);
            file_put_contents($sideEffectsFixture, $actualSideEffects);
        }

        $this->assertFileExists($responseFixture, sprintf('Missing golden response fixture for %s.', $handler));
        $this->assertFileExists($sideEffectsFixture, sprintf('Missing golden side-effects fixture for %s.', $handler));

        $expectedResponse = (string) file_get_contents($responseFixture);
        $expectedSideEffects = (string) file_get_contents($sideEffectsFixture);

        $this->assertSame($expectedResponse, $actualResponse, sprintf('Golden response drift for %s.', $handler));
        $this->assertSame($expectedSideEffects, $actualSideEffects, sprintf('Golden side-effects drift for %s.', $handler));
    }

    /**
     * @param array<string,mixed> $payload
     */
    private function assertGoldenPayload(string $handler, array $payload): void
    {
        $fixture = self::FIXTURE_ROOT . '/' . $handler . '/payload.json';
        $actual = $this->serializePayload($payload);

        if (getenv('UPDATE_ANALYSIS_JOBS_FIXTURES') === '1') {
            $dir = dirname($fixture);
            if (! is_dir($dir)) {
                mkdir($dir, 0777, true);
            }
            file_put_contents($fixture, $actual);
        }

        $this->assertFileExists($fixture, sprintf('Missing golden payload fixture for %s.', $handler));
        $expected = (string) file_get_contents($fixture);
        $this->assertSame($expected, $actual, sprintf('Golden payload drift for %s.', $handler));
    }

    private function assertGoldenStreamFrames(string $handler, string $output): void
    {
        $fixture = self::FIXTURE_ROOT . '/' . $handler . '/frames.txt';
        $normalized = $this->normalizeStreamOutput($output);

        if (getenv('UPDATE_ANALYSIS_JOBS_FIXTURES') === '1') {
            $dir = dirname($fixture);
            if (! is_dir($dir)) {
                mkdir($dir, 0777, true);
            }
            file_put_contents($fixture, $normalized);
        }

        $this->assertFileExists($fixture, sprintf('Missing golden stream fixture for %s.', $handler));
        $expected = (string) file_get_contents($fixture);
        $this->assertSame($expected, $normalized, sprintf('Golden stream drift for %s.', $handler));
    }

    private function serializeResponse(WP_REST_Response|WP_Error $response): string
    {
        if (is_wp_error($response)) {
            $payload = [
                'type' => 'error',
                'code' => $response->get_error_code(),
                'message' => $response->get_error_message(),
                'data' => $response->get_error_data(),
            ];
        } else {
            $payload = [
                'type' => 'response',
                'status' => $response->get_status(),
                'data' => $this->normalizeVolatileFields($response->get_data()),
            ];
        }

        $encoded = wp_json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $this->assertIsString($encoded);

        return $encoded;
    }

    /**
     * @param array<string,mixed> $sideEffects
     */
    private function serializeSideEffects(array $sideEffects): string
    {
        $encoded = wp_json_encode(
            $this->normalizeVolatileFields($sideEffects),
            JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
        );
        $this->assertIsString($encoded);

        return $encoded;
    }

    /**
     * @param array<string,mixed> $payload
     */
    private function serializePayload(array $payload): string
    {
        $encoded = wp_json_encode(
            $this->normalizeVolatileFields($payload),
            JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
        );
        $this->assertIsString($encoded);

        return $encoded;
    }

    private function normalizeStreamOutput(string $output): string
    {
        return str_replace("\r\n", "\n", trim($output)) . "\n";
    }

    /**
     * @return mixed
     */
    private function normalizeVolatileFields(mixed $value): mixed
    {
        if (! is_array($value)) {
            if (is_string($value) && $this->isVolatileTimestamp($value)) {
                return '__MASKED_TIMESTAMP__';
            }

            return $value;
        }

        $normalized = [];
        foreach ($value as $key => $item) {
            if (is_string($key) && $this->isVolatileFieldName($key)) {
                $normalized[$key] = '__MASKED_TIMESTAMP__';
                continue;
            }

            $normalized[$key] = $this->normalizeVolatileFields($item);
        }

        return $normalized;
    }

    private function isVolatileFieldName(string $key): bool
    {
        return in_array(
            $key,
            [
                'created_at',
                'updated_at',
                'started_at',
                'finished_at',
                'last_status_observed_at',
            ],
            true
        );
    }

    private function isVolatileTimestamp(string $value): bool
    {
        return (bool) preg_match(
            '/^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$/',
            $value
        );
    }

    private function streamService(): JobProgressStreamService
    {
        $host = $this->controller;
        $batch = new BatchRunService($host);
        $projection = new ProjectionSyncService($host);
        $jobStatus = new JobStatusService($host, $batch, $projection);

        return new JobProgressStreamService($host, $jobStatus, $batch, $projection);
    }

    private function characterizationStreamService(): CharacterizationStreamService
    {
        $host = $this->controller;
        $batch = new BatchRunService($host);
        $projection = new ProjectionSyncService($host);
        $jobStatus = new JobStatusService($host, $batch, $projection);
        $batch->wire_job_status_service($jobStatus);

        return new CharacterizationStreamService($host, $jobStatus, $batch, $projection);
    }
}

class CharacterizationStreamService extends JobProgressStreamService
{
    protected function prepare_stream_output_buffers(): void
    {
    }

    protected function terminate_job_progress_stream(): never
    {
        throw new JobProgressStreamTerminated();
    }
}

final class JobProgressStreamTerminated extends \RuntimeException
{
}
