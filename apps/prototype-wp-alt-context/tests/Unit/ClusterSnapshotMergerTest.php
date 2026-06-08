<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClusterSnapshotMerger;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\ClusterSnapshotMerger
 */
class ClusterSnapshotMergerTest extends TestCase
{
    private ClusterSnapshotMerger $merger;

    protected function setUp(): void
    {
        parent::setUp();
        $this->merger = new ClusterSnapshotMerger('wp_acx_clusters');
    }

    public function testMergeSnapshotBatchUsesCurationSafeUpsert(): void
    {
        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-1',
                    'label' => 'Daniel',
                    'identity_count' => 4,
                ],
            ],
            14
        );

        global $wpdb;
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('INSERT INTO `wp_acx_clusters`', $query);
        $this->assertStringContainsString('label = IF(is_user_confirmed = 1, label, VALUES(label))', $query);
        $this->assertStringContainsString('snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version))', $query);
    }

    public function testPrepareSnapshotMergeDeletesStaleNonCuratedRows(): void
    {
        $this->merger->prepare_snapshot_merge_for_tenant('tenant-prune', ['cluster-keep']);

        global $wpdb;
        $this->assertCount(1, $wpdb->queries);
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('DELETE FROM `wp_acx_clusters`', $query);
        $this->assertStringContainsString('is_user_confirmed = 0', $query);
        $this->assertStringContainsString('cluster_uuid NOT IN', $query);
    }
}
