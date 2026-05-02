<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Api
 */
class WorkbenchMediaDetailRouteTest extends TestCase
{
    public function testRegisteredRouteDefersOverLimitRequestsToControllerTruncation(): void
    {
        $api = new Api();
        $api->register_routes();

        $route = $this->findRegisteredRoute('/workbench/media/detail', 'GET');
        $ids = range(1, 101);

        $this->assertNotNull($route);
        $this->assertArrayHasKey('args', $route['args']);
        $this->assertArrayHasKey('ids', $route['args']['args']);
        $this->assertArrayNotHasKey('maxItems', $route['args']['args']['ids']);

        $request = new \WP_REST_Request('GET', '/acx/v1/workbench/media/detail');
        $request->set_param('ids[]', $ids);

        $callback = $route['args']['callback'] ?? null;
        $this->assertIsCallable($callback);

        $response = $callback($request);
        $this->assertInstanceOf(\WP_REST_Response::class, $response);

        $data = $response->get_data();
        $this->assertSame(100, $data['limit'] ?? null);
        $this->assertSame(101, $data['total'] ?? null);
        $this->assertTrue($data['truncated'] ?? false);
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
