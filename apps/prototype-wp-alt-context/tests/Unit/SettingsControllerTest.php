<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ProbeOutcome;
use AltContext\Api\SettingsController;
use AltContext\Api\Services\DescriptionBudgetService;
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
        $this->assertSame('service', $data['recognition_source']);
        $this->assertSame('default', $data['recognition_source_source']);
        // RECOG-1: GET no longer emits local_url / local_url_source.
        $this->assertArrayNotHasKey('local_url', $data);
        $this->assertArrayNotHasKey('local_url_source', $data);
        $this->assertSame('', $data['effective_target_url']);
        $this->assertSame('service', $data['effective_target_mode']);
        $this->assertFalse($data['api_key_set']);
        $this->assertSame('', $data['api_key_last4']);
        $this->assertSame('default', $data['key_source']);
        $this->assertSame(TenantIdentity::resolve()['value'], $data['tenant_id']);
        $this->assertSame('derived', $data['tenant_id_source']);
        $this->assertFalse($data['tenant_paired']);
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
        // RECOG-1: default source is 'service'; effective target is the service URL.
        $this->assertSame('service', $data['recognition_source']);
        $this->assertSame('default', $data['recognition_source_source']);
        $this->assertSame('https://api.example.com', $data['effective_target_url']);
        $this->assertSame('service', $data['effective_target_mode']);
        $this->assertTrue($data['api_key_set']);
        $this->assertSame('****1234', $data['api_key_last4']);
        $this->assertSame('option', $data['key_source']);
    }

    public function testGetSettingsReturnsPersistedTenantFields(): void
    {
        $this->setUserCapability('manage_options', true);
        $tenantId = 'dddddddd-bbbb-cccc-dddd-eeeeeeeeeeee';
        $this->setOption('acx_recognition_tenant_id', $tenantId);

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $data = $response->get_data();
        $this->assertSame($tenantId, $data['tenant_id']);
        $this->assertSame('option', $data['tenant_id_source']);
        $this->assertFalse($data['tenant_paired']);
    }

    public function testGetSettingsReturnsDescriptionBudgetUsageAndRecentErrors(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_description_budget_max_attempts', 25);

        $budget = new DescriptionBudgetService();
        $budget->record_success(101, 'openai', 'gpt-4.1-mini', 1200, false, 'updated', 0.04, 'USD');
        $budget->record_error(102, 'openai', 'gpt-4.1-mini', 'rate_limited', 'Rate limited', true, 'provider', 0.01, 'USD');

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $descriptionBudget = $response->get_data()['description_budget'];
        $this->assertSame(25, $descriptionBudget['max_attempts']);
        $this->assertSame(2, $descriptionBudget['usage']['attempts']);
        $this->assertSame(1, $descriptionBudget['usage']['successes']);
        $this->assertSame(1, $descriptionBudget['usage']['failures']);
        $this->assertSame('rate_limited', $descriptionBudget['recent_errors'][0]['error_code']);
    }

    public function testGetSettingsReturnsFilterTenantSourceWhenFilterProvides(): void
    {
        $this->setUserCapability('manage_options', true);
        $filterTenant = 'eeeeeeee-bbbb-cccc-dddd-eeeeeeeeeeee';
        $this->setOption('acx_recognition_tenant_id', 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');
        add_filter('acx_recognition_tenant_id', static fn () => $filterTenant);

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $data = $response->get_data();
        $this->assertSame($filterTenant, $data['tenant_id']);
        $this->assertSame('filter', $data['tenant_id_source']);
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testGetSettingsReturnsConstantTenantSourceWhenConstantDefined(): void
    {
        require_once __DIR__ . '/../bootstrap.php';
        $this->resetGlobalState();

        $constantTenant = 'ffffffff-bbbb-cccc-dddd-eeeeeeeeeeee';
        define('ACX_RECOGNITION_TENANT_ID', $constantTenant);
        $this->setOption('acx_recognition_tenant_id', 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');

        $controller = new SettingsController();
        $this->setUserCapability('manage_options', true);
        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $controller->get_settings($request);

        $data = $response->get_data();
        $this->assertSame($constantTenant, $data['tenant_id']);
        $this->assertSame('constant', $data['tenant_id_source']);
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
        // RECOG-1: default source is 'service'; effective target is the constant service URL.
        $this->assertSame('service', $data['recognition_source']);
        $this->assertSame('default', $data['recognition_source_source']);
        $this->assertSame('https://const.example.com', $data['effective_target_url']);
        $this->assertSame('service', $data['effective_target_mode']);
        $this->assertSame('constant', $data['key_source']);
        $this->assertSame('****efgh', $data['api_key_last4']);
    }

    // --- POST /settings ---

    public function testSaveSettingsWritesUrlAndKeyToOptions(): void
    {
        $this->setUserCapability('manage_options', true);

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        // RECOG-1: recognition_source is no longer a savable field. Posting it is
        // silently ignored — no option written, not present in the saved array.
        $request->set_body_params([
            'recognition_source' => 'local',
            'url' => 'https://new-api.example.com',
            'api_key' => 'new-key-12345678',
        ]);

        $response = $this->controller->save_settings($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $data = $response->get_data();
        $this->assertSame('ok', $data['result']);
        $this->assertNotContains('recognition_source', $data['saved']);
        $this->assertContains('url', $data['saved']);
        $this->assertContains('api_key', $data['saved']);

        $this->assertFalse(get_option('acx_recognition_source', false));
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

    /**
     * BR-131 / BR-135: http only for loopback — pin the *rule*, not one host.
     * Goes RED under the weakening
     * `return 'http' === $scheme && ( is_loopback_host( $host ) || 'attacker.invalid' !== $host )`.
     *
     * @dataProvider plaintextRemoteUrlProvider
     */
    public function testSaveSettingsRejectsPlaintextRemoteUrl(string $url): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_url', 'https://prior.example');

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params([
            'url' => $url,
        ]);

        $response = $this->controller->save_settings($request);

        $this->assertInstanceOf(\WP_Error::class, $response, 'must reject: ' . $url);
        $this->assertSame('invalid_url', $response->get_error_code());
        $this->assertNotSame($url, get_option('acx_recognition_url', ''));
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function plaintextRemoteUrlProvider(): array
    {
        return [
            // Public / unrelated hosts (not loopback).
            'rejects_public_attacker_invalid' => ['http://attacker.invalid'],
            'rejects_public_evil_example' => ['http://evil.example'],
            'rejects_public_unrelated_host' => ['http://remote.example.com/v1'],
            // mDNS / local-looking names that are not the loopback allowlist.
            'rejects_mdns_dot_local' => ['http://myservice.local'],
            'rejects_mdns_dot_localdomain' => ['http://myservice.localdomain'],
            // RFC1918 private ranges.
            'rejects_rfc1918_10' => ['http://10.0.0.5:8000'],
            'rejects_rfc1918_172_16' => ['http://172.16.0.1'],
            'rejects_rfc1918_172_31' => ['http://172.31.255.254'],
            'rejects_rfc1918_192_168' => ['http://192.168.1.10'],
            // Link-local and cloud metadata.
            'rejects_link_local_169_254' => ['http://169.254.1.1'],
            'rejects_cloud_metadata_169_254_169_254' => ['http://169.254.169.254'],
            // IPv6 non-loopback (bracketed).
            'rejects_ipv6_link_local' => ['http://[fe80::1]'],
            'rejects_ipv6_unique_local' => ['http://[fd00::1]'],
            // Loopback lookalikes that are not allowlisted forms.
            'rejects_loopback_decimal' => ['http://2130706433'],
            'rejects_loopback_octal' => ['http://0177.0.0.1'],
            'rejects_loopback_hex' => ['http://0x7f000001'],
            'rejects_loopback_dotted_suffix' => ['http://127.0.0.1.evil.test'],
            'rejects_localhost_dotted_suffix' => ['http://localhost.evil.test'],
            'rejects_userinfo_loopback_at_remote' => ['http://127.0.0.1@evil.test/'],
        ];
    }

    /**
     * BR-131 / BR-135: accepted side — loopback http and any https remain saveable.
     *
     * @dataProvider acceptedSaveUrlProvider
     */
    public function testSaveSettingsAcceptsLoopbackHttpAndHttpsUrl(string $url): void
    {
        $this->setUserCapability('manage_options', true);

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params([
            'url' => $url,
        ]);

        $response = $this->controller->save_settings($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response, 'must accept: ' . $url);
        $this->assertSame($url, get_option('acx_recognition_url'));
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function acceptedSaveUrlProvider(): array
    {
        return [
            'localhost_port' => ['http://localhost:8000'],
            'loopback_v4' => ['http://127.0.0.1:8000'],
            'loopback_v6' => ['http://[::1]:8000'],
            'localhost_case' => ['HTTP://LOCALHOST'],
            'https_remote' => ['https://api.example.com'],
            'https_any_host' => ['https://evil.example'],
        ];
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

    public function testSaveSettingsWritesDescriptionBudgetLimit(): void
    {
        $this->setUserCapability('manage_options', true);

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params([
            'description_budget' => [
                'max_attempts' => 50,
            ],
        ]);

        $response = $this->controller->save_settings($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertContains('description_budget', $response->get_data()['saved']);
        $this->assertSame(50, get_option('acx_description_budget_max_attempts'));
    }

    public function testSaveSettingsRejectsInvalidDescriptionBudgetLimit(): void
    {
        $this->setUserCapability('manage_options', true);

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params([
            'description_budget' => [
                'max_attempts' => -2,
            ],
        ]);

        $response = $this->controller->save_settings($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_description_budget', $response->get_error_code());
    }

    public function testGetSettingsReturnsAltStyleDefault(): void
    {
        $this->setUserCapability('manage_options', true);

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $this->assertSame('alt_only', $response->get_data()['alt_style']);
    }

    public function testGetSettingsNormalizesInvalidStoredAltStyle(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_alt_style', 'corrupt-value');

        $request = new WP_REST_Request('GET', '/acx/v1/settings');
        $response = $this->controller->get_settings($request);

        $this->assertSame('alt_only', $response->get_data()['alt_style']);
    }

    public function testSaveSettingsWritesAltStyle(): void
    {
        $this->setUserCapability('manage_options', true);

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params(['alt_style' => 'alt_plus_description']);

        $response = $this->controller->save_settings($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertContains('alt_style', $response->get_data()['saved']);
        $this->assertSame('alt_plus_description', get_option('acx_alt_style'));
    }

    public function testSaveSettingsRejectsInvalidAltStyle(): void
    {
        $this->setUserCapability('manage_options', true);

        $request = new WP_REST_Request('POST', '/acx/v1/settings');
        $request->set_body_params(['alt_style' => 'everything_everywhere']);

        $response = $this->controller->save_settings($request);

        $this->assertInstanceOf(\WP_Error::class, $response);
        $this->assertSame('invalid_alt_style', $response->get_error_code());
        $this->assertFalse(get_option('acx_alt_style'));
    }

    // --- POST /settings/test (probe dispatch) ---

    public function testProbeDispatchHitsAuthenticatedPoolEndpoint(): void
    {
        $this->configureProbe();
        $keyTenant = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
        $this->setOption('acx_recognition_tenant_id', $keyTenant);
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));

        $response = $this->controller->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'));
        $data     = $response->get_data();

        $calls = $this->getHttpCalls();
        $this->assertCount(2, $calls);
        $this->assertStringEndsWith('/health/detailed', $calls[0]['url']);
        $this->assertStringEndsWith('/recognition/tenant/whoami', $calls[1]['url']);
        $this->assertStringNotContainsString('/recognition/health/pool', $calls[0]['url']);
        $this->assertSame('test-key', $calls[0]['args']['headers']['X-API-Key'] ?? null);
        $this->assertSame($keyTenant, $calls[0]['args']['headers']['X-Tenant-ID'] ?? null);

        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertTrue($data['tenant_paired']);
        $this->assertSame($keyTenant, $data['tenant_id']);
        $this->assertSame(200, $data['status_code']);
        $this->assertArrayNotHasKey('connected', $data);
        $this->assertArrayNotHasKey('error', $data);
    }

    /**
     * BR-131: non-loopback recognition probes must use wp_safe_remote_get so
     * unsafe redirects / private destinations are rejected by core. The harness
     * marks safe-transport calls with 'safe' => true. Goes RED if
     * recognition_http_get always uses wp_remote_get.
     */
    public function testProbeUsesSafeRemoteGetForNonLoopbackTarget(): void
    {
        $this->configureProbe();
        $keyTenant = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
        $this->setOption('acx_recognition_tenant_id', $keyTenant);
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));

        $this->controller->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'));

        $calls = $this->getHttpCalls();
        $this->assertNotEmpty($calls);
        $this->assertStringEndsWith('/health/detailed', $calls[0]['url']);
        $this->assertTrue(
            !empty($calls[0]['safe']),
            'non-loopback health probe must call wp_safe_remote_get (stub records safe=true)'
        );
    }

    /**
     * BR-131 sibling: loopback development probes keep wp_remote_get so
     * localhost:8000 remains reachable without safe-URL rejection.
     */
    public function testProbeUsesRemoteGetForLoopbackTarget(): void
    {
        $this->setUserCapability('manage_options', true);
        $this->setOption('acx_recognition_url', 'http://127.0.0.1:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $keyTenant = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
        $this->setOption('acx_recognition_tenant_id', $keyTenant);
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));

        $this->controller->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'));

        $calls = $this->getHttpCalls();
        $this->assertNotEmpty($calls);
        $this->assertStringContainsString('127.0.0.1', $calls[0]['url']);
        $this->assertArrayNotHasKey(
            'safe',
            $calls[0],
            'loopback health probe must call wp_remote_get (no safe flag)'
        );
    }

    public function testProbePairingAdoptsMatchingKeyTenant(): void
    {
        $this->configureProbe();
        $keyTenant = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
        $this->setOption('acx_recognition_tenant_id', $keyTenant);
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertTrue($data['tenant_paired']);
        $this->assertTrue(TenantIdentity::is_paired());
        $this->assertSame($keyTenant, get_option('acx_recognition_tenant_id'));
    }

    public function testProbePairingReturnsConflictWhenPersistedTenantDiffers(): void
    {
        $this->configureProbe();
        $persisted = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        $keyTenant = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
        $this->setOption('acx_recognition_tenant_id', $persisted);
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $this->assertSame(ProbeOutcome::TENANT_PAIRING_CONFLICT, $data['outcome']);
        $this->assertSame($persisted, $data['persisted_tenant_id']);
        $this->assertSame($keyTenant, $data['key_tenant_id']);
        $this->assertFalse(TenantIdentity::is_paired());
        $this->assertSame($persisted, get_option('acx_recognition_tenant_id'));
    }

    public function testProbePairingAutoAdoptsDerivedIdentityOnFirstPairing(): void
    {
        $this->configureProbe();
        // No acx_recognition_tenant_id option set: resolve() derives the site-url bootstrap id and
        // persists it, so the option is never empty. A never-paired, auto-derived identity must adopt
        // the key's canonical tenant outright -- not force the operator through a conflict-confirm dance.
        $keyTenant = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertTrue($data['tenant_paired']);
        $this->assertArrayNotHasKey('persisted_tenant_id', $data);
        $this->assertTrue(TenantIdentity::is_paired());
        $this->assertSame($keyTenant, get_option('acx_recognition_tenant_id'));
    }

    public function testProbePairingRejectsMalformedWhoamiTenantId(): void
    {
        $this->configureProbe();
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse('not-a-uuid'));

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        // A malformed whoami tenant_id must surface as a pairing error -- never reach adopt/re-key (no 500,
        // no rows committed under a non-UUID tenant id).
        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertStringContainsString('malformed', $data['pairing_error']);
        $this->assertFalse(TenantIdentity::is_paired());
    }

    public function testProbePairingAdoptsWhenFilterMatchesKeyDespiteStaleOption(): void
    {
        $this->configureProbe();
        $staleOption = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        $keyTenant   = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
        $this->setOption('acx_recognition_tenant_id', $staleOption);
        add_filter('acx_recognition_tenant_id', static fn () => $keyTenant);
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertTrue($data['tenant_paired']);
        $this->assertSame($keyTenant, get_option('acx_recognition_tenant_id'));
    }

    public function testProbePairingConfirmAdoptsAndRekeysLocalRows(): void
    {
        global $wpdb;
        $this->configureProbe();
        $persisted = '11111111-1111-4111-8111-111111111111';
        $keyTenant = '22222222-2222-4222-8222-222222222222';
        $this->setOption('acx_recognition_tenant_id', $persisted);
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));

        $wpdb->insert(
            $wpdb->prefix . 'acx_clusters',
            array(
                'cluster_uuid'       => 'cluster-1',
                'tenant_id'          => $persisted,
                'label'              => 'A',
                'curation_state'     => 'unlabeled',
                'snapshot_version'   => 1,
                'created_at'         => '2026-01-01 00:00:00',
                'updated_at'         => '2026-01-01 00:00:00',
                'last_synced_at'     => '2026-01-01 00:00:00',
            )
        );

        $request = new WP_REST_Request('POST', '/acx/v1/settings/test');
        $request->set_body_params(array('confirm_tenant_pairing' => true));

        $data = $this->controller->test_connection($request)->get_data();

        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertTrue($data['tenant_paired']);
        $this->assertSame('rekey', $data['rekey_strategy']);
        $this->assertGreaterThanOrEqual(1, $data['rekey_updated_rows']);
        $this->assertSame($keyTenant, get_option('acx_recognition_tenant_id'));
        $this->assertSame(
            $keyTenant,
            $wpdb->get_var(
                $wpdb->prepare(
                    'SELECT tenant_id FROM ' . $wpdb->prefix . 'acx_clusters WHERE cluster_uuid = %s',
                    'cluster-1'
                )
            )
        );
    }

    public function testProbePairingWhoamiFailurePreservesConnectedOutcome(): void
    {
        $this->configureProbe();
        $keyTenant = '55555555-5555-4555-8555-555555555555';
        $this->setOption('acx_recognition_tenant_id', $keyTenant);
        $this->queueHttpResponse($this->buildOkResponse());
        $this->queueHttpResponse(
            array(
                'response' => array('code' => 503, 'message' => 'Service Unavailable'),
                'body'     => '{"detail":"database unavailable"}',
            )
        );

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertSame('database unavailable', $data['pairing_error']);
        $this->assertArrayNotHasKey('tenant_paired', $data);
    }

    public function testProbeMismatchAutoAdoptsAndReprobesToGreen(): void
    {
        $this->configureProbe();
        // No acx_recognition_tenant_id option: resolve() derives + persists the auto-derived bootstrap id.
        // A mismatched key 403s the first probe (TENANT_MISMATCH); a never-paired auto-derived site must
        // auto-adopt the key's tenant and recover to green within the SAME "Check health" request.
        $keyTenant = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
        $this->queueHttpResponse($this->buildTenantMismatchResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));
        $this->queueHttpResponse($this->buildOkResponse());

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $calls = $this->getHttpCalls();
        $this->assertCount(3, $calls, 'exactly one pairing whoami + one re-probe -- no retry loop');
        $this->assertStringEndsWith('/health/detailed', $calls[0]['url']);
        $this->assertStringEndsWith('/recognition/tenant/whoami', $calls[1]['url']);
        $this->assertStringEndsWith('/health/detailed', $calls[2]['url']);
        $this->assertSame(
            $keyTenant,
            $calls[2]['args']['headers']['X-Tenant-ID'] ?? null,
            're-probe must carry the adopted tenant identity'
        );

        $this->assertSame(ProbeOutcome::CONNECTED, $data['outcome']);
        $this->assertTrue($data['tenant_paired']);
        $this->assertTrue(TenantIdentity::is_paired());
        $this->assertSame($keyTenant, get_option('acx_recognition_tenant_id'));
    }

    public function testProbeMismatchSurfacesConflictWhenPairedElsewhere(): void
    {
        $this->configureProbe();
        // A pinned (non-auto-derived) tenant whose key now maps elsewhere must NOT auto-adopt: it surfaces
        // the explicit TENANT_PAIRING_CONFLICT for the operator to confirm, and must not re-probe.
        $persisted = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        $keyTenant = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
        $this->setOption('acx_recognition_tenant_id', $persisted);
        $this->queueHttpResponse($this->buildTenantMismatchResponse());
        $this->queueHttpResponse($this->buildWhoamiResponse($keyTenant));

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $this->assertCount(2, $this->getHttpCalls(), 'a conflict must not trigger a re-probe');
        $this->assertSame(ProbeOutcome::TENANT_PAIRING_CONFLICT, $data['outcome']);
        $this->assertSame($persisted, $data['persisted_tenant_id']);
        $this->assertSame($keyTenant, $data['key_tenant_id']);
        $this->assertFalse(TenantIdentity::is_paired());
        $this->assertSame($persisted, get_option('acx_recognition_tenant_id'));
    }

    public function testProbeMismatchPairingErrorReturnsProbeOutcomeAsIs(): void
    {
        $this->configureProbe();
        // Auto-derived + never-paired, so adoption is eligible -- but the whoami lookup fails, so adoption
        // never happens. The original probe outcome (TENANT_MISMATCH) is returned as-is with a pairing_error,
        // and no re-probe fires.
        $this->queueHttpResponse($this->buildTenantMismatchResponse());
        $this->queueHttpResponse(
            array(
                'response' => array('code' => 503, 'message' => 'Service Unavailable'),
                'body'     => '{"detail":"database unavailable"}',
            )
        );

        $data = $this->controller
            ->test_connection(new WP_REST_Request('POST', '/acx/v1/settings/test'))
            ->get_data();

        $this->assertCount(2, $this->getHttpCalls(), 'a failed pairing must not trigger a re-probe');
        $this->assertSame(ProbeOutcome::TENANT_MISMATCH, $data['outcome'], 'probe outcome returned as-is on pairing error');
        $this->assertSame('database unavailable', $data['pairing_error']);
        $this->assertFalse(TenantIdentity::is_paired());
        $this->assertArrayNotHasKey('tenant_paired', $data);
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

    // RECOG-1: the keyless local /health liveness probe (probe_mode 'local_liveness')
    // and the probe_target=local dispatch were removed. test_connection now always
    // runs the authenticated service probe (/health/detailed, probe_mode
    // 'service_auth'). The former testProbeDispatchHitsLocalHealthWhenLocalModeIsActive
    // and testProbeDispatchHonorsExplicitProbeTarget tests were deleted with that behavior.

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

    /**
     * @return array<string, mixed>
     */
    private function buildTenantMismatchResponse(): array
    {
        return [
            'response' => ['code' => 403, 'message' => 'Forbidden'],
            'body'     => '{"detail":"tenant mismatch"}',
        ];
    }

    /**
     * @return array<string, mixed>
     */
    private function buildWhoamiResponse(string $tenantId): array
    {
        return [
            'response' => ['code' => 200, 'message' => 'OK'],
            'body'     => wp_json_encode(
                array(
                    'tenant_id' => $tenantId,
                    'site_url'  => 'https://prod.example',
                )
            ),
        ];
    }
}
