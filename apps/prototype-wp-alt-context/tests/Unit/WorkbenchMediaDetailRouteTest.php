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
    public function testRegisterRoutesAdvertisesWorkbenchMediaDetailMaxItems(): void
    {
        $api = new Api();
        $api->register_routes();

        $route = $this->findRegisteredRoute('/workbench/media/detail', 'GET');

        $this->assertNotNull($route);
        $this->assertArrayHasKey('args', $route['args']);
        $this->assertArrayHasKey('ids', $route['args']['args']);
        $this->assertSame(100, $route['args']['args']['ids']['maxItems'] ?? null);
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