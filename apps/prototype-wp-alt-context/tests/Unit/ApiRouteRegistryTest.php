<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Api;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\Api
 */
class ApiRouteRegistryTest extends TestCase
{
    /**
     * @param array<int, array<string, mixed>> $routes
     */
    private function assertRouteRegistered(array $routes, string $path, string $method): void
    {
        foreach ($routes as $definition) {
            if ('acx/v1' !== ($definition['namespace'] ?? null) || $path !== ($definition['route'] ?? null)) {
                continue;
            }

            $args = $definition['args'] ?? array();
            if (isset($args['methods']) && $this->methodsContain($args['methods'], $method)) {
                return;
            }

            foreach ($args as $variant) {
                if (is_array($variant) && isset($variant['methods']) && $this->methodsContain($variant['methods'], $method)) {
                    return;
                }
            }
        }

        self::fail(sprintf('Expected %s %s route to be registered.', $method, $path));
    }

    /**
     * @param mixed $methods
     */
    private function methodsContain(mixed $methods, string $expected): bool
    {
        if (is_string($methods)) {
            return $expected === $methods;
        }

        return is_array($methods) && in_array($expected, $methods, true);
    }

    public function testApiBootstrapRegistersPersonMediaAndDelegatedControllerRoutes(): void
    {
        (new Api())->register_routes();

        $routes = $GLOBALS['__ac_rest_routes'];
        self::assertIsArray($routes);

        $expected_routes = array(
            '/roster/persons/(?P<id>[1-9][0-9]*)/media' => array('GET'),
            '/recognition/analyze'                       => array('POST'),
            '/recognition/gpu/status'                    => array('GET'),
            '/public/demo/describe'                     => array('POST'),
            '/settings'                                 => array('GET', 'POST'),
        );

        foreach ($expected_routes as $path => $methods) {
            foreach ($methods as $method) {
                $this->assertRouteRegistered($routes, $path, $method);
            }
        }
    }
}
