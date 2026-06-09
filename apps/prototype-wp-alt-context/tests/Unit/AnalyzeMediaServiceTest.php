<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AnalysisJobsController;
use AltContext\Api\Services\AnalyzeMediaService;
use AltContext\Api\Services\BatchRunService;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\Services\AnalyzeMediaService
 */
class AnalyzeMediaServiceTest extends TestCase
{
    private AnalyzeMediaService $service;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $host = new AnalysisJobsController();
        $this->service = new AnalyzeMediaService($host, new BatchRunService($host));
    }

    public function testAnalyzeMediaRejectsMissingPayload(): void
    {
        $request = new WP_REST_Request('POST', '/acx/v1/recognition/analyze');
        $controller = new AnalysisJobsController();

        $result = $this->service->analyze_media($request, array($controller, 'validate_media_ids'));

        $this->assertTrue(is_wp_error($result));
        $this->assertSame('no_media_items', $result->get_error_code());
    }
}
