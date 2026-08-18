<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClusterSnapshotMerger;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Repositories\ClusterSnapshotMerger
 */
class ClusterSnapshotMergerTest extends TestCase
{
    use FindsSqlQueries;

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
        $query = $this->findQueryContaining($wpdb->queries, 'INSERT INTO `wp_acx_clusters`');
        $this->assertStringContainsString('INSERT INTO `wp_acx_clusters`', $query);
        $this->assertStringContainsString('label = IF(is_user_confirmed = 1, label, IF(label IS NULL AND person_id IS NULL, label, VALUES(label)))', $query);
        $this->assertStringContainsString('snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version))', $query);
    }

    public function testMergeSnapshotBatchGatesOverwrittenDataColumnsOnIncomingVersion(): void
    {
        // COR-1 (PA-2 mechanism assertion): an out-of-order snapshot with a
        // lower version must not clobber newer projection data. Each column the
        // upsert previously overwrote unconditionally is now gated on the
        // incoming snapshot_version.
        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-ver',
                    'label' => 'Versioned',
                    'identity_count' => 3,
                ],
            ],
            14
        );

        global $wpdb;
        $query = $wpdb->queries[0];
        $this->assertStringContainsString('identity_count = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(identity_count), identity_count)', $query);
        $this->assertStringContainsString('representative_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_id), representative_id)', $query);
        $this->assertStringContainsString('representative_thumb_path = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_thumb_path), representative_thumb_path)', $query);
        $this->assertStringContainsString('is_pinned = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(is_pinned), is_pinned)', $query);
        $this->assertStringContainsString('suggested_label = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_label), suggested_label)', $query);
        $this->assertStringContainsString('suggested_target_cluster_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_target_cluster_id), suggested_target_cluster_id)', $query);
        // The monotonic version column itself stays GREATEST and the curation
        // guard on label is preserved.
        $this->assertStringContainsString('snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version))', $query);
        $this->assertStringContainsString('label = IF(is_user_confirmed = 1, label, IF(label IS NULL AND person_id IS NULL, label, VALUES(label)))', $query);
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

    public function testLabelOnlyUpsertBindsPersonForHumanLabel(): void
    {
        global $wpdb;

        $wpdb->insert_id = 21;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-human',
                'tenant_id' => 'tenant-merge',
                'label' => 'Daniel',
                'person_id' => null,
            ],
        ];

        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-human',
                    'label' => 'Daniel',
                    'identity_count' => 4,
                ],
            ],
            14
        );

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertNotEmpty($personInserts, 'human label-only upsert must create a person');
        $this->assertStringContainsString("'Daniel'", $personInserts[0]);

        $bindUpdate = $this->findQueryContaining($wpdb->queries, 'person_id = 21');
        $this->assertStringContainsString('cluster-human', $bindUpdate);
    }

    public function testDeleteThenSnapshotMergeDoesNotRecreatePerson(): void
    {
        global $wpdb;

        $wpdb->insert_id = 99;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-tory',
                'tenant_id' => 'tenant-merge',
                'label' => null,
                'person_id' => null,
                'is_user_confirmed' => 0,
                'local_revision' => 5,
            ],
        ];

        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-tory',
                    'label' => 'Tory Guzman',
                    'identity_count' => 3,
                ],
            ],
            14
        );

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(0, $personInserts, 'locally cleared label must not be backfilled from a stale snapshot');
        $this->assertNull($wpdb->tableRows['wp_acx_clusters'][0]['person_id']);
    }

    public function testBackfillResolvesAgainstStoredLabelWhenIncomingDiffers(): void
    {
        global $wpdb;

        $wpdb->insert_id = 22;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-stored',
                'tenant_id' => 'tenant-merge',
                'label' => 'Stored Name',
                'person_id' => null,
                'is_user_confirmed' => 1,
            ],
        ];

        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-stored',
                    'label' => 'Incoming Name',
                    'identity_count' => 2,
                ],
            ],
            14
        );

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertNotEmpty($personInserts);
        $this->assertStringContainsString("'Stored Name'", $personInserts[0]);
        $this->assertStringNotContainsString("'Incoming Name'", $personInserts[0]);
    }

    public function testBackfillSkipsReservedStoredLabel(): void
    {
        global $wpdb;

        $wpdb->insert_id = 23;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-reserved',
                'tenant_id' => 'tenant-merge',
                'label' => 'cluster_abcdef01',
                'person_id' => null,
            ],
        ];

        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-reserved',
                    'label' => 'cluster_abcdef01',
                    'identity_count' => 2,
                ],
            ],
            14
        );

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(0, $personInserts);
    }

    public function testBackfillSkipsAlreadyBoundCluster(): void
    {
        global $wpdb;

        $wpdb->insert_id = 24;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-bound',
                'tenant_id' => 'tenant-merge',
                'label' => 'Already Bound',
                'person_id' => 7,
            ],
        ];

        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-bound',
                    'label' => 'Already Bound',
                    'identity_count' => 2,
                ],
            ],
            14
        );

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(0, $personInserts);
    }

    public function testSecondIdenticalSnapshotBatchIsNoOpForBind(): void
    {
        global $wpdb;

        $wpdb->insert_id = 25;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-once',
                'tenant_id' => 'tenant-merge',
                'label' => 'Once',
                'person_id' => null,
            ],
        ];

        $payload = [
            [
                'cluster_uuid' => 'cluster-once',
                'label' => 'Once',
                'identity_count' => 2,
            ],
        ];
        $this->merger->merge_snapshot_batch_for_tenant('tenant-merge', $payload, 14);

        $wpdb->tableRows['wp_acx_clusters'][0]['person_id'] = 25;
        $wpdb->queries = [];
        $this->merger->merge_snapshot_batch_for_tenant('tenant-merge', $payload, 14);

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $updates = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_starts_with($query, 'UPDATE wp_acx_clusters SET person_id')
            )
        );
        $this->assertCount(0, $personInserts);
        $this->assertCount(0, $updates);
        $this->assertSame(25, $wpdb->tableRows['wp_acx_clusters'][0]['person_id']);
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
