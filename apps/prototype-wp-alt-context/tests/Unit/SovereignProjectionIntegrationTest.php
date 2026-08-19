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
            'label = IF(is_user_confirmed = 1, label, VALUES(label))',
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

        // Deliberate curated dissociation (person_id = NULL + user_confirmed) must survive replay.
        $this->assertStringContainsString(
            'person_id = IF(is_user_confirmed = 1, person_id, person_id)',
            $clusterInsert,
            'Curated dissociation must not be overwritten by replay rows'
        );

        $this->assertStringContainsString(
            'local_revision = IF(is_user_confirmed = 1, local_revision, local_revision)',
            $clusterInsert,
            'Local revision lineage must be preserved for user-confirmed rows'
        );

        // snapshot_version uses GREATEST to avoid rollback.
        $this->assertStringContainsString(
            'GREATEST(snapshot_version, VALUES(snapshot_version))',
            $clusterInsert,
            'Snapshot version must use GREATEST to prevent rollback'
        );
    }

    public function testProjectMixedCuratedAndUncuratedDataRefreshesConflictMetrics(): void
    {
        $projector = new SnapshotProjector(
            new ClustersRepository(),
            new IdentityMembersRepository(),
            new SyncStateRepository()
        );

        global $wpdb;
        // Three curated rows (two undisturbed) keep the single reassignment below
        // the E15-35 storm threshold so the per-entity conflict path is exercised.
        $wpdb->mockResults = [
            [
                'cluster_uuid' => 'cluster-curated-local',
                'label' => 'Curated Local',
                'identity_uuid' => 'identity-curated-local',
                'is_curated' => 1,
                'projection_version' => 40,
            ],
            [
                'cluster_uuid' => 'cluster-curated-2',
                'label' => 'Curated Two',
                'identity_uuid' => 'identity-curated-2',
                'is_curated' => 1,
                'projection_version' => 40,
            ],
            [
                'cluster_uuid' => 'cluster-curated-3',
                'label' => 'Curated Three',
                'identity_uuid' => 'identity-curated-3',
                'is_curated' => 1,
                'projection_version' => 40,
            ],
        ];
        $wpdb->queries = [];

        $projector->project(
            'tenant-mixed-conflicts',
            [
                'snapshot_version' => 41,
                'clusters' => [
                    [
                        'cluster_uuid' => 'cluster-curated-local',
                        'label' => 'Curated Local',
                        'curation_state' => 'confirmed',
                        'is_user_confirmed' => true,
                        'identity_count' => 1,
                        'representative_media_id' => 701,
                    ],
                    [
                        'cluster_uuid' => 'cluster-curated-2',
                        'label' => 'Curated Two',
                        'curation_state' => 'confirmed',
                        'is_user_confirmed' => true,
                        'identity_count' => 1,
                        'representative_media_id' => 704,
                    ],
                    [
                        'cluster_uuid' => 'cluster-curated-3',
                        'label' => 'Curated Three',
                        'curation_state' => 'confirmed',
                        'is_user_confirmed' => true,
                        'identity_count' => 1,
                        'representative_media_id' => 705,
                    ],
                    [
                        'cluster_uuid' => 'cluster-uncurated',
                        'label' => 'Machine Updated',
                        'curation_state' => 'auto',
                        'is_user_confirmed' => false,
                        'identity_count' => 2,
                        'representative_media_id' => 702,
                    ],
                    [
                        'cluster_uuid' => 'cluster-machine-target',
                        'label' => 'Machine Target',
                        'curation_state' => 'auto',
                        'is_user_confirmed' => false,
                        'identity_count' => 2,
                        'representative_media_id' => 703,
                    ],
                ],
                'members' => [
                    [
                        'identity_uuid' => 'identity-curated-local',
                        'cluster_uuid' => 'cluster-machine-target',
                        'attachment_id' => 701,
                    ],
                    [
                        'identity_uuid' => 'identity-uncurated',
                        'cluster_uuid' => 'cluster-machine-target',
                        'attachment_id' => 702,
                    ],
                    [
                        'identity_uuid' => 'identity-curated-2',
                        'cluster_uuid' => 'cluster-curated-2',
                        'attachment_id' => 704,
                    ],
                    [
                        'identity_uuid' => 'identity-curated-3',
                        'cluster_uuid' => 'cluster-curated-3',
                        'attachment_id' => 705,
                    ],
                    [
                        'identity_uuid' => 'identity-new',
                        'cluster_uuid' => 'cluster-machine-target',
                        'attachment_id' => 703,
                    ],
                ],
            ]
        );

        $queries = $wpdb->queries;
        $sql = implode("\n", $queries);

        $this->assertStringContainsString("'member_cluster_reassignment'", $sql);
        $this->assertStringContainsString('wp_acx_sync_state', $sql);
        $this->assertStringContainsString('conflict_count', $sql);

        $memberInsert = $this->findQueryContaining($queries, 'INSERT INTO `wp_acx_identity_members`');
        $this->assertStringContainsString("SELECT 'identity-uncurated', 'cluster-machine-target', 702", $memberInsert);
        $this->assertStringNotContainsString("SELECT 'identity-curated-local', 'cluster-machine-target', 701", $sql);
    }

    public function testProjectionReplayDeletesStaleNonCuratedMembersAndPreservesCuratedOnes(): void
    {
        $projector = new SnapshotProjector(
            new ClustersRepository(),
            new IdentityMembersRepository(),
            new SyncStateRepository()
        );

        // First projection seeds M1 and M2 under cluster C1.
        $projector->project(
            'tenant-rebuild',
            [
                'snapshot_version' => 50,
                'clusters' => [
                    [
                        'cluster_uuid' => 'cluster-rebuild-1',
                        'label' => 'Rebuild Cluster',
                        'curation_state' => 'auto',
                        'is_user_confirmed' => false,
                        'identity_count' => 2,
                        'representative_media_id' => 600,
                    ],
                ],
                'members' => [
                    [
                        'identity_uuid' => 'identity-stale-1',
                        'cluster_uuid' => 'cluster-rebuild-1',
                        'attachment_id' => 601,
                    ],
                    [
                        'identity_uuid' => 'identity-stale-2',
                        'cluster_uuid' => 'cluster-rebuild-1',
                        'attachment_id' => 602,
                    ],
                ],
            ]
        );

        // Reset query log between projections so we only inspect the replay scope.
        global $wpdb;
        $wpdb->queries = [];

        // Replay snapshot keeps cluster C1 but only retains M3 (drops M1 and M2).
        $projector->project(
            'tenant-rebuild',
            [
                'snapshot_version' => 51,
                'clusters' => [
                    [
                        'cluster_uuid' => 'cluster-rebuild-1',
                        'label' => 'Rebuild Cluster',
                        'curation_state' => 'auto',
                        'is_user_confirmed' => false,
                        'identity_count' => 1,
                        'representative_media_id' => 603,
                    ],
                ],
                'members' => [
                    [
                        'identity_uuid' => 'identity-fresh-3',
                        'cluster_uuid' => 'cluster-rebuild-1',
                        'attachment_id' => 603,
                    ],
                ],
            ]
        );

        $deleteQuery = $this->findQueryContaining(
            $wpdb->queries,
            'DELETE m FROM `wp_acx_identity_members` m'
        );

        // Stale-member DELETE must exclude only the surviving identity uuid.
        $this->assertStringContainsString("'identity-fresh-3'", $deleteQuery);
        $this->assertStringNotContainsString("'identity-stale-1'", $deleteQuery);
        $this->assertStringNotContainsString("'identity-stale-2'", $deleteQuery);
        $this->assertStringContainsString('NOT IN', $deleteQuery);

        // Curation guards must remain in place so curated rows survive replay.
        $this->assertStringContainsString('c.is_user_confirmed = 0', $deleteQuery);
        $this->assertStringContainsString('m.is_curated = 0', $deleteQuery);

        // Tenant scope must be enforced on the rebuild DELETE.
        $this->assertStringContainsString("c.tenant_id = 'tenant-rebuild'", $deleteQuery);
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
    }
}
