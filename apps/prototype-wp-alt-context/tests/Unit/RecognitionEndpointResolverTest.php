<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionEndpointResolver;
use AltContext\Support\LoopbackHost;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\RecognitionEndpointResolver
 */
class RecognitionEndpointResolverTest extends TestCase
{
    private RecognitionEndpointResolver $resolver;

    protected function setUp(): void
    {
        parent::setUp();
        $this->resolver = new RecognitionEndpointResolver();
    }

    public function testDefaultsToServiceTargetWhenNothingConfigured(): void
    {
        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('default', $snapshot['recognition_source_source']);
        $this->assertSame('service', $snapshot['effective_target_mode']);
        $this->assertSame('', $snapshot['effective_target_url']);
        // BR-138: genuinely unconfigured must not look like a rejected URL.
        $this->assertNull($snapshot['service_url_rejection_reason']);
        $this->assertNull($snapshot['service_url_rejection_source']);
        $this->assertNull($snapshot['service_url_rejection_value']);
    }

    /**
     * BR-139: shared LoopbackHost predicate — pin the full matrix, not one host.
     * Goes RED if the allowlist is widened (private IP / docker name / suffix)
     * or if bracket stripping for [::1] regresses.
     *
     * @dataProvider loopbackHostMatrixProvider
     */
    public function testLoopbackHostMatrix(string $host, bool $expected): void
    {
        require_once dirname(__DIR__, 2) . '/src/support/class-loopback-host.php';

        $this->assertSame(
            $expected,
            LoopbackHost::is_loopback($host),
            'LoopbackHost::is_loopback mismatch for host: ' . $host
        );
    }

    /**
     * @return array<string, array{0: string, 1: bool}>
     */
    public static function loopbackHostMatrixProvider(): array
    {
        return [
            'accepts_localhost' => ['localhost', true],
            'accepts_127_0_0_1' => ['127.0.0.1', true],
            'accepts_ipv6_loopback' => ['::1', true],
            'accepts_bracketed_ipv6_loopback' => ['[::1]', true],
            'rejects_private_ip' => ['10.0.0.5', false],
            'rejects_docker_service_name' => ['recognition', false],
            'rejects_localhost_suffix' => ['localhost.attacker.invalid', false],
            'rejects_loopback_dotted_suffix' => ['127.0.0.1.attacker.invalid', false],
            // Adversarial near-loopback forms from the oracle corpus — hardcoded
            // reject expectations so widening LoopbackHost::is_loopback goes red
            // even when the transport consistency pin moves with the predicate.
            'rejects_unspecified_ipv4' => ['0.0.0.0', false],
            'rejects_short_loopback_form' => ['127.1', false],
            'rejects_ipv4_mapped_loopback' => ['[::ffff:127.0.0.1]', false],
            'rejects_dword_loopback' => ['2130706433', false],
            'rejects_localhost_trailing_dot' => ['localhost.', false],
            'rejects_loopback_trailing_dot' => ['127.0.0.1.', false],
            'rejects_localhost_evil_suffix' => ['localhost.evil.test', false],
        ];
    }

    public function testServiceModeUsesStoredServiceUrl(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('https://api.altcontext.com', $snapshot['effective_target_url']);
    }

