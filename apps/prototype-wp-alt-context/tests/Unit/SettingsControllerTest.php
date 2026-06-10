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
        $this->assertSame('http://localhost:8000', $data['local_url']);
        $this->assertSame('http://localhost:8000', $data['effective_target_url']);
        $this->assertSame('local', $data['effective_target_mode']);
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

    public function testGetSettingsBr07FilterUrlWinsOverSavedOptionUrl(): void
    {
        // E15-12-BR-07: when both a saved option URL and a code-managed filter
        // URL exist, the filter (code-managed) MUST win over the option
        // (operator-saved). The pre-fix order was constant -> option -> filter,
        // which let a stale saved URL keep routing recognition traffic even
        // after the operator wired up a filter to point at a new environment,
        // and surfaced the selector as option-owned/editable instead of
        // code-managed/read-only.
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_url', 'https://stale-saved.example.com');
        add_filter('acx_recognition_base_url', static fn () => 'https://filter.example.com');
        add_filter('acx_recognition_source', static fn () => 'service');

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $data = $response->get_data();
        $this->assertSame('https://filter.example.com', $data['url'], 'filter URL must win over saved option URL');
        $this->assertSame('filter', $data['url_source'], 'url_source must report filter when filter is set, even if option is set');
        $this->assertSame('service', $data['recognition_source']);
        $this->assertSame('filter', $data['recognition_source_source'], 'recognition_source_source must report filter (code-managed) so the selector renders read-only');
    }

    public function testGetSettingsRr01FilterApiKeyWinsOverSavedOptionApiKey(): void
    {
        // E15-12-RR-01: same selector contract as BR-07, applied to the API key
        // resolver. When both a saved option api_key and a code-managed filter
        // api_key exist, the filter (code-managed) MUST win over the option
        // (operator-saved). The pre-fix order in resolve_key_source() was
        // constant -> option -> filter, which let a stale saved key keep
        // routing recognition auth to the option value even after the operator
        // wired up a filter to inject a deploy-time key, and surfaced the key
        // field as option-owned/editable instead of code-managed/read-only.
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_api_key', 'sk-stale-saved-abcdef1234');
        add_filter('acx_recognition_api_key', static fn () => 'sk-filter-wins-12345678');

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $data = $response->get_data();
        $this->assertSame(
            'filter',
            $data['key_source'],
            'key_source must report filter when filter is set, even if option is set'
        );
        $this->assertSame(
            '****5678',
            $data['api_key_last4'],
            'api_key_last4 must reflect the filter-provided key, not the saved option'
        );
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

    public function testSaveSettingsRr07PreservesCodeManagedSelectorContract(): void
    {
        // E15-12-RR-07: when a code-managed source (filter) is active, saving
        // a different URL via the operator-facing settings POST must NOT change
        // what the read side returns. The save-path is allowed to update the
        // underlying option (operators may stage a value for the day the
        // filter is removed), but the round-trip read MUST continue to surface
        // the filter URL with source=filter so the selector stays read-only
        // and recognition traffic stays code-managed. This guards against a
        // regression where save_settings or a future cache layer makes the
        // saved option win over the filter.
        $this->setUserCapability('manage_options', true);
        add_filter('acx_recognition_base_url', static fn () => 'https://filter.example.com');
        add_filter('acx_recognition_source', static fn () => 'service');

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params([
            'url' => 'https://operator-saved.example.com',
        ]);

        $save_response = $this->controller->save_settings($request);
        $this->assertInstanceOf(\WP_REST_Response::class, $save_response);

        $get_response = $this->controller->get_settings(new WP_REST_Request('GET', '/acx/v1/settings'));
        $data = $get_response->get_data();

        $this->assertSame(
            'https://filter.example.com',
            $data['url'],
            'GET after save must still surface the filter URL when filter is active'
        );
        $this->assertSame(
            'filter',
            $data['url_source'],
            'url_source must remain filter so the selector renders read-only'
        );
        $this->assertSame(
            'filter',
            $data['recognition_source_source'],
            'recognition_source_source must remain filter (code-managed) so the source selector renders read-only'
        );
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
        $this->setOption('acx_recognition_source', 'service');
        $this->setOption('acx_recognition_api_key', 'test-key');

        $response = $this->controller->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'));
        $data     = $response->get_data();

        $this->assertSame(ProbeOutcome::NOT_CONFIGURED, $data['outcome']);
        $this->assertArrayNotHasKey('connected', $data);
        $this->assertArrayNotHasKey('error', $data);
        $this->assertSame([], $this->getHttpCalls(), 'wp_remote_get must not be called when service URL is missing');
    }

    public function testProbeDispatchHitsLocalHealthWhenLocalModeIsActive(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_url', 'https://api.example.com');
        $this->setOption('acx_recognition_source', 'local');
        $this->setOption('acx_recognition_local_url', 'http://localhost:8001');
        $this->queueHttpResponse($this->buildOkResponse());

        $response = $this->controller->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'));
        $data     = $response->get_data();

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('http://localhost:8001/health', $calls[0]['url']);
        $this->assertArrayNotHasKey('X-API-Key', $calls[0]['args']['headers'] ?? array());
        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertSame('local_liveness', $data['probe_mode']);
        $this->assertSame('http://localhost:8001/health', $data['probed_url']);
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
        $this->setOption('acx_recognition_source', 'service');
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
