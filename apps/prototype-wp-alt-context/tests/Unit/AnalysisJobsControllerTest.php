<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
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
    }

    public function testAnalyzeMediaRejectsMissingPayload(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');

        $result = $this->controller->analyze_media($request);

        $this->assertTrue(is_wp_error($result));
        $this->assertSame('no_media_items', $result->get_error_code());
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
        $this->assertTrue($syncSpy->performedBypass);
        $this->assertNotSame('', $syncSpy->tenantIdBypass);
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

        $method = new \ReflectionMethod($this->controller, 'build_stream_progress_payload');
        $payload = $method->invoke(
            $this->controller,
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
    }

    public function testBuildStreamProgressPayloadOmitsAbsentOptionalFields(): void
    {
        $progress = [
            'completed' => 10,
            'total'     => 100,
        ];

        $method = new \ReflectionMethod($this->controller, 'build_stream_progress_payload');
        $payload = $method->invoke(
            $this->controller,
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

    public function perform(string $tenant_id): SyncPullResult
    {
        return SyncPullResult::ok();
    }

    public function perform_bypass_cooldown(string $tenant_id): SyncPullResult
    {
        $this->performedBypass = true;
        $this->tenantIdBypass = $tenant_id;
        return SyncPullResult::ok();
    }
}
