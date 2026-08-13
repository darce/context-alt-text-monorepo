<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClusterCurationWriter;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\ClusterCurationWriter
 */
class ClusterCurationWriterTest extends TestCase
{
    private ClusterCurationWriter $writer;

    protected function setUp(): void
    {
        parent::setUp();
        $this->writer = new ClusterCurationWriter('wp_acx_clusters');
    }

    public function testUpdateLabelRejectsReservedShape(): void
    {
        global $wpdb;

        $result = $this->writer->update_label('cluster-1', 'cluster-abcdef01');

        $this->assertSame(0, $result);
        $this->assertSame([], $wpdb->queries);
    }

    public function testUpdateLabelSetsUserConfirmedAndBumpsRevision(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->writer->update_label('cluster-123', 'Ada Lovelace');

        $this->assertSame(1, $result);
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString("UPDATE `wp_acx_clusters` SET label = 'Ada Lovelace'", $query);
        $this->assertStringContainsString('is_user_confirmed = 1', $query);
        $this->assertStringContainsString('local_revision = local_revision + 1', $query);
    }

    public function testDismissSetsUserConfirmedAndBumpsRevision(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->writer->dismiss('cluster-dismiss');

        $this->assertSame(1, $result);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString("curation_state = 'dismissed'", $query);
        $this->assertStringContainsString('is_user_confirmed = 1', $query);
        $this->assertStringContainsString('local_revision = local_revision + 1', $query);
    }

    public function testUndismissClearsUserConfirmedAndBumpsRevision(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->writer->undismiss('cluster-undismiss');

        $this->assertSame(1, $result);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString("curation_state = 'uncurated'", $query);
        $this->assertStringContainsString('is_user_confirmed = 0', $query);
        $this->assertStringContainsString('local_revision = local_revision + 1', $query);
    }

    public function testResetCurationClearsLabelAndUserConfirmed(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;

        $result = $this->writer->reset_curation('cluster-reset', self::currentTenantId());

        $this->assertSame(1, $result);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('label = NULL', $query);
        $this->assertStringContainsString('is_user_confirmed = 0', $query);
        $this->assertStringContainsString('local_revision = local_revision + 1', $query);
    }
}
