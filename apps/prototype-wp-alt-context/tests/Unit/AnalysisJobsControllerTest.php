<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
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

    public function testGetJobStatusDispatchesRecognitionCompleteOnlyOncePerJob(): void
    {
        $jobId = '11111111-1111-1111-1111-111111111111';
        $captured = [];

        add_action(
            'acx_recognition_complete',
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

        $this->assertCount(2, $captured);
        $this->assertSame([[101, $jobId], [202, $jobId]], $captured);
    }

    public function testGetJobStatusDispatchesRecognitionCompleteFromJobPayloadMediaIds(): void
    {
        $jobId = '22222222-2222-2222-2222-222222222222';
        $captured = [];

        add_action(
            'acx_recognition_complete',
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

        $this->assertSame([[303, $jobId]], $captured);
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
