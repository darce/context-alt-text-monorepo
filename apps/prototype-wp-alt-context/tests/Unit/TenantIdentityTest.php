<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\TenantIdentity;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\TenantIdentity
 */
class TenantIdentityTest extends TestCase
{
    public function testDerivationIsDeterministic(): void
    {
        $this->assertSame(
            TenantIdentity::derive_from_site_url(),
            TenantIdentity::derive_from_site_url(),
            'derive_from_site_url must be idempotent for the same site URL'
        );
    }

    public function testDerivationMatchesExpectedUuidForStubSite(): void
    {
        // The test stub fixes get_site_url() to http://example.com. The SHA-1 of
        // 'acx-site-tenant:http://example.com' is computed deterministically; we
        // pin it here so any future refactor of the derivation must either keep
        // the canonical output or explicitly rev this constant (which is a
        // cross-repo wire-contract change — every persisted recognition row is
        // keyed on this tenant UUID).
        $this->assertSame(
            $this->expectedUuidFor('http://example.com'),
            TenantIdentity::derive_from_site_url()
        );
    }

    public function testDerivationProducesV5ShapedUuid(): void
    {
        $this->assertMatchesRegularExpression(
            '/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i',
            TenantIdentity::derive_from_site_url()
        );
    }

    public function testResolveDerivesAndPersistsWhenOptionEmpty(): void
    {
        $expected = $this->expectedUuidFor('http://example.com');

        $resolution = TenantIdentity::resolve();

        $this->assertSame($expected, $resolution['value']);
        $this->assertSame('derived', $resolution['source']);
        $this->assertSame($expected, $GLOBALS['__ac_options']['acx_recognition_tenant_id'] ?? null);
    }

    public function testResolveReadsPersistedOptionOnSecondCall(): void
    {
        $first = TenantIdentity::resolve();
        $this->assertSame('derived', $first['source']);

        $second = TenantIdentity::resolve();

        $this->assertSame($first['value'], $second['value']);
        $this->assertSame('option', $second['source']);
    }

    public function testResolveReturnsPersistedOptionWithoutReDeriving(): void
    {
        $persisted = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        $this->setOption('acx_recognition_tenant_id', $persisted);
        $GLOBALS['__ac_site_url'] = 'http://localhost:10010';

        $resolution = TenantIdentity::resolve();

        $this->assertSame($persisted, $resolution['value']);
        $this->assertSame('option', $resolution['source']);
    }

    public function testResolveFilterWinsOverOption(): void
    {
        $filterTenant = 'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee';
        $this->setOption('acx_recognition_tenant_id', 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');
        add_filter('acx_recognition_tenant_id', static fn () => $filterTenant);

        $resolution = TenantIdentity::resolve();

        $this->assertSame($filterTenant, $resolution['value']);
        $this->assertSame('filter', $resolution['source']);
    }

    public function testResolveRejectsMalformedOptionAndDerives(): void
    {
        $this->setOption('acx_recognition_tenant_id', 'not-a-uuid');
        $expected = $this->expectedUuidFor('http://example.com');

        $resolution = TenantIdentity::resolve();

        $this->assertSame($expected, $resolution['value']);
        $this->assertSame('derived', $resolution['source']);
        $this->assertSame('not-a-uuid', $GLOBALS['__ac_options']['acx_recognition_tenant_id']);
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testResolveConstantWinsOverFilterAndOption(): void
    {
        require_once __DIR__ . '/../bootstrap.php';
        $this->resetGlobalState();

        $constantTenant = 'cccccccc-bbbb-cccc-dddd-eeeeeeeeeeee';
        define('ACX_RECOGNITION_TENANT_ID', $constantTenant);
        $this->setOption('acx_recognition_tenant_id', 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');
        add_filter('acx_recognition_tenant_id', static fn () => 'bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee');

        $resolution = TenantIdentity::resolve();

        $this->assertSame($constantTenant, $resolution['value']);
        $this->assertSame('constant', $resolution['source']);
    }

    private function expectedUuidFor(string $siteUrl): string
    {
        $hash      = sha1('acx-site-tenant:' . strtolower(rtrim($siteUrl, '/')));
        $time_hi   = (hexdec(substr($hash, 12, 4)) & 0x0fff) | 0x5000;
        $clock_seq = (hexdec(substr($hash, 16, 4)) & 0x3fff) | 0x8000;

        return sprintf(
            '%s-%s-%04x-%04x-%s',
            substr($hash, 0, 8),
            substr($hash, 8, 4),
            $time_hi,
            $clock_seq,
            substr($hash, 20, 12)
        );
    }
}