    /**
     * BR-131 / BR-135: http only for loopback — pin the *rule*, not one host.
     * Goes RED under the weakening
     * `return 'http' === $scheme && ( is_loopback_host( $host ) || 'attacker.invalid' !== $host )`.
     *
     * @dataProvider plaintextRemoteServiceUrlProvider
     */
    public function testRejectsPlaintextRemoteServiceUrl(string $url): void
    {
        $this->setOption('acx_recognition_url', $url);

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('', $snapshot['service_url'], 'rejected url must not resolve as service_url: ' . $url);
        $this->assertSame('default', $snapshot['service_url_source']);
        $this->assertSame('', $snapshot['effective_target_url'], 'rejected url must not become effective target: ' . $url);
        // BR-138: rejection is reported, not silently collapsed to unconfigured.
        $this->assertSame(
            RecognitionEndpointResolver::URL_REJECTION_NON_LOOPBACK_HTTP,
            $snapshot['service_url_rejection_reason'],
            'plaintext remote must report non_loopback_http: ' . $url
        );
        $this->assertSame('option', $snapshot['service_url_rejection_source']);
        $this->assertSame($url, $snapshot['service_url_rejection_value']);
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function plaintextRemoteServiceUrlProvider(): array
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
     * BR-131 / BR-135: accepted side of the rule — loopback http and any https.
     *
     * @dataProvider acceptedServiceUrlProvider
     */
    public function testAcceptsLoopbackHttpAndHttpsServiceUrl(string $url): void
    {
        $this->setOption('acx_recognition_url', $url);

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame($url, $snapshot['service_url'], 'accepted url must resolve: ' . $url);
        $this->assertSame('option', $snapshot['service_url_source']);
        $this->assertSame($url, $snapshot['effective_target_url']);
        $this->assertNull($snapshot['service_url_rejection_reason'], 'accepted url must not carry rejection: ' . $url);
        $this->assertNull($snapshot['service_url_rejection_source']);
        $this->assertNull($snapshot['service_url_rejection_value']);
    }

    /**
     * BR-138: a rejected constant / filter / option each produce a snapshot
     * distinguishable from the genuinely-unconfigured case and from each other.
     *
     * @dataProvider rejectedServiceUrlTierProvider
     */
    public function testRejectedServiceUrlReportsTierAndReason(
        string $tier,
        string $url,
        string $expectedReason
    ): void {
        if ('option' === $tier) {
            $this->setOption('acx_recognition_url', $url);
        } elseif ('filter' === $tier) {
            add_filter('acx_recognition_base_url', static fn (): string => $url);
        } else {
            $this->fail('constant tier is covered by a separate-process test');
        }

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('', $snapshot['service_url']);
        $this->assertSame('default', $snapshot['service_url_source']);
        $this->assertSame('', $snapshot['effective_target_url']);
        $this->assertSame($expectedReason, $snapshot['service_url_rejection_reason']);
        $this->assertSame($tier, $snapshot['service_url_rejection_source']);
        $this->assertSame($url, $snapshot['service_url_rejection_value']);
    }

    /**
     * @return array<string, array{0: string, 1: string, 2: string}>
     */
    public static function rejectedServiceUrlTierProvider(): array
    {
        return [
            'option_non_loopback_http' => [
                'option',
                'http://10.0.0.5:8000',
                RecognitionEndpointResolver::URL_REJECTION_NON_LOOPBACK_HTTP,
            ],
            'filter_non_loopback_http' => [
                'filter',
                'http://recognition:8000',
                RecognitionEndpointResolver::URL_REJECTION_NON_LOOPBACK_HTTP,
            ],
            'option_rejected_scheme' => [
                'option',
                'ftp://files.example.com/v1',
                RecognitionEndpointResolver::URL_REJECTION_REJECTED_SCHEME,
            ],
            'filter_invalid_url' => [
                'filter',
                'not-a-url',
                RecognitionEndpointResolver::URL_REJECTION_INVALID_URL,
            ],
        ];
    }

    /**
     * BR-138: rejected constant tier is distinguishable from filter/option.
     *
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testRejectedConstantServiceUrlReportsConstantTier(): void
    {
        if (!defined('ACX_RECOGNITION_URL')) {
            define('ACX_RECOGNITION_URL', 'http://host.docker.internal:8000');
        }

        $resolver = new RecognitionEndpointResolver();
        $snapshot = $resolver->resolve_settings_snapshot();

        $this->assertSame('', $snapshot['service_url']);
        $this->assertSame('default', $snapshot['service_url_source']);
        $this->assertSame(
            RecognitionEndpointResolver::URL_REJECTION_NON_LOOPBACK_HTTP,
            $snapshot['service_url_rejection_reason']
        );
        $this->assertSame('constant', $snapshot['service_url_rejection_source']);
        $this->assertSame('http://host.docker.internal:8000', $snapshot['service_url_rejection_value']);
    }

    /**
     * BR-138: when a higher tier is rejected but a lower tier is valid, the
     * valid URL wins and no rejection is surfaced (reporting is for the empty
     * effective-target case only).
     */
    public function testValidLowerTierWinsOverRejectedHigherTier(): void
    {
        add_filter(
            'acx_recognition_base_url',
            static fn (): string => 'http://10.0.0.5:8000'
        );
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('https://api.altcontext.com', $snapshot['service_url']);
        $this->assertSame('option', $snapshot['service_url_source']);
        $this->assertNull($snapshot['service_url_rejection_reason']);
        $this->assertNull($snapshot['service_url_rejection_source']);
        $this->assertNull($snapshot['service_url_rejection_value']);
    }

    /**
     * BR-138: highest-precedence rejected tier wins the diagnostic when all
     * present values fail validation (constant > filter > option).
     */
    public function testHighestPrecedenceRejectionWinsWhenAllTiersFail(): void
    {
        add_filter(
            'acx_recognition_base_url',
            static fn (): string => 'http://filter.internal:8000'
        );
        $this->setOption('acx_recognition_url', 'http://option.internal:8000');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('', $snapshot['service_url']);
        $this->assertSame('filter', $snapshot['service_url_rejection_source']);
        $this->assertSame('http://filter.internal:8000', $snapshot['service_url_rejection_value']);
        $this->assertSame(
            RecognitionEndpointResolver::URL_REJECTION_NON_LOOPBACK_HTTP,
            $snapshot['service_url_rejection_reason']
        );
    }

    /**
     * @return array<string, array{0: string}>
     */
    public static function acceptedServiceUrlProvider(): array
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

    public function testFilterSourcedServiceUrlResolvesService(): void
    {
        add_filter(
            'acx_recognition_base_url',
            static fn(): string => 'https://filter.example.com'
        );

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('default', $snapshot['recognition_source_source']);
        $this->assertSame('https://filter.example.com', $snapshot['effective_target_url']);
        $this->assertSame('filter', $snapshot['service_url_source']);
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testConstantServiceUrlResolvesService(): void
    {
        if (!defined('ACX_RECOGNITION_URL')) {
            define('ACX_RECOGNITION_URL', 'https://constant.example.com');
        }

        $resolver = new RecognitionEndpointResolver();
        $snapshot = $resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('default', $snapshot['recognition_source_source']);
        $this->assertSame('https://constant.example.com', $snapshot['effective_target_url']);
        $this->assertSame('constant', $snapshot['service_url_source']);
    }

    /**
     * RECOG-1: the option tier for recognition_source is retired. A stale
     * acx_recognition_source='local' option must be ignored and resolve to the
     * service default (the documented upgrade transition).
     */
    public function testStoredSourceOptionIsIgnoredAfterRetirement(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');
        $this->setOption('acx_recognition_source', 'local');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('default', $snapshot['recognition_source_source']);
        $this->assertSame('https://api.altcontext.com', $snapshot['effective_target_url']);
    }

    /**
     * RECOG-1: the option tier for local_url is retired. A stored
     * acx_recognition_local_url option must be ignored; the dev hatch falls back
     * to the constant/filter/default chain only.
     */
    public function testStoredLocalUrlOptionIsIgnoredAfterRetirement(): void
    {
        add_filter('acx_recognition_source', static fn(): string => 'local');
        $this->setOption('acx_recognition_local_url', 'http://localhost:8001');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('http://localhost:8000', $snapshot['effective_target_url']);
    }

    /**
     * Dev hatch (filter tier): local remains reachable via the
     * acx_recognition_source filter even though the product no longer writes it.
     */
    public function testFilterSourcedRecognitionSourceEnablesLocalHatch(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');
        add_filter('acx_recognition_source', static fn(): string => 'local');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('filter', $snapshot['recognition_source_source']);
        $this->assertSame('http://localhost:8000', $snapshot['effective_target_url']);
    }

    /**
     * Dev hatch (constant tier): ACX_RECOGNITION_SOURCE=local still selects local
     * and overrides an otherwise service-default install.
     *
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testConstantRecognitionSourceEnablesLocalHatch(): void
    {
        if (!defined('ACX_RECOGNITION_SOURCE')) {
            define('ACX_RECOGNITION_SOURCE', 'local');
        }

        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');

        $resolver = new RecognitionEndpointResolver();
        $snapshot = $resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('constant', $snapshot['recognition_source_source']);
        $this->assertSame('http://localhost:8000', $snapshot['effective_target_url']);
    }

    /**
     * Dev hatch full form: ACX_RECOGNITION_SOURCE=local + ACX_RECOGNITION_LOCAL_URL
     * routes to the constant-supplied local URL.
     *
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testConstantLocalUrlHatchRoutesToConstantUrl(): void
    {
        if (!defined('ACX_RECOGNITION_SOURCE')) {
            define('ACX_RECOGNITION_SOURCE', 'local');
        }
        if (!defined('ACX_RECOGNITION_LOCAL_URL')) {
            define('ACX_RECOGNITION_LOCAL_URL', 'http://localhost:8001');
        }

        $resolver = new RecognitionEndpointResolver();
        $snapshot = $resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('http://localhost:8001', $snapshot['effective_target_url']);
        $this->assertSame('http://localhost:8001', $resolver->get_effective_base_url());
    }

    /**
     * Constant source tier still precedes the filter tier.
     *
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testConstantRecognitionSourcePrecedesFilter(): void
    {
        if (!defined('ACX_RECOGNITION_SOURCE')) {
            define('ACX_RECOGNITION_SOURCE', 'service');
        }

        add_filter('acx_recognition_source', static fn(): string => 'local');
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');

        $resolver = new RecognitionEndpointResolver();
        $snapshot = $resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('constant', $snapshot['recognition_source_source']);
        $this->assertSame('https://api.altcontext.com', $snapshot['effective_target_url']);
    }
}
