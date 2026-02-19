<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\SnapshotProjector;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Sync\SnapshotProjector
 * @covers \AltContext\Sovereign\Repositories\ClustersRepository
 * @covers \AltContext\Sovereign\Repositories\IdentityMembersRepository
 * @covers \AltContext\Sovereign\Repositories\SyncStateRepository
 */
class SovereignProjectionIntegrationTest extends TestCase
{
    public function testFixtureSnapshotProjectionWritesExpectedReadModelRowPayloads(): void
    {
        $projector = new SnapshotProjector(
            new ClustersRepository(),
            new IdentityMembersRepository(),
            new SyncStateRepository()
        );

        $projector->project(
            'tenant-integration',
            [
                'snapshot_version' => 31,
                'clusters' => [
                    [
                        'cluster_uuid' => 'cluster-int-1',
                        'label' => 'Daniel',
                        'curation_state' => 'confirmed',
                        'is_user_confirmed' => true,
                        'identity_count' => 2,
                        'representative_media_id' => 901,
                    ],
                ],
                'members' => [
                    [
                        'identity_uuid' => 'identity-int-1',
                        'cluster_uuid' => 'cluster-int-1',
                        'attachment_id' => 901,
                        'bbox' => [
                            'x' => 10,
                            'y' => 20,
                            'width' => 50,
                            'height' => 60,
                        ],
                        'image_width' => 1000,
                        'image_height' => 800,
                        'similarity' => 0.91,
                    ],
                ],
            ]
        );

        global $wpdb;
        $queries = $wpdb->queries;
        $sql = implode("\n", $queries);

        $this->assertStringContainsString('START TRANSACTION', $sql);
        $this->assertStringContainsString('COMMIT', $sql);

        $clusterInsert = $this->findQueryContaining($queries, 'INSERT INTO `wp_acx_clusters`');
        $this->assertStringContainsString("'cluster-int-1'", $clusterInsert);
        $this->assertStringContainsString("'tenant-integration'", $clusterInsert);
        $this->assertStringContainsString("'Daniel'", $clusterInsert);
        $this->assertStringContainsString("'confirmed'", $clusterInsert);
        $this->assertStringContainsString("'acx://cluster/cluster-int-1/media/901'", $clusterInsert);
        $this->assertStringContainsString(', 2, 31, 1,', $clusterInsert);

        $memberInsert = $this->findQueryContaining($queries, 'INSERT INTO `wp_acx_identity_members`');
        $this->assertStringContainsString("SELECT 'identity-int-1', 'cluster-int-1', 901", $memberInsert);
        $this->assertStringContainsString('\\"pixels\\":{\\"x\\":10,\\"y\\":20,\\"width\\":50,\\"height\\":60}', $memberInsert);
        $this->assertStringContainsString('\\"normalized\\":{\\"x\\":0.01,\\"y\\":0.025,\\"width\\":0.05,\\"height\\":0.075}', $memberInsert);
        $this->assertStringContainsString("NULLIF('0.91', '')", $memberInsert);

        $syncInsert = $this->findQueryContaining($queries, 'INSERT INTO `wp_acx_sync_state`');
        $this->assertStringContainsString("'tenant:tenant-integration:clusters'", $syncInsert);
        $this->assertStringContainsString(', 31,', $syncInsert);
    }

    /**
     * Verifies that user-curated labels survive a subsequent snapshot projection.
     *
     * The SQL uses `IF(is_user_confirmed = 1, label, VALUES(label))` so that once
     * a cluster is user-confirmed the snapshot cannot overwrite the label.
     */
    public function testSnapshotPreservesUserCuratedLabelsOnSubsequentProjection(): void
    {
        $projector = new SnapshotProjector(
            new ClustersRepository(),
            new IdentityMembersRepository(),
            new SyncStateRepository()
        );

        // First projection: cluster arrives as user_confirmed with curated label.
        $projector->project(
            'tenant-label-test',
            [
                'snapshot_version' => 10,
                'clusters' => [
                    [
                        'cluster_uuid' => 'cluster-curated',
                        'label' => 'Curated Name',
                        'curation_state' => 'confirmed',
                        'is_user_confirmed' => true,
                        'identity_count' => 1,
                        'representative_media_id' => 500,
                    ],
                ],
                'members' => [
                    [
                        'identity_uuid' => 'identity-curated-1',
                        'cluster_uuid' => 'cluster-curated',
                        'attachment_id' => 500,
                    ],
                ],
            ]
        );

        // Reset query log before second projection.
        global $wpdb;
        $wpdb->queries = [];

        // Second projection: same cluster_uuid arrives with a different label.
        $projector->project(
            'tenant-label-test',
            [
                'snapshot_version' => 11,
                'clusters' => [
                    [
                        'cluster_uuid' => 'cluster-curated',
                        'label' => 'Machine Label',
                        'curation_state' => 'auto',
                        'is_user_confirmed' => false,
                        'identity_count' => 1,
                        'representative_media_id' => 500,
                    ],
                ],
                'members' => [
                    [
                        'identity_uuid' => 'identity-curated-1',
                        'cluster_uuid' => 'cluster-curated',
                        'attachment_id' => 500,
                    ],
                ],
            ]
        );

        $queries = $wpdb->queries;
        $clusterInsert = $this->findQueryContaining($queries, 'INSERT INTO `wp_acx_clusters`');

        // The ON DUPLICATE KEY UPDATE guard must preserve the user-curated label.
        $this->assertStringContainsString(
            'IF(is_user_confirmed = 1, label, VALUES(label))',
            $clusterInsert,
            'Cluster upsert must guard user-curated labels with is_user_confirmed check'
        );

        // The incoming row carries the machine label, but the SQL guard keeps
        // the curated one (this is tested at the SQL level since our stub $wpdb
        // does not actually execute queries — the guard is structural).
        $this->assertStringContainsString("'Machine Label'", $clusterInsert);
        $this->assertStringContainsString("'cluster-curated'", $clusterInsert);

        // Curation state is also guarded.
        $this->assertStringContainsString(
            'IF(is_user_confirmed = 1, curation_state, VALUES(curation_state))',
            $clusterInsert,
            'Curation state must also be preserved for user-confirmed clusters'
        );

        // snapshot_version uses GREATEST to avoid rollback.
        $this->assertStringContainsString(
            'GREATEST(snapshot_version, VALUES(snapshot_version))',
            $clusterInsert,
            'Snapshot version must use GREATEST to prevent rollback'
        );
    }

    /**
     * @param array<int,string> $queries
     */
    private function findQueryContaining(array $queries, string $needle): string
    {
        foreach ($queries as $query) {
            if (str_contains($query, $needle)) {
                return $query;
            }
        }

        $this->fail(sprintf('Unable to find query containing "%s".', $needle));
        return '';
    }
}
