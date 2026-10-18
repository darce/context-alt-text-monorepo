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

    public function testReassignToClusterRefreshesAssignedAt(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->writer->reassign_to_cluster('identity-reassign', 'cluster-target');

        $this->assertSame(1, $result);
        $this->assertCount(1, $wpdb->queries);
        $sql = $wpdb->queries[0];
        $this->assertStringContainsString('assigned_at =', $sql);
        $this->assertStringContainsString("cluster_uuid = 'cluster-target'", $sql);
        $this->assertStringContainsString("identity_uuid = 'identity-reassign'", $sql);
    }

    public function testReassignClusterMembersRefreshesAssignedAt(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->writer->reassign_cluster_members('cluster-source', 'cluster-target');

        $this->assertSame(1, $result);
        $this->assertCount(1, $wpdb->queries);
        $sql = $wpdb->queries[0];
        $this->assertStringContainsString('assigned_at =', $sql);
        $this->assertStringContainsString("SET cluster_uuid = 'cluster-target'", $sql);
        $this->assertStringContainsString("WHERE cluster_uuid = 'cluster-source'", $sql);
    }
}
