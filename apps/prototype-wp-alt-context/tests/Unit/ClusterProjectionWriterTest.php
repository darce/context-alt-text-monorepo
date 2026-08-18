<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClusterProjectionWriter;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\ClusterProjectionWriter
 */
class ClusterProjectionWriterTest extends TestCase
{
    private ClusterProjectionWriter $writer;

    protected function setUp(): void
    {
        parent::setUp();
        $this->writer = new ClusterProjectionWriter('wp_acx_clusters');
    }

    public function testCreateLocalClusterSetsUserConfirmed(): void
    {
        global $wpdb;
        $wpdb->defaultInsertResult = 1;

        $result = $this->writer->create_local_cluster(
            self::currentTenantId(),
            'cluster-new',
            'Curated Label',
            3
        );

        $this->assertSame(1, $result);
        $this->assertStringContainsString('INSERT INTO wp_acx_clusters', $wpdb->queries[0]);

        // Assert the curation-marker value pairing, not just column presence:
        // a flipped is_user_confirmed or dropped local_revision bump must fail here.
        $row = $wpdb->tableRows['wp_acx_clusters'][0];
        $this->assertSame(1, $row['is_user_confirmed']);
        $this->assertSame(1, $row['local_revision']);
        $this->assertSame('uncurated', $row['curation_state']);
        $this->assertSame(0, $row['snapshot_version']);
        $this->assertSame(3, $row['identity_count']);
    }

    public function testUpsertProjectionClusterLeavesUserConfirmedUnset(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->writer->upsert_projection_cluster(
            self::currentTenantId(),
            'cluster-proj',
            'Projection Label',
            4,
            9
        );

        $this->assertSame(1, $result);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('INSERT INTO `wp_acx_clusters`', $query);
        $this->assertStringContainsString('ON DUPLICATE KEY UPDATE', $query);
        $this->assertStringContainsString('is_user_confirmed = VALUES(is_user_confirmed)', $query);
    }
}
