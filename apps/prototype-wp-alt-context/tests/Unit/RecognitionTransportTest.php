<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\LoopbackHost;
use AltContext\Support\RecognitionTransport;
use AltContext\Tests\TestCase;

/**
 * BR-137 / R4G: shared credentialed recognition egress.
 *
 * @covers \AltContext\Support\RecognitionTransport
 */
class RecognitionTransportTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        require_once dirname(__DIR__, 2) . '/src/support/class-recognition-transport.php';
        require_once dirname(__DIR__, 2) . '/src/support/class-loopback-host.php';
        RecognitionTransport::set_curl_capability_probe(static fn (string $scheme): bool => true);
    }

    protected function tearDown(): void
    {
        RecognitionTransport::set_curl_capability_probe(null);
        RecognitionTransport::set_curl_resolve_applier(null);
        RecognitionTransport::set_http_api_curl_runner(null);
        parent::tearDown();
    }

    /**
     * Public non-loopback hosts must take the safe transport; non-global
     * literals must be denied before HTTP. A fixture-host-only
     * implementation (api.example.test hard-code) goes RED on other public hosts.
     *
     * @dataProvider nonLoopbackHostProvider
     */
    public function testGetUsesSafeTransportForNonLoopbackHosts(string $url, bool $expectedDenied = false): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'ok',
        ]);

        $result = RecognitionTransport::get($url, ['headers' => ['X-API-Key' => 'k'], 'timeout' => 5]);

        if ($expectedDenied) {
            $this->assertInstanceOf(\WP_Error::class, $result);
            $this->assertSame('acx_egress_denied', $result->get_error_code());
            $this->assertCount(0, $this->getHttpCalls());
            return;
        }

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertTrue(
            !empty($calls[0]['safe']),
            'non-loopback GET must use wp_safe_remote_get; host=' . parse_url($url, PHP_URL_HOST)
        );
    }

    /**
     * @dataProvider nonLoopbackHostProvider
     */
    public function testRequestUsesSafeTransportForNonLoopbackHosts(string $url, bool $expectedDenied = false): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'ok',
        ]);

        $result = RecognitionTransport::request($url, [
            'method' => 'GET',
            'headers' => ['X-API-Key' => 'k'],
            'timeout' => 5,
        ]);

        if ($expectedDenied) {
            $this->assertInstanceOf(\WP_Error::class, $result);
            $this->assertSame('acx_egress_denied', $result->get_error_code());
            $this->assertCount(0, $this->getHttpCalls());
            return;
        }

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertTrue(
            !empty($calls[0]['safe']),
            'non-loopback request must use wp_safe_remote_request; host=' . parse_url($url, PHP_URL_HOST)
        );
    }

    /**
     * @return array<string, array{0: string, 1: bool}>
     */
    public static function nonLoopbackHostProvider(): array
    {
        return [
            'public_dns' => ['https://api.example.test/health', false],
            'unrelated_tld' => ['https://cdn.other-org.example/v1', false],
            'bare_public_ipv4' => ['https://203.0.113.10/probe', false],
            'global_ipv4' => ['https://93.184.216.34/probe', false],
            'public_ipv6' => ['https://[2606:4700:4700::1111]/probe', false],
            'bracketed_ipv6' => ['https://[2001:db8::1]/probe', true],
        ];
    }

    /**
     * @dataProvider loopbackHostProvider
     */
    public function testGetUsesPlainTransportForLoopbackHosts(string $url): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'ok',
        ]);

        RecognitionTransport::get($url, ['timeout' => 5]);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertArrayNotHasKey(
            'safe',
            $calls[0],
            'loopback GET must use wp_remote_get; host=' . parse_url($url, PHP_URL_HOST)
        );
    }

    /**
     * @dataProvider loopbackHostProvider
     */
    public function testRequestUsesPlainTransportForLoopbackHosts(string $url): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'ok',
        ]);

        RecognitionTransport::request($url, ['method' => 'GET', 'timeout' => 5]);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertArrayNotHasKey(
            'safe',
            $calls[0],
            'loopback request must use wp_remote_request; host=' . parse_url($url, PHP_URL_HOST)
        );
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function loopbackHostProvider(): array
    {
        return [
            'localhost' => ['http://localhost:8000/health'],
            'ipv4_loopback' => ['http://127.0.0.1:8000/health'],
            'bracketed_ipv6_loopback' => ['http://[::1]:8000/health'],
        ];
    }

    /**
     * R7 / FIX-6: hardcoded correctness pin for the transport safe-vs-plain
     * chooser and egress gate. Expectations are literal true/false/null (deny),
     * never derived from
     * LoopbackHost::is_loopback — so a predicate widen moves the chooser red
     * here even when the consistency oracle still agrees with itself.
     *
     * Covers the four loopback forms, the adversarial near-loopback set from
     * the oracle corpus, and userinfo-bearing hosts (parse_url host extraction).
     *
     * @dataProvider transportSafeChoiceHardcodedProvider
     */
    public function testTransportSafeChoiceHardcodedExpectations(string $url, ?bool $expectedPlain): void
    {
        foreach (['get', 'request'] as $method) {
            $GLOBALS['__ac_http_calls'] = [];
            $this->queueHttpResponse([
                'response' => ['code' => 200, 'message' => 'OK'],
                'body' => 'ok',
            ]);

            if ('get' === $method) {
                $result = RecognitionTransport::get($url, ['headers' => ['X-API-Key' => 'k'], 'timeout' => 5]);
            } else {
                $result = RecognitionTransport::request($url, ['method' => 'GET', 'headers' => ['X-API-Key' => 'k'], 'timeout' => 5]);
            }

            $calls = $this->getHttpCalls();
            if (null === $expectedPlain) {
                // class-recognition-transport.php:126-135,156-165 rejects empty
                // resolution and non-global addresses before either safe call.
                $this->assertInstanceOf(\WP_Error::class, $result);
                $this->assertSame('acx_egress_denied', $result->get_error_code());
                $this->assertCount(0, $calls, "denied {$method} must not send credentials for url={$url}");
                continue;
            }
            $this->assertCount(1, $calls, "hardcoded {$method} must issue one call for url={$url}");

            $usedSafe = !empty($calls[0]['safe']);
            $this->assertSame(
                !$expectedPlain,
                $usedSafe,
                sprintf(
                    'RecognitionTransport::%s safe flag mismatch for url=%s (expected_plain=%s, used_safe=%s)',
                    $method,
                    $url,
                    $expectedPlain ? 'true' : 'false',
                    $usedSafe ? 'true' : 'false'
                )
            );
        }
    }

    /**
     * @return array<string, array{0: string, 1: bool|null}>
     */
    public static function transportSafeChoiceHardcodedProvider(): array
    {
        return [
            // Explicit loopback remains the development exception:
            // transport:122-124,152-154 and endpoint resolver:73,269-271.
            // Four loopback forms — must take plain transport (expectedPlain=true).
            'loopback_localhost' => ['http://localhost:8000/health', true],
            'loopback_ipv4' => ['http://127.0.0.1:8000/health', true],
            'loopback_ipv6_bare_bracketed_in_url' => ['http://[::1]:8000/health', true],
            'loopback_ipv6_bracketed' => ['https://[::1]/oracle-probe', true],
            // Public destinations still exercise the safe chooser.
            'public_dns' => ['https://api.example.test/oracle-probe', false],
            'public_ipv4' => ['https://93.184.216.34/oracle-probe', false],
            'public_ipv6' => ['https://[2606:4700:4700::1111]/oracle-probe', false],
            // Adversarial near-loopback and unknown hosts must be denied.
            'reject_0_0_0_0' => ['https://0.0.0.0/oracle-probe', null],
            'reject_127_1' => ['https://127.1/oracle-probe', null],
            'reject_ipv4_mapped' => ['https://[::ffff:127.0.0.1]/oracle-probe', null],
            'reject_dword' => ['https://2130706433/oracle-probe', null],
            'reject_localhost_trailing_dot' => ['https://localhost./oracle-probe', null],
            'reject_loopback_trailing_dot' => ['https://127.0.0.1./oracle-probe', null],
            'reject_localhost_evil' => ['https://localhost.evil.test/oracle-probe', null],
            'reject_documentation_ipv6' => ['https://[2001:db8::1]/oracle-probe', null],
            // Userinfo-bearing: parse_url host is evil.test, not localhost.
            'reject_userinfo_localhost_at_evil' => ['https://localhost@evil.test/oracle-probe', null],
        ];
    }

    /**
     * R5G-BR-03 / [TEST-15]: consistency pin — transport safe-vs-plain must
     * agree with LoopbackHost::is_loopback for a large programmatically
     * generated host corpus (anti-allowlist device). Expected values are
     * computed from the same parse_url-extracted, lowercased host the
     * transport uses for admitted destinations. Denial expectations for the
     * non-global and unresolved corpus entries are independent of production.
     * Correctness of the loopback set is pinned by
     * the hardcoded table and RecognitionEndpointResolverTest matrix, not here.
     */
    public function testTransportSafeChoiceAgreesWithLoopbackHostOracle(): void
    {
        $hosts = self::generateOracleHostCorpus();
        $dnsHosts = self::generateOracleDnsHostCorpus();
        // This corpus owns its named DNS fixtures. Literal IPs still reach
        // the real address validator; adversarial names remain unresolved.
        RecognitionTransport::set_resolver(static function (string $host) use ($dnsHosts): array {
            return in_array($host, $dnsHosts, true) ? ['93.184.216.34'] : self::resolveFixtureHost($host);
        });
        $this->assertGreaterThanOrEqual(
            40,
            count($hosts),
            'oracle corpus must be large enough that a fixture-host allowlist cannot mirror it'
        );

        foreach ($hosts as $host) {
            $url = self::urlForHost($host);
            // Match RecognitionTransport: parse_url host, lowercased.
            $parsedHost = strtolower((string) (parse_url($url, PHP_URL_HOST) ?? ''));
            $expectedPlain = LoopbackHost::is_loopback($parsedHost);
            $expectedDenied = str_starts_with($parsedHost, '[2001:db8:') || in_array($parsedHost, [
                'localhost.evil.test', 'localhost.', '127.1', '0.0.0.0',
                '2130706433', '[::ffff:127.0.0.1]', '127.0.0.1.attacker.invalid',
            ], true);

            foreach (['get', 'request'] as $method) {
                $GLOBALS['__ac_http_calls'] = [];
                $this->queueHttpResponse([
                    'response' => ['code' => 200, 'message' => 'OK'],
                    'body' => 'ok',
                ]);

                if ('get' === $method) {
                    $result = RecognitionTransport::get($url, ['headers' => ['X-API-Key' => 'k'], 'timeout' => 5]);
                } else {
                    $result = RecognitionTransport::request($url, ['method' => 'GET', 'headers' => ['X-API-Key' => 'k'], 'timeout' => 5]);
                }

                $calls = $this->getHttpCalls();
                if ($expectedDenied) {
                    $this->assertInstanceOf(\WP_Error::class, $result);
                    $this->assertSame('acx_egress_denied', $result->get_error_code());
                    $this->assertCount(0, $calls, "denied oracle {$method} must not send for host={$host}");
                    continue;
                }
                $this->assertCount(1, $calls, "oracle {$method} must issue one call for host={$host}");

                $usedSafe = !empty($calls[0]['safe']);
                $this->assertSame(
                    !$expectedPlain,
                    $usedSafe,
                    sprintf(
                        'RecognitionTransport::%s safe flag must equal !LoopbackHost::is_loopback(parse_url host) for corpus_host=%s parsed_host=%s (expected_plain=%s, used_safe=%s)',
                        $method,
                        $host,
                        $parsedHost,
                        $expectedPlain ? 'true' : 'false',
                        $usedSafe ? 'true' : 'false'
                    )
                );
            }
        }
    }

    /**
     * Programmatic named DNS fixtures for the oracle's external resolver seam.
     *
     * @return list<string>
     */
    private static function generateOracleDnsHostCorpus(): array
    {
        $hosts = [];
        $labels = [
            'api', 'cdn', 'recognition', 'svc', 'edge', 'origin', 'health',
            'altcontext', 'other-org', 'prod', 'staging', 'media', 'blob',
            'worker', 'ingest', 'gateway', 'mesh', 'control',
        ];
        $tlds = [
            'example.test', 'example.com', 'example.net', 'example.org',
            'invalid', 'local', 'internal', 'corp', 'io', 'dev',
        ];
        foreach ($labels as $i => $label) {
            $tld = $tlds[$i % count($tlds)];
            $hosts[] = $label . '.' . $tld;
            $hosts[] = $label . $i . '.' . $tld;
        }

        return $hosts;
    }

    /**
     * Programmatic host corpus: DNS fixtures, bare public IPv4,
     * bracketed IPv6 (including denied documentation addresses), and loopback.
     * Userinfo-bearing and other adversarial forms that need hardcoded
     * expectations live in transportSafeChoiceHardcodedProvider.
     *
     * @return list<string>
     */
    private static function generateOracleHostCorpus(): array
    {
        $hosts = self::generateOracleDnsHostCorpus();

        // Preserve the existing IPv4 corpus (the production PHP validator
        // admits these documentation ranges), and add a public range.
        foreach ([10, 20, 30, 40, 50, 100, 113, 200] as $third) {
            $hosts[] = '203.0.' . $third . '.10';
            $hosts[] = '198.51.100.' . $third;
            $hosts[] = '192.0.2.' . $third;
            $hosts[] = '93.184.' . $third . '.10';
        }

        // Bracketed documentation / non-loopback IPv6.
        foreach (['1', '2', 'a', 'f', '10', 'ff'] as $nibble) {
            $hosts[] = '[2001:db8::' . $nibble . ']';
            $hosts[] = '[2001:db8:1::' . $nibble . ']';
            $hosts[] = '[2606:4700::' . $nibble . ']';
        }

        // Adversarial near-loopback forms that must NOT take plain transport.
        // Kept in the corpus as an anti-allowlist device; correctness is pinned
        // by transportSafeChoiceHardcodedProvider + loopbackHostMatrixProvider.
        $hosts[] = 'localhost.evil.test';
        $hosts[] = 'localhost.';
        $hosts[] = '127.1';
        $hosts[] = '0.0.0.0';
        $hosts[] = '2130706433';
        $hosts[] = '[::ffff:127.0.0.1]';
        $hosts[] = '127.0.0.1.attacker.invalid';

        // Explicit loopback forms (must take plain transport).
        $hosts[] = 'localhost';
        $hosts[] = '127.0.0.1';
        $hosts[] = '::1';
        $hosts[] = '[::1]';

        // Unique, stable order.
        $hosts = array_values(array_unique($hosts));

        return $hosts;
    }

    private static function urlForHost(string $host): string
    {
        // Bare ::1 must be bracketed for a legal URL host; LoopbackHost accepts both.
        if ('::1' === $host) {
            $host = '[::1]';
        }

        return 'https://' . $host . '/oracle-probe';
    }

    /**
     * Never-follow-redirects is a transport policy: forced even if the caller
     * passes redirection > 0.
     */
    public function testForcesRedirectionZeroOverridingCaller(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'ok',
        ]);

        RecognitionTransport::get('https://api.example.test/health', [
            'headers' => ['X-API-Key' => 'secret'],
            'redirection' => 5,
        ]);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame(0, $calls[0]['args']['redirection'] ?? null);
    }

    /**
     * R5G-BR-04: request() must force redirection => 0 the same way get() does.
     * A request()-only mutation that drops the force line goes red here while
     * leaving get()-only pins green.
     */
    public function testRequestForcesRedirectionZeroOverridingCaller(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'ok',
        ]);

        RecognitionTransport::request('https://api.example.test/health', [
            'method' => 'GET',
            'headers' => ['X-API-Key' => 'secret'],
            'redirection' => 5,
        ]);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame(
            0,
            $calls[0]['args']['redirection'] ?? null,
            'RecognitionTransport::request must force redirection => 0 even when caller passes > 0'
        );
    }

    /**
     * R5G-BR-02: redirection => 0 is credential-policy, not API-key-only policy.
     * Settings probes send X-Tenant-ID always and X-API-Key only optionally.
     * A mutation that forces redirection=0 only when X-API-Key is present must
     * go red on tenant-only and empty-header rows.
     *
     * @dataProvider credentialHeaderProvider
     */
    public function testGetForcesRedirectionZeroRegardlessOfCredentialHeaders(array $headers): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'stolen',
        ]);

        $response = RecognitionTransport::get('https://api.example.test/health', [
            'headers' => $headers,
            'redirection' => 5,
        ]);

        $this->assertIsArray($response);
        $this->assertSame(302, (int) ($response['response']['code'] ?? 0));

        $calls = $this->getHttpCalls();
        $this->assertCount(
            1,
            $calls,
            'GET must not follow redirect regardless of credential headers present'
        );
        $this->assertSame(
            0,
            $calls[0]['args']['redirection'] ?? null,
            'GET redirection must be forced to 0 without requiring X-API-Key'
        );
    }

    /**
     * @dataProvider credentialHeaderProvider
     */
    public function testRequestForcesRedirectionZeroRegardlessOfCredentialHeaders(array $headers): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'stolen',
        ]);

        $response = RecognitionTransport::request('https://api.example.test/health', [
            'method' => 'GET',
            'headers' => $headers,
            'redirection' => 5,
        ]);

        $this->assertIsArray($response);
        $this->assertSame(302, (int) ($response['response']['code'] ?? 0));

        $calls = $this->getHttpCalls();
        $this->assertCount(
            1,
            $calls,
            'request must not follow redirect regardless of credential headers present'
        );
        $this->assertSame(
            0,
            $calls[0]['args']['redirection'] ?? null,
            'request redirection must be forced to 0 without requiring X-API-Key'
        );
    }

    /**
     * @return array<string, array{0: array<string, string>}>
     */
    public static function credentialHeaderProvider(): array
    {
        return [
            'api_key_and_tenant' => [
                [
                    'X-API-Key' => 'secret-must-not-walk',
                    'X-Tenant-ID' => 'tenant-1',
                ],
            ],
            'tenant_only' => [
                [
                    'X-Tenant-ID' => 'tenant-1',
                ],
            ],
            'empty_headers' => [
                [],
            ],
        ];
    }

    /**
     * Harness self-test: exercises the HTTP stub's redirect-follow behaviour,
     * not src/. Stays green under every production RecognitionTransport mutation.
     * Kept as evidence that with redirection > 0 the stub follows Location and
     * re-sends credential headers.
     */
    public function testHarnessStubFollowsRedirectWhenRedirectionPositiveWalkingHeaders(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'stolen',
        ]);

        // Bypass RecognitionTransport: call the safe transport with WP default
        // redirection budget so the stub's follow behaviour is the subject.
        $response = wp_safe_remote_get('https://api.example.test/health', [
            'headers' => [
                'X-API-Key' => 'secret-must-not-walk',
                'X-Tenant-ID' => 'tenant-1',
            ],
            'redirection' => 5,
        ]);

        $this->assertIsArray($response);
        $this->assertSame(200, (int) ($response['response']['code'] ?? 0));

        $calls = $this->getHttpCalls();
        $this->assertCount(
            2,
            $calls,
            'with redirection > 0 the stub must issue a second request to Location'
        );
        $this->assertStringContainsString('attacker.example', $calls[1]['url']);
        $this->assertSame(
            'secret-must-not-walk',
            $calls[1]['args']['headers']['X-API-Key'] ?? null,
            'second hop re-sends X-API-Key — this is the BR-137 credential walk'
        );
    }

    /**
     * Harness self-test (R6L-BR-03 / [TEST-15]): pins the stub default that every
     * never-follow assertion depends on. WP_Http defaults redirection to 5 when
     * the key is omitted; the harness stub must do the same. The explicit
     * 'redirection' => 5 pin above does not exercise the omitted-key path — if
     * the default ever drifts to 0, assertCount(1) never-follow pins go vacuous.
     * Goes red under mutation default 5 → 0.
     */
    public function testHarnessStubDefaultsRedirectionToFiveWhenKeyOmittedAndFollowsWalkingHeaders(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'stolen',
        ]);

        // Intentionally omit 'redirection' — subject is the stub default, not an
        // explicit budget. A default of 0 would return the 302 in one hop.
        $response = wp_safe_remote_get('https://api.example.test/health', [
            'headers' => [
                'X-API-Key' => 'secret-must-not-walk',
                'X-Tenant-ID' => 'tenant-1',
            ],
        ]);

        $this->assertIsArray($response);
        $this->assertSame(200, (int) ($response['response']['code'] ?? 0));

        $calls = $this->getHttpCalls();
        $this->assertCount(
            2,
            $calls,
            'omitted redirection key must default to > 0 so the stub follows Location'
        );
        $this->assertStringContainsString('attacker.example', $calls[1]['url']);
        $this->assertSame(
            'secret-must-not-walk',
            $calls[1]['args']['headers']['X-API-Key'] ?? null,
            'second hop re-sends X-API-Key under the omitted-key default'
        );
    }

    /**
     * Transport chooser + forced redirection=0: a 302 stays a single hop.
     */
    public function testTransportDoesNotFollowRedirect(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'stolen',
        ]);

        $response = RecognitionTransport::get('https://api.example.test/health', [
            'headers' => ['X-API-Key' => 'secret-must-not-walk'],
        ]);

        $this->assertIsArray($response);
        $this->assertSame(302, (int) ($response['response']['code'] ?? 0));

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls, 'must not follow redirect under RecognitionTransport');
        $this->assertSame(0, $calls[0]['args']['redirection'] ?? null);
        $this->assertStringNotContainsString('attacker.example', $calls[0]['url']);
    }

    /**
     * R5G-BR-04: request() must never follow redirects. Mirrors
     * testTransportDoesNotFollowRedirect for the request() entrypoint.
     * Goes red under a request()-only drop of the redirection force.
     */
    public function testRequestDoesNotFollowRedirect(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 302, 'message' => 'Found'],
            'headers' => ['Location' => 'https://attacker.example/collect'],
            'body' => '',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'stolen',
        ]);

        $response = RecognitionTransport::request('https://api.example.test/health', [
            'method' => 'GET',
            'headers' => ['X-API-Key' => 'secret-must-not-walk'],
            'redirection' => 5,
        ]);

        $this->assertIsArray($response);
        $this->assertSame(302, (int) ($response['response']['code'] ?? 0));

        $calls = $this->getHttpCalls();
        $this->assertCount(
            1,
            $calls,
            'must not follow redirect under RecognitionTransport::request'
        );
        $this->assertSame(0, $calls[0]['args']['redirection'] ?? null);
        $this->assertStringNotContainsString('attacker.example', $calls[0]['url']);
    }

    /**
     * @dataProvider nonGlobalResolutionProvider
     *
     * @param list<string> $addresses
     */
    public function testGetAndRequestDenyNonGlobalResolvedAddresses(array $addresses): void
    {
        RecognitionTransport::set_resolver(static fn (string $host): array => $addresses);

        foreach (['get', 'request'] as $method) {
            $GLOBALS['__ac_http_calls'] = [];
            $result = 'get' === $method
                ? RecognitionTransport::get('https://api.example.test/health', ['timeout' => 5])
                : RecognitionTransport::request('https://api.example.test/health', ['method' => 'GET', 'timeout' => 5]);

            $this->assertInstanceOf(\WP_Error::class, $result, $method . ' must reject non-global DNS results');
            $this->assertSame('acx_egress_denied', $result->get_error_code());
            $this->assertSame([], $this->getHttpCalls(), $method . ' must not make an HTTP call after rejection');
        }
    }

    /**
     * @dataProvider nonGlobalLiteralProvider
     */
    public function testNonGlobalLiteralsAreDeniedWithDefaultAndProductionResolver(string $url): void
    {
        foreach (['fixture', 'production'] as $resolver) {
            if ('production' === $resolver) {
                // Canonical literals take resolve_host():182-185 without DNS.
                RecognitionTransport::set_resolver(null);
            }
            foreach (['get', 'request'] as $method) {
                $GLOBALS['__ac_http_calls'] = [];
                $args = ['headers' => ['X-API-Key' => 'secret-must-not-leave'], 'timeout' => 5];
                $result = 'get' === $method
                    ? RecognitionTransport::get($url, $args)
                    : RecognitionTransport::request($url, ['method' => 'GET'] + $args);

                // Removing the non-global check at transport:132/162 would
                // send 0.0.0.0 or mapped loopback, failing these assertions.
                $this->assertInstanceOf(\WP_Error::class, $result, "{$resolver} {$method} must deny {$url}");
                $this->assertSame('acx_egress_denied', $result->get_error_code());
                $this->assertCount(0, $this->getHttpCalls(), "{$resolver} {$method} must not send X-API-Key");
            }
        }
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function nonGlobalLiteralProvider(): array
    {
        return [
            'unspecified_ipv4' => ['https://0.0.0.0/health'],
            'private_ipv4' => ['https://10.0.0.5/health'],
            'metadata_ipv4' => ['https://169.254.169.254/health'],
            'mapped_loopback' => ['https://[::ffff:127.0.0.1]/health'],
            'documentation_ipv6' => ['https://[2001:db8::1]/health'],
            'unique_local_ipv6' => ['https://[fd00::1]/health'],
            'link_local_ipv6' => ['https://[fe80::1]/health'],
        ];
    }

    /**
     * @return array<string, array{0: list<string>}>
     */
    public static function nonGlobalResolutionProvider(): array
    {
        return [
            'cloud_metadata' => [['169.254.169.254']],
            'private_ipv4' => [['10.0.0.5']],
            'shared_address_space' => [['100.64.0.1']],
            'private_lan' => [['192.168.1.2']],
            'unspecified_ipv4' => [['0.0.0.0']],
            'unique_local_ipv6' => [['fd00::1']],
            'link_local_ipv6' => [['fe80::1']],
            'mapped_metadata_ipv4' => [['::ffff:169.254.169.254']],
            'empty_result' => [[]],
            'mixed_public_and_private' => [['93.184.216.34', '10.0.0.5']],
        ];
    }

    public function testPublicResolutionStillUsesSafeHttpAndRemovesCurlAction(): void
    {
        RecognitionTransport::set_resolver(static fn (string $host): array => ['93.184.216.34']);
        $appliedPins = [];
        $before = 0;
        RecognitionTransport::set_curl_resolve_applier(
            static function ($handle, array $value) use (&$appliedPins): void {
                $appliedPins[] = $value;
            }
        );
        RecognitionTransport::set_http_api_curl_runner(
            function (callable $callback, callable $request, string $url) use (&$appliedPins, &$before): mixed {
                $registered = $GLOBALS['__ac_actions']['http_api_curl'][10] ?? [];
                $this->assertCount($before + 1, $registered, 'the pin callback must be registered during transport');
                $this->assertSame($callback, $registered[0]['callback'] ?? null);

                $handle = (object) [];
                $callback($handle, [], 'https://other.example.test/health');
                $this->assertSame([], $appliedPins, 'a different host must remain unpinned');
                $callback($handle, [], 'https://api.example.test:8443/health');
                $this->assertSame([], $appliedPins, 'a different port must remain unpinned');
                $callback($handle, [], $url);
                $this->assertSame(
                    [['api.example.test:443:93.184.216.34']],
                    $appliedPins,
                    'the matching host and port must receive the validated CURLOPT_RESOLVE pin'
                );

                return $request();
            }
        );

        foreach (['get', 'request'] as $method) {
            $GLOBALS['__ac_http_calls'] = [];
            $before = self::httpApiCurlActionCount();
            $appliedPins = [];
            $this->queueHttpResponse([
                'response' => ['code' => 200, 'message' => 'OK'],
                'body' => 'ok',
            ]);

            if ('get' === $method) {
                RecognitionTransport::get('https://api.example.test/health', ['timeout' => 5]);
            } else {
                RecognitionTransport::request('https://api.example.test/health', ['method' => 'GET', 'timeout' => 5]);
            }

            $calls = $this->getHttpCalls();
            $this->assertCount(1, $calls);
            $this->assertTrue(!empty($calls[0]['safe']), $method . ' must reach the safe WordPress HTTP API');
            $this->assertSame($before, self::httpApiCurlActionCount(), 'request-scoped cURL action must be removed');
        }
    }

    public function testPublicResolutionFailsClosedWhenRequestsCannotUseCurl(): void
    {
        RecognitionTransport::set_resolver(static fn (string $host): array => ['93.184.216.34']);
        $probedSchemes = [];
        RecognitionTransport::set_curl_capability_probe(
            static function (string $scheme) use (&$probedSchemes): bool {
                $probedSchemes[] = $scheme;
                return false;
            }
        );
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'must not be sent',
        ]);

        $result = RecognitionTransport::get('https://api.example.test/health', [
            'headers' => ['X-API-Key' => 'fake-test-key'],
            'timeout' => 5,
        ]);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('acx_egress_pin_unavailable', $result->get_error_code());
        $this->assertSame(
            'Recognition egress pin is unavailable because the WordPress HTTP transport cannot use cURL.',
            $result->get_error_message()
        );
        $this->assertSame(['https'], $probedSchemes, 'HTTPS capability must include the TLS cURL check');
        $this->assertCount(0, $this->getHttpCalls(), 'a request without a usable pin must not send credentials');
        $this->assertSame(0, self::httpApiCurlActionCount());
    }

    public function testLoopbackStillSendsWhenCurlPinIsUnavailable(): void
    {
        $probedSchemes = [];
        RecognitionTransport::set_curl_capability_probe(
            static function (string $scheme) use (&$probedSchemes): bool {
                $probedSchemes[] = $scheme;
                return false;
            }
        );
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'ok',
        ]);

        $result = RecognitionTransport::get('http://[::1]:8000/health', ['timeout' => 5]);

        $this->assertIsArray($result);
        $this->assertSame([], $probedSchemes, 'loopback must bypass the remote cURL pin gate');
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertArrayNotHasKey('safe', $calls[0], 'loopback must keep using the plain local transport');
        $this->assertSame(0, self::httpApiCurlActionCount());
    }

    /**
     * @return array<string, array{0: string, 1: bool}>
     */
    public static function globalAddressProvider(): array
    {
        return [
            'public_ipv4' => ['93.184.216.34', true],
            'public_ipv6' => ['2001:4860::1', true],
            'private_ipv4' => ['10.0.0.5', false],
            'shared_address_space' => ['100.64.0.1', false],
            'link_local_ipv4' => ['169.254.169.254', false],
            'unspecified_ipv4' => ['0.0.0.0', false],
            'multicast_ipv4' => ['224.0.0.1', false],
            'unique_local_ipv6' => ['fd00::1', false],
            'link_local_ipv6' => ['fe80::1', false],
            'multicast_ipv6' => ['ff02::1', false],
            'unspecified_ipv6' => ['::', false],
            'ipv6_loopback' => ['::1', false],
            'nat64_well_known_private_embedding' => ['64:ff9b::a9fe:a9fe', false],
            'nat64_well_known_rfc1918_embedding' => ['64:ff9b::a00:5', false],
            'nat64_local_use' => ['64:ff9b:1::a00:5', false],
            'six_to_four_private_embedding' => ['2002:a9fe:a9fe::1', false],
            'teredo_private_embedding' => ['2001:0:a9fe:a9fe::1', false],
            'ipv4_compatible_private_embedding' => ['::a9fe:a9fe', false],
            'ipv4_translated_private_embedding' => ['::ffff:0:a9fe:a9fe', false],
            'discard_only_ipv6' => ['100::1', false],
            'site_local_ipv6' => ['fec0::1', false],
            'protocol_assignment_ipv4' => ['192.0.0.170', false],
            'benchmark_ipv4' => ['198.18.0.1', false],
            'mapped_private_ipv4' => ['::ffff:169.254.169.254', false],
            'mapped_public_ipv4' => ['::ffff:93.184.216.34', true],
            'invalid_address' => ['not-an-ip', false],
        ];
    }

    /**
     * @dataProvider globalAddressProvider
     */
    public function testIsGlobalAddress(string $address, bool $expected): void
    {
        $this->assertSame($expected, RecognitionTransport::is_global_address($address));
    }

    public function testResolvePinFormatsIpv4Ipv6AndDefaultPorts(): void
    {
        $this->assertSame(
            'api.example.test:443:93.184.216.34',
            RecognitionTransport::resolve_pin('api.example.test', 443, '93.184.216.34')
        );
        $this->assertSame(
            'api.example.test:80:93.184.216.34',
            RecognitionTransport::resolve_pin('api.example.test', 80, '93.184.216.34')
        );
        $this->assertSame(
            'api.example.test:443:[2001:4860::1]',
            RecognitionTransport::resolve_pin('api.example.test', 443, '2001:4860::1')
        );
    }

    private static function httpApiCurlActionCount(): int
    {
        $count = 0;
        foreach ($GLOBALS['__ac_actions']['http_api_curl'] ?? [] as $callbacks) {
            $count += count($callbacks);
        }

        return $count;
    }
}
