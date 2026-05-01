<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ProbeOutcome;
use AltContext\Api\SettingsController;
use AltContext\Api\TenantIdentity;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\SettingsController
 */
class SettingsControllerTest extends TestCase
{
    private SettingsController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->controller = new SettingsController();
    }

    public function testRegisterRoutesIncludesSettingsEndpoints(): void
    {
        $this->controller->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains('/settings', $routes);
        $this->assertContains('/settings/test', $routes);
    }

    // --- GET /settings ---

    public function testGetSettingsReturnsDefaultSourceWhenNothingConfigured(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_api_key', '');

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $data = $response->get_data();
        $this->assertSame('', $data['url']);
        $this->assertSame('default', $data['url_source']);
        $this->assertSame('local', $data['recognition_source']);
        $this->assertSame('default', $data['recognition_source_source']);
        $this->assertFalse($data['api_key_set']);
        $this->assertSame('', $data['api_key_last4']);
        $this->assertSame('default', $data['key_source']);
    }

    public function testGetSettingsReturnsOptionSourceWhenOptionSet(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_url', 'https://api.example.com');
        $this->setOption('acx_recognition_api_key', 'sk-test-key-abcdef1234');

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $data = $response->get_data();
        $this->assertSame('https://api.example.com', $data['url']);
        $this->assertSame('option', $data['url_source']);
        $this->assertTrue($data['api_key_set']);
        $this->assertSame('****1234', $data['api_key_last4']);
        $this->assertSame('option', $data['key_source']);
    }

    public function testGetSettingsReturnsFilterSourceWhenFilterProvides(): void
    {
        $this->setUserCapability('manage_options', true);
        add_filter('acx_recognition_base_url', static fn () => 'https://filter.example.com');

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $data = $response->get_data();
        $this->assertSame('https://filter.example.com', $data['url']);
        $this->assertSame('filter', $data['url_source']);
    }

    public function testGetSettingsMasksShortApiKey(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_api_key', 'abc');

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $data = $response->get_data();
        $this->assertTrue($data['api_key_set']);
        $this->assertSame('****', $data['api_key_last4']);
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testGetSettingsReturnsConstantSourceWhenConstantDefined(): void
    {
        require_once __DIR__ . '/../bootstrap.php';
        $this->resetGlobalState();

        define('ACX_RECOGNITION_URL', 'https://const.example.com');
        define('ACX_RECOGNITION_API_KEY', 'const-key-abcdefgh');
        // Also set option — constant should take precedence
        $this->setOption('acx_recognition_url', 'https://option.example.com');

        $controller = new SettingsController();
        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $controller->get_settings($request);

        $data = $response->get_data();
        $this->assertSame('https://const.example.com', $data['url']);
        $this->assertSame('constant', $data['url_source']);
        $this->assertSame('constant', $data['key_source']);
        $this->assertSame('****efgh', $data['api_key_last4']);
    }

    // --- POST /settings ---

    public function testSaveSettingsWritesUrlAndKeyToOptions(): void
    {
        $this->setUserCapability('manage_options', true);

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params([
            'recognition_source' => 'local',
            'url' => 'https://new-api.example.com',
            'api_key' => 'new-key-12345678',
        ]);

        $response = $this->controller->save_settings($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('ok', $data['result']);
        $this->assertContains('recognition_source', $data['saved']);
        $this->assertContains('url', $data['saved']);
        $this->assertContains('api_key', $data['saved']);

        $this->assertSame('local', get_option('acx_recognition_source'));
        $this->assertSame('https://new-api.example.com', get_option('acx_recognition_url'));
        $this->assertSame('new-key-12345678', get_option('acx_recognition_api_key'));
    }

    public function testSaveSettingsRejectsInvalidUrl(): void
    {
        $this->setUserCapability('manage_options', true);

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params([
            'url' => 'not-a-url',
        ]);

        $response = $this->controller->save_settings($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_url', $response->get_error_code());
    }

    public function testSaveSettingsAcceptsPartialUpdate(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_url', 'https://old.example.com');

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params([
            'api_key' => 'only-key-update',
        ]);

        $response = $this->controller->save_settings($request);

        $data = $response->get_data();
        $this->assertContains('api_key', $data['saved']);
        $this->assertNotContains('url', $data['saved']);
        $this->assertSame('https://old.example.com', get_option('acx_recognition_url'));
    }

    // --- POST /settings/test (probe dispatch) ---

    public function testProbeDispatchHitsAuthenticatedPoolEndpoint(): void
    {
        $this->configureProbe();
        $this->queueHttpResponse($this->buildOkResponse());

        $response = $this->controller->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'));
        $data     = $response->get_data();

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringEndsWith('/health/detailed', $calls[0]['url']);
        $this->assertStringNotContainsString('/recognition/health/pool', $calls[0]['url']);
        $this->assertSame('test-key', $calls[0]['args']['headers']['X-API-Key'] ?? null);
        $this->assertSame(
            TenantIdentity::derive_from_site_url(),
            $calls[0]['args']['headers']['X-Tenant-ID'] ?? null
        );

        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertSame(200, $data['status_code']);
        $this->assertArrayNotHasKey('connected', $data);
        $this->assertArrayNotHasKey('error', $data);
    }

    public function testProbeDispatchReturnsNotConfiguredWithoutHttpCall(): void
    {
        $this->setUserCapability('manage_options', true);
        // No URL set.
        $this->setOption('acx_recognition_api_key', 'test-key');

        $response = $this->controller->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'));
        $data     = $response->get_data();

        $this->assertSame(ProbeOutcome::NOT_CONFIGURED, $data['outcome']);
        $this->assertArrayNotHasKey('connected', $data);
        $this->assertArrayNotHasKey('error', $data);
        $this->assertSame([], $this->getHttpCalls(), 'wp_remote_get must not be called when URL is missing');
    }

    /**
     * @dataProvider outcomeProvider
     * @param array<string, mixed>|\WP_Error $stubbed
     */
    public function testProbeDispatchClassifiesResponse(
        array|\WP_Error $stubbed,
        string $expectedOutcome,
        ?string $expectedDetail,
    ): void {
        $this->configureProbe();
        $this->queueHttpResponse($stubbed);

        $response = $this->controller->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'));
        $data     = $response->get_data();

        $this->assertSame($expectedOutcome, $data['outcome']);
        $this->assertArrayNotHasKey('connected', $data);
        $this->assertArrayNotHasKey('error', $data);
        if (null !== $expectedDetail) {
            $this->assertSame($expectedDetail, $data['detail'] ?? null);
        }
    }

    public static function outcomeProvider(): array
    {
        return [
            'invalid_key_401' => [
                [
                    'response' => ['code' => 401, 'message' => 'Unauthorized'],
                    'body'     => '{"detail": "Authorization header required"}',
                ],
                ProbeOutcome::INVALID_KEY,
                'Authorization header required',
            ],
            'invalid_key_403' => [
                [
                    'response' => ['code' => 403, 'message' => 'Forbidden'],
                    'body'     => '{"detail": "invalid or missing API key"}',
                ],
                ProbeOutcome::INVALID_KEY,
                'invalid or missing API key',
            ],
            'expired' => [
                [
                    'response' => ['code' => 401, 'message' => 'Unauthorized'],
                    'body'     => '{"detail": "api key expired"}',
                ],
                ProbeOutcome::EXPIRED,
                'api key expired',
            ],
            'revoked' => [
                [
                    'response' => ['code' => 401, 'message' => 'Unauthorized'],
                    'body'     => '{"detail": "api key revoked"}',
                ],
                ProbeOutcome::REVOKED,
                'api key revoked',
            ],
            'tenant_mismatch' => [
                [
                    'response' => ['code' => 403, 'message' => 'Forbidden'],
                    'body'     => '{"detail": "tenant mismatch"}',
                ],
                ProbeOutcome::TENANT_MISMATCH,
                'tenant mismatch',
            ],
            'rate_limited' => [
                [
                    'response' => ['code' => 429, 'message' => 'Too Many Requests'],
                    'body'     => '{"detail": "rate limit exceeded"}',
                    'headers'  => ['Retry-After' => '42'],
                ],
                ProbeOutcome::RATE_LIMITED,
                'rate limit exceeded',
            ],
            'server_error' => [
                [
                    'response' => ['code' => 500, 'message' => 'Internal Server Error'],
                    'body'     => '{"detail": "boom"}',
                ],
                ProbeOutcome::SERVER_ERROR,
                'boom',
            ],
            'network_error' => [
                new \WP_Error('http_request_failed', 'Connection refused'),
                ProbeOutcome::NETWORK_ERROR,
                'Connection refused',
            ],
            'tls_error_certificate' => [
                new \WP_Error('http_request_failed', 'SSL certificate problem: self signed certificate'),
                ProbeOutcome::TLS_ERROR,
                null,
            ],
            'tls_error_tls_keyword' => [
                new \WP_Error('http_request_failed', 'TLS handshake failed'),
                ProbeOutcome::TLS_ERROR,
                null,
            ],
            'tls_error_ssl_keyword' => [
                new \WP_Error('http_request_failed', 'SSL routines: error'),
                ProbeOutcome::TLS_ERROR,
                null,
            ],
        ];
    }

    public function testProbeDispatchSurfacesRetryAfterAsInteger(): void
    {
        $this->configureProbe();
        $this->queueHttpResponse([
            'response' => ['code' => 429, 'message' => 'Too Many Requests'],
            'body'     => '{"detail": "rate limit exceeded"}',
            'headers'  => ['Retry-After' => '17'],
        ]);

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $this->assertSame(ProbeOutcome::RATE_LIMITED, $data['outcome']);
        $this->assertSame(17, $data['retry_after_seconds']);
    }

    public function testProbeDispatchOmitsRetryAfterWhenHeaderIsNonNumeric(): void
    {
        $this->configureProbe();
        $this->queueHttpResponse([
            'response' => ['code' => 429, 'message' => 'Too Many Requests'],
            'body'     => '{"detail": "rate limit exceeded"}',
            'headers'  => ['Retry-After' => 'Wed, 21 Oct 2026 07:28:00 GMT'],
        ]);

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $this->assertSame(ProbeOutcome::RATE_LIMITED, $data['outcome']);
        $this->assertArrayNotHasKey(
            'retry_after_seconds',
            $data,
            'HTTP-date Retry-After must fall back to omitted per wire contract (integer delta-seconds only)'
        );
    }

    // --- Permission ---

    public function testCanManageSettingsRequiresManageOptions(): void
    {
        $this->setUserCapability('manage_options', false);
        $this->assertFalse($this->controller->can_manage_settings());

        $this->setUserCapability('manage_options', true);
        $this->assertTrue($this->controller->can_manage_settings());
    }

    // --- Helpers ---

    private function configureProbe(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_url', 'https://api.example.com');
        $this->setOption('acx_recognition_api_key', 'test-key');
    }

    /**
     * @return array<string, mixed>
     */
    private function buildOkResponse(): array
    {
        return [
            'response' => ['code' => 200, 'message' => 'OK'],
            'body'     => '{"pool":"healthy"}',
        ];
    }
}
