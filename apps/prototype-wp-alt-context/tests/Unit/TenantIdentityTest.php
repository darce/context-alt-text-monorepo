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
    protected function setUp(): void
    {
        parent::setUp();
        // Opt-in update_option failure map is not cleared by TestCase::resetGlobalState.
        $GLOBALS['__ac_update_option_fail'] = [];
    }

    public function testDerivationIsDeterministic(): void
    {
        $first  = TenantIdentity::resolve();
        $second = TenantIdentity::resolve();

        $this->assertSame($first['value'], $second['value']);
    }

    public function testDerivationMatchesExpectedUuidForStubSite(): void
    {
        $resolution = TenantIdentity::resolve();

        // Pinned golden literal for site URL http://example.com. Hardcoded (not recomputed) so a
        // change to the derivation algorithm shifts every tenant id and is caught here, since the
        // tenant id is the cross-repo partition key for all recognition data.
        $this->assertSame('33380427-1819-5ad2-922b-cdd246fac3a0', $resolution['value']);
        // Belt-and-suspenders: the reusable helper must agree with the pinned literal.
        $this->assertSame('33380427-1819-5ad2-922b-cdd246fac3a0', $this->expectedUuidFor('http://example.com'));
    }

    public function testDerivationProducesV5ShapedUuid(): void
    {
        $resolution = TenantIdentity::resolve();

        $this->assertMatchesRegularExpression(
            '/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i',
            $resolution['value']
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
        $this->assertTrue(
            $this->errorLogContains('ignoring malformed option tenant id override'),
            'malformed option override must emit a warning'
        );
    }

    public function testResolveRejectsMalformedFilterAndFallsThroughToOption(): void
    {
        $validOption = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        $this->setOption('acx_recognition_tenant_id', $validOption);
        add_filter('acx_recognition_tenant_id', static fn () => 'not-a-uuid');

        $resolution = TenantIdentity::resolve();

        $this->assertSame($validOption, $resolution['value']);
        $this->assertSame('option', $resolution['source']);
        $this->assertTrue(
            $this->errorLogContains('ignoring malformed filter tenant id override'),
            'malformed filter override must emit a warning before falling through'
        );
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testResolveRejectsMalformedConstantAndFallsThrough(): void
    {
        require_once __DIR__ . '/../bootstrap.php';
        $this->resetGlobalState();

        $validOption = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
        define('ACX_RECOGNITION_TENANT_ID', 'not-a-uuid');
        $this->setOption('acx_recognition_tenant_id', $validOption);

        $resolution = TenantIdentity::resolve();

        $this->assertSame($validOption, $resolution['value']);
        $this->assertSame('option', $resolution['source']);
        $this->assertTrue(
            $this->errorLogContains('ignoring malformed constant tenant id override'),
            'malformed constant override must emit a warning before falling through'
        );
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testResolveDropsNonStringConstantWithWarning(): void
    {
        require_once __DIR__ . '/../bootstrap.php';
        $this->resetGlobalState();

        define('ACX_RECOGNITION_TENANT_ID', true);

        $resolution = TenantIdentity::resolve();

        // Non-string constant is ignored and we fall through to derivation.
        $this->assertSame('derived', $resolution['source']);
        $this->assertTrue(
            $this->errorLogContains('ignoring malformed constant tenant id override'),
            'non-string constant override must emit a warning'
        );
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

    /**
     * R23-BR-15 [TEST-15]: tenant-id write failure must throw and must not set
     * the paired flag. Pin reds if PAIRED_OPTION_KEY is written before read-back.
     */
    public function testAdoptPairedTenantThrowsAndSkipsPairedFlagWhenWriteFails(): void
    {
        $tenant = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
        $GLOBALS['__ac_update_option_fail'] = [
            TenantIdentity::OPTION_KEY => true,
        ];

        try {
            TenantIdentity::adopt_paired_tenant($tenant);
            $this->fail('Expected RuntimeException when tenant id write does not land');
        } catch (\RuntimeException $e) {
            $this->assertStringContainsString('paired tenant id', $e->getMessage());
        }

        $this->assertFalse(
            TenantIdentity::is_paired(),
            'paired flag must not be set when tenant id did not persist'
        );
        $this->assertNotSame(
            $tenant,
            get_option(TenantIdentity::OPTION_KEY, null),
            'failed write must not leave the intended tenant id in storage'
        );
    }

    /**
     * R23-BR-15 [TEST-15] leg 2: paired-flag write failure must throw, leave
     * is_paired() false, and keep the verified tenant id in storage (safe state;
     * do not roll back leg 1).
     *
     * Fail-message note: AssertionFailedError extends RuntimeException in PHPUnit,
     * so the fail() text must not contain the production pin phrase or a missing
     * throw is swallowed as a false green (the exact trap that burned the prior
     * "BR-15 fixed" claim on leg 1 only). Pin against the production throw text.
     */
    public function testAdoptPairedTenantThrowsWhenPairedFlagWriteFails(): void
    {
        $tenant = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
        $GLOBALS['__ac_update_option_fail'] = [
            TenantIdentity::PAIRED_OPTION_KEY => true,
        ];

        try {
            TenantIdentity::adopt_paired_tenant($tenant);
            $this->fail('Expected RuntimeException when PAIRED_OPTION_KEY write does not land');
        } catch (\RuntimeException $e) {
            // Pin phrase is the production throw text — must not appear in fail() above.
            $this->assertStringContainsString(
                'Could not persist the paired flag',
                $e->getMessage()
            );
            $this->assertStringNotContainsString('paired tenant id', $e->getMessage());
        }

        $this->assertFalse(
            TenantIdentity::is_paired(),
            'paired flag must not be set when the paired-flag write failed'
        );
        $this->assertSame(
            $tenant,
            get_option(TenantIdentity::OPTION_KEY, null),
            'verified tenant id must remain stored when only the paired flag fails'
        );
    }

    /**
     * R23-BR-15 false-failure pin: re-adopting the already-stored tenant id is
     * a no-op for update_option (returns false) but must still succeed and set
     * the paired flag. A return-value check would break re-pairing.
     */
    public function testAdoptPairedTenantSucceedsOnNoOpWhenTenantAlreadyStored(): void
    {
        $tenant = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
        $this->setOption(TenantIdentity::OPTION_KEY, $tenant);
        $this->assertFalse(TenantIdentity::is_paired());

        TenantIdentity::adopt_paired_tenant($tenant);

        $this->assertTrue(TenantIdentity::is_paired());
        $this->assertSame($tenant, get_option(TenantIdentity::OPTION_KEY));
    }

    /**
     * R23-BR-15 false-failure pin: first-time adopt of a new tenant still works.
     */
    public function testAdoptPairedTenantPersistsNewTenantAndSetsPairedFlag(): void
    {
        $tenant = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

        TenantIdentity::adopt_paired_tenant($tenant);

        $this->assertSame($tenant, get_option(TenantIdentity::OPTION_KEY));
        $this->assertTrue(TenantIdentity::is_paired());
    }

    /**
     * R23-BR-15: storage failure is RuntimeException, not InvalidArgumentException.
     */
    public function testAdoptPairedTenantMalformedUuidStillThrowsInvalidArgument(): void
    {
        $this->expectException(\InvalidArgumentException::class);
        TenantIdentity::adopt_paired_tenant('not-a-uuid');
    }

    private function errorLogContains(string $needle): bool
    {
        foreach ($this->getErrorLog() as $entry) {
            if (str_contains((string) $entry, $needle)) {
                return true;
            }
        }

        return false;
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
