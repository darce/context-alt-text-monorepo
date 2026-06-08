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

    public function testMergeBatchCoercesActiveCurationStateToUncurated(): void
    {
        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-active',
                    'label' => 'Daniel',
                    'curation_state' => 'active',
                    'identity_count' => 2,
                ],
            ],
            14
        );

        global $wpdb;
        $query = $wpdb->queries[0];
        // normalize_curation_state maps the legacy 'active' to 'uncurated' in the
        // emitted VALUES — guard the coercion, not just the column name.
        $this->assertStringContainsString("'uncurated'", $query);
        $this->assertStringNotContainsString("'active'", $query);
    }

    public function testMergeBatchResolvesNormalizerFallbacks(): void
    {
        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-fallback',
                    'label' => 'Edge',
                    // identity_count absent -> count(members) == 3
                    'members' => [[], [], []],
                    // representative_* absent -> derived from representatives[0]
                    'representatives' => [
                        ['thumb_path' => '/r.jpg', 'id' => 'rep-1'],
                    ],
                    // string flags coerced to 1
                    'is_user_confirmed' => 'yes',
                    'is_pinned' => 'on',
                ],
            ],
            20
        );

        global $wpdb;
        $query = $wpdb->queries[0];
        $this->assertStringContainsString("'/r.jpg'", $query);
        // VALUES tuple: ..., representative_id, is_pinned, identity_count, snapshot_version, is_user_confirmed, ...
        $this->assertStringContainsString("'rep-1', 1, 3, 20, 1,", $query);
    }

    public function testMergeBatchDerivesThumbKeyFromRepresentativeMediaId(): void
    {
        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-thumb',
                    'label' => 'Thumbed',
                    'identity_count' => 1,
                    // no thumb_path on the representative -> build_thumb_key from media_id
                    'representatives' => [
                        ['media_id' => 42],
                    ],
                ],
            ],
            5
        );

        global $wpdb;
        $query = $wpdb->queries[0];
        $this->assertStringContainsString("'acx://cluster/cluster-thumb/media/42'", $query);
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
