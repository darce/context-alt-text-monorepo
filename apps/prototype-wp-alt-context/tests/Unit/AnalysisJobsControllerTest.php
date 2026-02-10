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
        $this->setOption('alt_context_recognition_url', 'http://localhost:8000');
        $this->setOption('alt_context_tier', 'free');
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
