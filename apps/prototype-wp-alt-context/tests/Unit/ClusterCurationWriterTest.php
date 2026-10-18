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

    public function testBindPersonToClusterReturnsFalseOnUpdateFailure(): void
    {
        global $wpdb;

        $wpdb->defaultUpdateResult = false;
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-bind',
                'tenant_id' => self::currentTenantId(),
                'person_id' => null,
            ],
        ];

        $result = $this->writer->bind_person_to_cluster('cluster-bind', 9, self::currentTenantId(), false);

        $this->assertFalse($result);
    }

    public function testBindPersonToClusterDoesNotTouchOtherTenantRow(): void
    {
        global $wpdb;

        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'shared-uuid',
                'tenant_id' => 'tenant-a',
                'person_id' => 1,
            ],
            [
                'cluster_uuid' => 'shared-uuid',
                'tenant_id' => 'tenant-b',
                'person_id' => 2,
            ],
        ];

        $result = $this->writer->bind_person_to_cluster('shared-uuid', 99, 'tenant-a', false);

        $this->assertSame(1, $result);
        $this->assertSame(99, $wpdb->tableRows['wp_acx_clusters'][0]['person_id']);
        $this->assertSame(2, $wpdb->tableRows['wp_acx_clusters'][1]['person_id']);
    }

    public function testResetCurationClearsLabelAndUserConfirmed(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = 1;
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-reset',
                'tenant_id' => self::currentTenantId(),
                'label' => 'Tory',
                'person_id' => 4,
                'is_user_confirmed' => 1,
                'local_revision' => 3,
                'snapshot_version' => 14,
                'curation_state' => 'confirmed',
            ],
        ];

        $result = $this->writer->reset_curation('cluster-reset', self::currentTenantId());

        $this->assertSame(1, $result);
        $updates = array_values(array_filter(
            $wpdb->queries,
            static fn(string $query): bool => str_starts_with($query, 'UPDATE')
        ));
        $this->assertCount(1, $updates, 'reset_curation must be a single UPDATE');
        $this->assertStringContainsString('label = NULL', $updates[0]);
        $this->assertStringContainsString('person_id = NULL', $updates[0]);
        $this->assertStringContainsString('is_user_confirmed = 0', $updates[0]);
        $this->assertStringContainsString('local_revision = local_revision + 1', $updates[0]);
        $this->assertStringContainsString('label_cleared_revision = snapshot_version', $updates[0]);
    }

    public function testResetCurationReturnsZeroWhenNoRowMatches(): void
    {
        global $wpdb;
        $wpdb->tableRows['wp_acx_clusters'] = [];

        $result = $this->writer->reset_curation('missing-cluster', self::currentTenantId());

        $this->assertSame(0, $result);
    }

    public function testResetCurationReturnsFalseOnQueryFailure(): void
    {
        global $wpdb;
        $wpdb->defaultQueryResult = false;

        $result = $this->writer->reset_curation('cluster-reset', self::currentTenantId());

        $this->assertFalse($result);
    }
}
