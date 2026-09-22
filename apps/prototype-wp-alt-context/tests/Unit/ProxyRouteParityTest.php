<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once dirname(__DIR__, 2) . '/src/api/class-proxy-routes.php';

use AltContext\Api\ProxyRoutes;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\ProxyRoutes
 */
final class ProxyRouteParityTest extends TestCase
{
    public function testEveryDeclaredRetentionRouteMatchesTheCheckedInManifest(): void
    {
        $manifest = $this->manifest();

        foreach (ProxyRoutes::all() as $route) {
            self::assertArrayHasKey('method', $route);
            self::assertArrayHasKey('path', $route);
            self::assertArrayHasKey('kind', $route);

            $method = (string) $route['method'];
            $path = (string) $route['path'];
            $expected_kind = str_contains($path, '{param_0}')
                ? ProxyRoutes::ROUTE_KIND_PARAMETERIZED
                : ProxyRoutes::ROUTE_KIND_STATIC;
            self::assertSame($expected_kind, $route['kind'], "Route kind does not match path shape: {$method} {$path}");
            self::assertTrue(
                $this->manifestContains($manifest, $method, $path),
                sprintf('Proxy route is missing from the manifest: %s %s', $method, $path)
            );
        }
    }

    public function testEveryManifestRetentionRouteIsDeclaredByProxyRoutes(): void
    {
        $manifest = $this->manifest();

        foreach ($manifest as $entry) {
            $path = (string) ($entry['path'] ?? '');
            if (!str_starts_with($path, '/recognition/retention')) {
                continue;
            }

            $method = (string) ($entry['method'] ?? '');
            self::assertTrue(
                $this->manifestContains(ProxyRoutes::all(), $method, $path),
                sprintf('Manifest retention route is not declared by ProxyRoutes: %s %s', $method, $path)
            );
        }
    }

    public function testParameterizedExportBuildersRawUrlEncodeJobIds(): void
    {
        self::assertSame(
            '/recognition/retention/export/job%2Fid%20with%20space/status',
            ProxyRoutes::export_job_status_path('job/id with space')
        );
        self::assertSame(
            '/recognition/retention/export/job%2Fid%20with%20space/data',
            ProxyRoutes::export_job_data_path('job/id with space')
        );
    }

    /**
     * @return list<array{method: string, path: string}>
     */
    private function manifest(): array
    {
        $contents = file_get_contents(__DIR__ . '/../fixtures/api-route-manifest.json');
        self::assertNotFalse($contents, 'The checked-in API route manifest must be readable.');

        $manifest = json_decode((string) $contents, true, 512, JSON_THROW_ON_ERROR);
        self::assertIsArray($manifest);
        self::assertArrayHasKey('routes', $manifest);
        self::assertIsArray($manifest['routes']);

        return $manifest['routes'];
    }

    /**
     * @param array<int, array<string, mixed>> $routes
     */
    private function manifestContains(array $routes, string $method, string $path): bool
    {
        foreach ($routes as $route) {
            if (($route['method'] ?? null) === $method && ($route['path'] ?? null) === $path) {
                return true;
            }
        }

        return false;
    }
}
