<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once dirname(__DIR__, 2) . '/src/api/class-proxy-routes.php';
require_once dirname(__DIR__, 2) . '/src/api/class-retention-controller.php';

use AltContext\Api\ProxyRoutes;
use AltContext\Api\RetentionController;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

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
            self::assertArrayHasKey('route_level_not_found', $route);
            self::assertIsBool($route['route_level_not_found']);

            $method = (string) $route['method'];
            $path = (string) $route['path'];
            self::assertSame(
                in_array(
                    $path,
                    array(
                        ProxyRoutes::GET_RETENTION_EXPORT_STATUS_PATH,
                        ProxyRoutes::GET_RETENTION_EXPORT_DATA_PATH,
                    ),
                    true
                ),
                $route['route_level_not_found'],
                "Unexpected route-level 404 contract: {$method} {$path}"
            );
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

    public function testRetentionHandlersProxyToDeclaredRoutes(): void
    {
        $declared_routes = ProxyRoutes::all();
        // GET and PATCH share /recognition/retention/policy, so the declared route must be
        // matched on method AND path or the first path hit wins and the assertion is vacuous.
        $expected_call = static function (
            string $method,
            string $declared_path,
            ?string $emitted_path = null
        ) use ($declared_routes): array {
            foreach ($declared_routes as $route) {
                if ($route['method'] === $method && $route['path'] === $declared_path) {
                    return array($route['method'], $emitted_path ?? $declared_path);
                }
            }

            throw new \LogicException(
                sprintf('Expected route %s %s is missing from ProxyRoutes.', $method, $declared_path)
            );
        };

        $job_id = 'job/id with space';
        $normalized_job_id = sanitize_key($job_id);
        $import_request = new WP_REST_Request('POST', '/acx/v1/retention/import');
        $import_request->set_body_params(array('data' => array()));

        $operations = array(
            array(
                'name' => 'get_status',
                'handler' => 'get_status',
                'request' => new WP_REST_Request('GET', '/acx/v1/retention/status'),
                'expected' => array(
                    $expected_call('GET', ProxyRoutes::GET_RETENTION_POLICY_PATH),
                    $expected_call('GET', ProxyRoutes::GET_RETENTION_AUDIT_PATH),
                ),
            ),
            array(
                'name' => 'update_policy',
                'handler' => 'update_policy',
                'request' => new WP_REST_Request(
                    'PATCH',
                    '/acx/v1/retention/policy',
                    array('retention_mode' => 'dispose_after_ack')
                ),
                'expected' => array(
                    $expected_call('PATCH', ProxyRoutes::PATCH_RETENTION_POLICY_PATH),
                ),
            ),
            array(
                'name' => 'apply_preset',
                'handler' => 'apply_preset',
                'request' => new WP_REST_Request(
                    'POST',
                    '/acx/v1/retention/policy/preset',
                    array('preset' => 'dispose_after_ack')
                ),
                'expected' => array(
                    $expected_call('POST', ProxyRoutes::POST_RETENTION_POLICY_PRESET_PATH),
                ),
            ),
            array(
                'name' => 'trigger_export',
                'handler' => 'trigger_export',
                'request' => new WP_REST_Request('POST', '/acx/v1/retention/export'),
                'expected' => array(
                    $expected_call('POST', ProxyRoutes::POST_RETENTION_EXPORT_PATH),
                ),
            ),
            array(
                'name' => 'get_export_job_status',
                'handler' => 'get_export_job_status',
                'request' => new WP_REST_Request(
                    'GET',
                    '/acx/v1/retention/export/' . $job_id . '/status',
                    array('job_id' => $job_id)
                ),
                'expected' => array(
                    $expected_call(
                        'GET',
                        ProxyRoutes::GET_RETENTION_EXPORT_STATUS_PATH,
                        ProxyRoutes::export_job_status_path($normalized_job_id)
                    ),
                ),
            ),
            array(
                'name' => 'get_export_job_data',
                'handler' => 'get_export_job_data',
                'request' => new WP_REST_Request(
                    'GET',
                    '/acx/v1/retention/export/' . $job_id . '/data',
                    array('job_id' => $job_id)
                ),
                'expected' => array(
                    $expected_call(
                        'GET',
                        ProxyRoutes::GET_RETENTION_EXPORT_DATA_PATH,
                        ProxyRoutes::export_job_data_path($normalized_job_id)
                    ),
                ),
            ),
            array(
                'name' => 'trigger_purge',
                'handler' => 'trigger_purge',
                'request' => new WP_REST_Request(
                    'POST',
                    '/acx/v1/retention/purge',
                    array('confirm' => true, 'scope' => 'disposed')
                ),
                'expected' => array(
                    $expected_call('POST', ProxyRoutes::POST_RETENTION_PURGE_PATH),
                ),
            ),
            array(
                'name' => 'trigger_import',
                'handler' => 'trigger_import',
                'request' => $import_request,
                'expected' => array(
                    $expected_call('POST', ProxyRoutes::POST_RETENTION_IMPORT_PATH),
                ),
            ),
            array(
                'name' => 'list_audit_events',
                'handler' => 'list_audit_events',
                'request' => new WP_REST_Request(
                    'GET',
                    '/acx/v1/retention/audit',
                    array('limit' => 5, 'offset' => 10, 'event_type' => 'policy_updated')
                ),
                'expected' => array(
                    $expected_call('GET', ProxyRoutes::GET_RETENTION_AUDIT_PATH),
                ),
            ),
        );

        $controller = new class() extends RetentionController {
            /** @var list<array{0: string, 1: string}> */
            public array $proxy_calls = array();

            protected function proxy_request(
                string $method,
                string $path,
                array $body = array(),
                array $query = array(),
                string $request_class = 'auto',
                string $body_kind = 'json',
                ?int $max_body_bytes = null
            ): WP_REST_Response|WP_Error {
                $this->proxy_calls[] = array($method, $path);

                return new WP_REST_Response(array(), 500);
            }
        };

        foreach ($operations as $operation) {
            $calls_before = count($controller->proxy_calls);
            $handler = $operation['handler'];
            $controller->{$handler}($operation['request']);

            self::assertSame(
                $operation['expected'],
                array_slice($controller->proxy_calls, $calls_before),
                $operation['name'] . ' emitted unexpected proxy route calls.'
            );
        }
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
