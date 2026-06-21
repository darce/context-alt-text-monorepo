<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\IdentityMemberCurationWriter;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\IdentityMemberCurationWriter
 */
class IdentityMemberCurationWriterTest extends TestCase
{
    private IdentityMemberCurationWriter $writer;

    protected function setUp(): void
    {
        parent::setUp();
        $this->writer = new IdentityMemberCurationWriter('wp_acx_identity_members', 'wp_acx_clusters');
    }

    public function testResetCurationScopesByTenant(): void
    {
        $this->writer->reset_curation('identity-reset-writer', 'tenant-reset-writer');

        global $wpdb;
        $sql = implode("\n", $wpdb->queries);
        $this->assertStringContainsString('SET m.is_curated = 0', $sql);
        $this->assertStringContainsString("'tenant-reset-writer'", $sql);
    }
}
