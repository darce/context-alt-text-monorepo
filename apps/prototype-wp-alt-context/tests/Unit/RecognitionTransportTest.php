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
    }

    /**
     * Non-loopback hosts must take the safe transport. A fixture-host-only
     * implementation (api.example.test hard-code) goes RED on other public hosts.
     *
     * @dataProvider nonLoopbackHostProvider
     */
    public function testGetUsesSafeTransportForNonLoopbackHosts(string $url): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'ok',
        ]);

        RecognitionTransport::get($url, ['headers' => ['X-API-Key' => 'k'], 'timeout' => 5]);

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
    public function testRequestUsesSafeTransportForNonLoopbackHosts(string $url): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => 'ok',
        ]);

        RecognitionTransport::request($url, [
            'method' => 'GET',
            'headers' => ['X-API-Key' => 'k'],
            'timeout' => 5,
        ]);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertTrue(
            !empty($calls[0]['safe']),
            'non-loopback request must use wp_safe_remote_request; host=' . parse_url($url, PHP_URL_HOST)
        );
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function nonLoopbackHostProvider(): array
    {
        return [
            'public_dns' => ['https://api.example.test/health'],
            'unrelated_tld' => ['https://cdn.other-org.example/v1'],
            'bare_public_ipv4' => ['https://203.0.113.10/probe'],
            'bracketed_ipv6' => ['https://[2001:db8::1]/probe'],
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
     * chooser. Expectations are literal true/false — never derived from
     * LoopbackHost::is_loopback — so a predicate widen moves the chooser red
     * here even when the consistency oracle still agrees with itself.
     *
     * Covers the four loopback forms, the adversarial near-loopback set from
     * the oracle corpus, and userinfo-bearing hosts (parse_url host extraction).
     *
     * @dataProvider transportSafeChoiceHardcodedProvider
     */
    public function testTransportSafeChoiceHardcodedExpectations(string $url, bool $expectedPlain): void
    {
        foreach (['get', 'request'] as $method) {
            $GLOBALS['__ac_http_calls'] = [];
            $this->queueHttpResponse([
                'response' => ['code' => 200, 'message' => 'OK'],
                'body' => 'ok',
            ]);

            if ('get' === $method) {
                RecognitionTransport::get($url, ['timeout' => 5]);
            } else {
                RecognitionTransport::request($url, ['method' => 'GET', 'timeout' => 5]);
            }

            $calls = $this->getHttpCalls();
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
     * @return array<string, array{0: string, 1: bool}>
     */
    public static function transportSafeChoiceHardcodedProvider(): array
    {
        return [
            // Four loopback forms — must take plain transport (expectedPlain=true).
            'loopback_localhost' => ['http://localhost:8000/health', true],
            'loopback_ipv4' => ['http://127.0.0.1:8000/health', true],
            'loopback_ipv6_bare_bracketed_in_url' => ['http://[::1]:8000/health', true],
            'loopback_ipv6_bracketed' => ['https://[::1]/oracle-probe', true],
            // Adversarial near-loopback — must take safe transport (expectedPlain=false).
            'reject_0_0_0_0' => ['https://0.0.0.0/oracle-probe', false],
            'reject_127_1' => ['https://127.1/oracle-probe', false],
            'reject_ipv4_mapped' => ['https://[::ffff:127.0.0.1]/oracle-probe', false],
            'reject_dword' => ['https://2130706433/oracle-probe', false],
            'reject_localhost_trailing_dot' => ['https://localhost./oracle-probe', false],
            'reject_loopback_trailing_dot' => ['https://127.0.0.1./oracle-probe', false],
            'reject_localhost_evil' => ['https://localhost.evil.test/oracle-probe', false],
            // Userinfo-bearing: parse_url host is evil.test, not localhost.
            'reject_userinfo_localhost_at_evil' => ['https://localhost@evil.test/oracle-probe', false],
        ];
    }

    /**
     * R5G-BR-03 / [TEST-15]: consistency pin — transport safe-vs-plain must
     * agree with LoopbackHost::is_loopback for a large programmatically
     * generated host corpus (anti-allowlist device). Expected values are
     * computed from the same parse_url-extracted, lowercased host the
     * transport uses, so corpus input and transport input agree (e.g.
     * userinfo-bearing hosts). Correctness of the loopback set is pinned by
     * the hardcoded table and RecognitionEndpointResolverTest matrix, not here.
     */
    public function testTransportSafeChoiceAgreesWithLoopbackHostOracle(): void
    {
        $hosts = self::generateOracleHostCorpus();
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

            foreach (['get', 'request'] as $method) {
                $GLOBALS['__ac_http_calls'] = [];
                $this->queueHttpResponse([
                    'response' => ['code' => 200, 'message' => 'OK'],
                    'body' => 'ok',
                ]);

                if ('get' === $method) {
                    RecognitionTransport::get($url, ['timeout' => 5]);
                } else {
                    RecognitionTransport::request($url, ['method' => 'GET', 'timeout' => 5]);
                }

                $calls = $this->getHttpCalls();
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
     * Programmatic host corpus: public DNS names, unrelated TLDs, bare IPv4,
     * bracketed IPv6, plus the loopback forms. Not a hand-written allowlist.
     * Userinfo-bearing and other adversarial forms that need hardcoded
     * expectations live in transportSafeChoiceHardcodedProvider.
     *
     * @return list<string>
     */
    private static function generateOracleHostCorpus(): array
    {
        $hosts = [];

        // Public DNS names over several TLD / label shapes.
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

        // Bare public / documentation IPv4 ranges (RFC 5737 + misc non-loopback).
        foreach ([10, 20, 30, 40, 50, 100, 113, 200] as $third) {
            $hosts[] = '203.0.' . $third . '.10';
            $hosts[] = '198.51.100.' . $third;
            $hosts[] = '192.0.2.' . $third;
        }

        // Bracketed documentation / non-loopback IPv6.
        foreach (['1', '2', 'a', 'f', '10', 'ff'] as $nibble) {
            $hosts[] = '[2001:db8::' . $nibble . ']';
            $hosts[] = '[2001:db8:1::' . $nibble . ']';
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
}
