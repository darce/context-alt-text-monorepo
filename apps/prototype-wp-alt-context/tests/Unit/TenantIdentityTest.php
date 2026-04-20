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
