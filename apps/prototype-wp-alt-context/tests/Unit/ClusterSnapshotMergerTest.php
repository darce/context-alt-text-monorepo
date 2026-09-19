<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\ClusterSnapshotMerger;
use AltContext\Tests\Support\FindsSqlQueries;
use AltContext\Tests\TestCase;
use RuntimeException;

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
        $this->assertStringContainsString(
            '(cluster_uuid, tenant_id, label, label_cleared_label, label_cleared_revision, curation_state, representative_thumb_path, representative_id, is_pinned, identity_count, snapshot_version, is_user_confirmed, created_at, updated_at, last_synced_at, suggested_label, suggested_label_source, suggested_label_confidence, suggested_target_cluster_id, representative_quality, quality_components, representative_media_id, undoable_merge_receipt_id)',
            $query
        );
        $this->assertStringContainsString("NULLIF('', ''), NULLIF('', ''), NULLIF('', ''), NULLIF('', '')", $query);
        $this->assertStringContainsString('label = IF(is_user_confirmed = 1, label, VALUES(label))', $query);
        $this->assertStringContainsString('snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version))', $query);
    }

    public function testMergeSnapshotBatchPersistsSnapshotExportFields(): void
    {
        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-quality',
                    'label' => 'Quality',
                    'identity_count' => 4,
                    'representative_quality' => 0.82,
                    'quality_components' => [
                        'confidence' => 0.94,
                        'bbox_area' => 77.0,
                        'sharpness' => 42.5,
                        'occlusion_severity' => null,
                    ],
                    'representative_media_id' => 501,
                    'undoable_merge_receipt_id' => 'b9e2c4a1-7d6f-4a8b-9c31-2e5f0a7b8d44',
                ],
            ],
            14
        );

        global $wpdb;
        $query = $this->findQueryContaining($wpdb->queries, 'INSERT INTO `wp_acx_clusters`');
        $this->assertStringContainsString("'0.82'", $query);
        $this->assertStringContainsString('42.5', $query);
        $this->assertStringContainsString('77', $query);
        $this->assertStringContainsString("'501'", $query);
        $this->assertStringContainsString("'b9e2c4a1-7d6f-4a8b-9c31-2e5f0a7b8d44'", $query);
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
        $query = $this->findQueryContaining($wpdb->queries, 'INSERT INTO `wp_acx_clusters`');
        $this->assertStringContainsString('identity_count = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(identity_count), identity_count)', $query);
        $this->assertStringContainsString('representative_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_id), representative_id)', $query);
        $this->assertStringContainsString('representative_thumb_path = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_thumb_path), representative_thumb_path)', $query);
        $this->assertStringContainsString('is_pinned = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(is_pinned), is_pinned)', $query);
        $this->assertStringContainsString('suggested_label = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_label), suggested_label)', $query);
        $this->assertStringContainsString('suggested_target_cluster_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(suggested_target_cluster_id), suggested_target_cluster_id)', $query);
        $this->assertStringContainsString('representative_quality = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_quality), representative_quality)', $query);
        $this->assertStringContainsString('quality_components = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(quality_components), quality_components)', $query);
        $this->assertStringContainsString('representative_media_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(representative_media_id), representative_media_id)', $query);
        $this->assertStringContainsString('undoable_merge_receipt_id = IF(VALUES(snapshot_version) >= snapshot_version, VALUES(undoable_merge_receipt_id), undoable_merge_receipt_id)', $query);
        // The monotonic version column itself stays GREATEST and the curation
        // guard on label is preserved.
        $this->assertStringContainsString('snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version))', $query);
        $this->assertStringContainsString('label = IF(is_user_confirmed = 1, label, VALUES(label))', $query);
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
        $query = $this->findQueryContaining($wpdb->queries, 'INSERT INTO `wp_acx_clusters`');
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
        $query = $this->findQueryContaining($wpdb->queries, 'INSERT INTO `wp_acx_clusters`');
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
        $query = $this->findQueryContaining($wpdb->queries, 'INSERT INTO `wp_acx_clusters`');
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

        $tenant = self::currentTenantId();
        $clusterUuid = 'cluster-tory-delete';
        $wpdb->insert_id = 99;
        $wpdb->mockRow = [
            'id' => 4,
            'name' => 'Tory Guzman',
            'person_uuid' => '7fa30d6d-5d89-4d09-b4fb-b5fe11111111',
            'local_revision' => 2,
            'tenant_id' => $tenant,
        ];
        $wpdb->tableRows['wp_acx_persons'] = [
            [
                'id' => 4,
                'name' => 'Tory Guzman',
                'person_uuid' => '7fa30d6d-5d89-4d09-b4fb-b5fe11111111',
                'local_revision' => 2,
                'tenant_id' => $tenant,
            ],
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => $clusterUuid,
                'tenant_id' => $tenant,
                'label' => 'Tory Guzman',
                'person_id' => 4,
                'is_user_confirmed' => 1,
                'local_revision' => 5,
                'snapshot_version' => 14,
                'curation_state' => 'confirmed',
            ],
        ];

        $api = new \AltContext\Api\Api();
        $request = new \WP_REST_Request('DELETE', '/acx/v1/roster/persons/4');
        $request->set_param('id', 4);
        $response = $api->delete_person($request);
        $this->assertNotInstanceOf(\WP_Error::class, $response);

        $wpdb->mockRow = null;
        $wpdb->queries = [];
        $wpdb->insert_id = 100;

        $this->merger->merge_snapshot_batch_for_tenant(
            $tenant,
            [
                [
                    'cluster_uuid' => $clusterUuid,
                    'label' => 'Tory Guzman',
                    'identity_count' => 3,
                ],
            ],
            15
        );

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(0, $personInserts, 'delete must survive a stale-label snapshot; person must not be recreated');
        $this->assertNull(
            $wpdb->tableRows['wp_acx_clusters'][0]['label'],
            'cleared label must persist as NULL, not an empty string or the stale name'
        );
        $this->assertTrue(
            $wpdb->tableRows['wp_acx_clusters'][0]['person_id'] === null
            || (int) $wpdb->tableRows['wp_acx_clusters'][0]['person_id'] === 0
        );
    }

    /**
     * @dataProvider clearedLabelSnapshotVersions
     */
    public function testClearedLabelSurvivesSnapshotVersion(int $existingSnapshotVersion, int $mergeVersion): void
    {
        global $wpdb;

        $wpdb->insert_id = 99;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-tory',
                'tenant_id' => 'tenant-merge',
                'label' => 'Tory Guzman',
                'person_id' => 4,
                'is_user_confirmed' => 1,
                'local_revision' => 5,
                'snapshot_version' => $existingSnapshotVersion,
            ],
        ];

        $writer = new \AltContext\Sovereign\Repositories\ClusterCurationWriter('wp_acx_clusters');
        $writer->reset_curation('cluster-tory', 'tenant-merge');
        $wpdb->queries = [];

        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-tory',
                    'label' => 'Tory Guzman',
                    'identity_count' => 3,
                ],
            ],
            $mergeVersion
        );

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertCount(0, $personInserts, 'locally cleared label must not be backfilled from a stale snapshot');
        $this->assertTrue(
            $wpdb->tableRows['wp_acx_clusters'][0]['label'] === null
            || $wpdb->tableRows['wp_acx_clusters'][0]['label'] === '',
            'tombstone must keep the cleared label'
        );
        $this->assertTrue(
            $wpdb->tableRows['wp_acx_clusters'][0]['person_id'] === null
            || (int) $wpdb->tableRows['wp_acx_clusters'][0]['person_id'] === 0
        );
        $upsert = $this->findQueryContaining($wpdb->queries, 'INSERT INTO `wp_acx_clusters`');
        $this->assertStringContainsString("VALUES ('cluster-tory', 'tenant-merge', NULLIF('', ''), 'Tory Guzman'", $upsert);
    }

    /**
     * @return array<string,array{0:int,1:int}>
     */
    public static function clearedLabelSnapshotVersions(): array
    {
        return [
            'older than cleared_rev' => [14, 13],
            'equal to cleared_rev' => [14, 14],
            'newer than cleared_rev' => [14, 15],
            'locally created cluster' => [0, 1],
        ];
    }

    public function testNewerSnapshotAfterClearRelabelsCluster(): void
    {
        global $wpdb;

        $wpdb->insert_id = 100;
        $wpdb->tableRows['wp_acx_persons'] = [];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-tory',
                'tenant_id' => 'tenant-merge',
                'label' => 'Tory Guzman',
                'person_id' => 4,
                'is_user_confirmed' => 1,
                'local_revision' => 5,
                'snapshot_version' => 14,
            ],
        ];

        $writer = new \AltContext\Sovereign\Repositories\ClusterCurationWriter('wp_acx_clusters');
        $writer->reset_curation('cluster-tory', 'tenant-merge');
        $wpdb->queries = [];

        $this->merger->merge_snapshot_batch_for_tenant(
            'tenant-merge',
            [
                [
                    'cluster_uuid' => 'cluster-tory',
                    'label' => 'Ada Lovelace',
                    'identity_count' => 3,
                ],
            ],
            15
        );

        $personInserts = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'INSERT INTO wp_acx_persons')
            )
        );
        $this->assertNotEmpty($personInserts, 'a newer snapshot may re-label only when the incoming label differs');
        $this->assertStringContainsString("'Ada Lovelace'", $personInserts[0]);
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

    public function testPrepareSnapshotMergeDoesNotTombstoneWithoutCompleteness(): void
    {
        $this->seedTombstoneProjection('tenant-prune');

        $result = $this->merger->prepare_snapshot_merge_for_tenant('tenant-prune', ['cluster-keep']);

        global $wpdb;
        $this->assertSame(
            array(
                'tombstoned_clusters' => 0,
                'tombstoned_members' => 0,
                'preserved_curated' => 0,
            ),
            $result
        );
        $this->assertCount(3, $this->clusterIdsForTenant('tenant-prune'));
        $this->assertCount(3, $wpdb->tableRows['wp_acx_identity_members']);
        $this->assertSame(
            array(),
            array_values(
                array_filter(
                    $wpdb->queries,
                    static fn(string $query): bool => str_starts_with($query, 'DELETE FROM wp_acx_')
                )
            )
        );
    }

    public function testFullSnapshotTombsAbsentClustersAndMembersLeavingOne(): void
    {
        $this->seedTombstoneProjection('tenant-tombstone');

        $result = $this->merger->merge_snapshot_for_tenant(
            'tenant-tombstone',
            array(
                array(
                    'cluster_uuid' => 'cluster-keep',
                    'label' => 'Keep',
                    'identity_count' => 1,
                ),
            ),
            21,
            true
        );

        global $wpdb;
        $this->assertSame(
            array(
                'tombstoned_clusters' => 2,
                'tombstoned_members' => 2,
                'preserved_curated' => 0,
            ),
            $result
        );
        $this->assertSame(array('cluster-keep'), $this->clusterIdsForTenant('tenant-tombstone'));
        $this->assertSame(
            array('cluster-other-tenant'),
            $this->clusterIdsForTenant('other-tenant')
        );
        $this->assertSame(
            array('id-keep'),
            array_values(
                array_map(
                    static fn(array $row): string => (string) $row['identity_uuid'],
                    $wpdb->tableRows['wp_acx_identity_members']
                )
            )
        );
        $this->assertContains(9, $this->personIds());
        $this->assertSame('Operator Name', $this->personName(9));
        $this->assertSame(
            array(),
            $this->queriesStartingWith('DELETE FROM wp_acx_persons')
        );
        $this->assertSame(
            array('version_conflict:cluster-keep'),
            $this->conflictKeys()
        );
    }

    public function testPartialSnapshotDoesNotTombstone(): void
    {
        $this->seedTombstoneProjection('tenant-tombstone');

        $result = $this->merger->merge_snapshot_for_tenant(
            'tenant-tombstone',
            array(
                'clusters' => array(
                    array(
                        'cluster_uuid' => 'cluster-keep',
                        'label' => 'Keep',
                        'identity_count' => 1,
                    ),
                ),
                'has_more' => true,
            ),
            21
        );

        global $wpdb;
        $this->assertSame(
            array(
                'tombstoned_clusters' => 0,
                'tombstoned_members' => 0,
                'preserved_curated' => 0,
            ),
            $result
        );
        $this->assertSame(
            array('cluster-keep', 'cluster-stale-a', 'cluster-stale-b'),
            $this->clusterIdsForTenant('tenant-tombstone')
        );
        $this->assertCount(3, $wpdb->tableRows['wp_acx_identity_members']);
        $this->assertCount(3, $wpdb->tableRows['wp_acx_sync_conflicts']);
        $this->assertContains(9, $this->personIds());
        $this->assertSame(
            array(),
            $this->queriesStartingWith('DELETE FROM wp_acx_persons')
        );
    }

    public function testUndeclaredCompletenessDoesNotTombstone(): void
    {
        $this->seedTombstoneProjection('tenant-tombstone');

        $result = $this->merger->merge_snapshot_for_tenant(
            'tenant-tombstone',
            array(
                array(
                    'cluster_uuid' => 'cluster-keep',
                    'label' => 'Keep',
                    'identity_count' => 1,
                ),
            ),
            21
        );

        $this->assertSame(
            array(
                'tombstoned_clusters' => 0,
                'tombstoned_members' => 0,
                'preserved_curated' => 0,
            ),
            $result
        );
        $this->assertSame(
            array('cluster-keep', 'cluster-stale-a', 'cluster-stale-b'),
            $this->clusterIdsForTenant('tenant-tombstone')
        );
    }

    public function testCompleteEnvelopeTombsAndDropsClusterNotFoundConflicts(): void
    {
        $this->seedTombstoneProjection('tenant-tombstone');

        $result = $this->merger->merge_snapshot_for_tenant(
            'tenant-tombstone',
            array(
                'clusters' => array(
                    array(
                        'cluster_uuid' => 'cluster-keep',
                        'label' => 'Keep',
                        'identity_count' => 1,
                    ),
                ),
                'is_complete' => true,
            ),
            21
        );

        $this->assertSame(2, $result['tombstoned_clusters']);
        $this->assertSame(2, $result['tombstoned_members']);
        $this->assertSame(0, $result['preserved_curated']);
        $this->assertSame(array('cluster-keep'), $this->clusterIdsForTenant('tenant-tombstone'));
        $this->assertSame(array('version_conflict:cluster-keep'), $this->conflictKeys());
    }

    public function testUpsertQueryFailureThrowsAndDoesNotTombstone(): void
    {
        $this->seedTombstoneProjection('tenant-upsert-fail');

        global $wpdb;
        $wpdb->queries = [];
        $wpdb->defaultQueryResult = false;
        $wpdb->last_error = 'simulated upsert failure';

        try {
            $this->merger->merge_snapshot_for_tenant(
                'tenant-upsert-fail',
                array(
                    array(
                        'cluster_uuid' => 'cluster-keep',
                        'label' => 'Keep',
                        'identity_count' => 1,
                    ),
                ),
                21,
                false
            );
            $this->fail('Expected RuntimeException when upsert query returns false');
        } catch (RuntimeException $exception) {
            $this->assertStringContainsString('simulated upsert failure', $exception->getMessage());
            $this->assertSame(array(), $this->queriesStartingWith('DELETE FROM wp_acx_'));
            $this->assertCount(3, $this->clusterIdsForTenant('tenant-upsert-fail'));
        }
    }

    public function testMemberDeleteFailureThrowsBeforeClusterDelete(): void
    {
        $this->seedTombstoneProjection('tenant-delete-fail');

        global $wpdb;
        $wpdb->queries = [];
        $wpdb->last_error = 'simulated member delete failure';
        $wpdb->deleteResultsByTable['wp_acx_identity_members'] = false;

        try {
            $this->merger->prepare_snapshot_merge_for_tenant(
                'tenant-delete-fail',
                array('cluster-keep'),
                true
            );
            $this->fail('Expected RuntimeException when member delete returns false');
        } catch (RuntimeException $exception) {
            $this->assertStringContainsString('simulated member delete failure', $exception->getMessage());
            $this->assertSame(array(), $this->queriesStartingWith('DELETE FROM wp_acx_clusters'));
            $this->assertSame(
                array('cluster-keep', 'cluster-stale-a', 'cluster-stale-b'),
                $this->clusterIdsForTenant('tenant-delete-fail')
            );
        }
    }

    public function testCompleteSnapshotPreservesConfirmedAndPersonBoundClusters(): void
    {
        global $wpdb;

        $tenant = 'tenant-preserve';
        $wpdb->tableRows['wp_acx_clusters'] = array(
            array(
                'cluster_uuid' => 'cluster-keep',
                'tenant_id' => $tenant,
                'label' => 'Keep',
                'is_user_confirmed' => 0,
                'person_id' => null,
                'curation_state' => 'uncurated',
            ),
            array(
                'cluster_uuid' => 'cluster-uncurated',
                'tenant_id' => $tenant,
                'label' => 'Stale Uncurated',
                'is_user_confirmed' => 0,
                'person_id' => null,
                'curation_state' => 'uncurated',
            ),
            array(
                'cluster_uuid' => 'cluster-confirmed',
                'tenant_id' => $tenant,
                'label' => 'Human Confirmed',
                'is_user_confirmed' => 1,
                'person_id' => null,
                'curation_state' => 'uncurated',
            ),
            array(
                'cluster_uuid' => 'cluster-person-bound',
                'tenant_id' => $tenant,
                'label' => 'Bound Person',
                'is_user_confirmed' => 0,
                'person_id' => 11,
                'curation_state' => 'uncurated',
            ),
        );
        $wpdb->tableRows['wp_acx_identity_members'] = array(
            array(
                'identity_uuid' => 'id-keep',
                'cluster_uuid' => 'cluster-keep',
            ),
            array(
                'identity_uuid' => 'id-uncurated',
                'cluster_uuid' => 'cluster-uncurated',
            ),
            array(
                'identity_uuid' => 'id-confirmed',
                'cluster_uuid' => 'cluster-confirmed',
            ),
            array(
                'identity_uuid' => 'id-person-bound',
                'cluster_uuid' => 'cluster-person-bound',
            ),
        );
        $wpdb->tableRows['wp_acx_sync_conflicts'] = array(
            array(
                'tenant_id' => $tenant,
                'conflict_code' => 'cluster_not_found',
                'entity_key' => 'cluster-uncurated',
            ),
            array(
                'tenant_id' => $tenant,
                'conflict_code' => 'cluster_not_found',
                'entity_key' => 'cluster-confirmed',
            ),
            array(
                'tenant_id' => $tenant,
                'conflict_code' => 'cluster_not_found',
                'entity_key' => 'cluster-person-bound',
            ),
        );

        $result = $this->merger->merge_snapshot_for_tenant(
            $tenant,
            array(
                array(
                    'cluster_uuid' => 'cluster-keep',
                    'label' => 'Keep',
                    'identity_count' => 1,
                ),
            ),
            21,
            true
        );

        $this->assertSame(
            array(
                'tombstoned_clusters' => 1,
                'tombstoned_members' => 1,
                'preserved_curated' => 2,
            ),
            $result
        );
        $this->assertSame(
            array('cluster-confirmed', 'cluster-keep', 'cluster-person-bound'),
            $this->clusterIdsForTenant($tenant)
        );
        $memberIds = array_values(
            array_map(
                static fn(array $row): string => (string) $row['identity_uuid'],
                $wpdb->tableRows['wp_acx_identity_members']
            )
        );
        sort($memberIds);
        $this->assertSame(array('id-confirmed', 'id-keep', 'id-person-bound'), $memberIds);
        $this->assertSame(
            array('cluster_not_found:cluster-confirmed', 'cluster_not_found:cluster-person-bound'),
            $this->conflictKeys()
        );
    }

    public function testTombstoneLocksClassifiedAbsentClustersForUpdate(): void
    {
        $this->seedTombstoneProjection('tenant-tombstone-lock');

        global $wpdb;
        $wpdb->queries = [];

        $this->merger->prepare_snapshot_merge_for_tenant(
            'tenant-tombstone-lock',
            array('cluster-keep'),
            true
        );

        $lockQueries = array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_contains($query, 'FOR UPDATE')
            )
        );
        $this->assertNotSame(array(), $lockQueries);
        $lockSql = implode("\n", $lockQueries);
        $this->assertStringContainsString(
            'SELECT cluster_uuid, is_user_confirmed, person_id, curation_state FROM `wp_acx_clusters`',
            $lockSql
        );
        $this->assertStringContainsString("tenant_id = 'tenant-tombstone-lock'", $lockSql);
        $this->assertStringContainsString('cluster-stale-a', $lockSql);
        $this->assertStringContainsString('cluster-stale-b', $lockSql);
        $this->assertStringNotContainsString('cluster-keep', $lockSql);
        $this->assertStringNotContainsString('cluster-other-tenant', $lockSql);

        $lockIndex = array_search($lockQueries[0], $wpdb->queries, true);
        $deleteQueries = $this->queriesStartingWith('DELETE FROM wp_acx_');
        $this->assertNotSame(array(), $deleteQueries);
        $firstDeleteIndex = array_search($deleteQueries[0], $wpdb->queries, true);
        $this->assertIsInt($lockIndex);
        $this->assertIsInt($firstDeleteIndex);
        $this->assertLessThan($firstDeleteIndex, $lockIndex);
    }

    public function testTombstoneRechecksCurationConfirmationAndPersonBindingBeforeDelete(): void
    {
        global $wpdb;

        $tenant = 'tenant-tombstone-recheck';
        $wpdb->tableRows['wp_acx_clusters'] = array(
            array(
                'cluster_uuid' => 'cluster-keep',
                'tenant_id' => $tenant,
                'label' => 'Keep',
                'is_user_confirmed' => 0,
                'person_id' => null,
                'curation_state' => 'uncurated',
            ),
            array(
                'cluster_uuid' => 'cluster-flip-confirmed',
                'tenant_id' => $tenant,
                'label' => 'Flip Confirmed',
                'is_user_confirmed' => 0,
                'person_id' => null,
                'curation_state' => 'uncurated',
            ),
            array(
                'cluster_uuid' => 'cluster-flip-bound',
                'tenant_id' => $tenant,
                'label' => 'Flip Bound',
                'is_user_confirmed' => 0,
                'person_id' => null,
                'curation_state' => 'uncurated',
            ),
            array(
                'cluster_uuid' => 'cluster-flip-curated',
                'tenant_id' => $tenant,
                'label' => 'Flip Curated',
                'is_user_confirmed' => 0,
                'person_id' => null,
                'curation_state' => 'uncurated',
            ),
            array(
                'cluster_uuid' => 'cluster-still-stale',
                'tenant_id' => $tenant,
                'label' => 'Still Stale',
                'is_user_confirmed' => 0,
                'person_id' => null,
                'curation_state' => 'uncurated',
            ),
        );
        $wpdb->tableRows['wp_acx_identity_members'] = array(
            array(
                'identity_uuid' => 'id-keep',
                'cluster_uuid' => 'cluster-keep',
            ),
            array(
                'identity_uuid' => 'id-flip-confirmed',
                'cluster_uuid' => 'cluster-flip-confirmed',
            ),
            array(
                'identity_uuid' => 'id-flip-bound',
                'cluster_uuid' => 'cluster-flip-bound',
            ),
            array(
                'identity_uuid' => 'id-flip-curated',
                'cluster_uuid' => 'cluster-flip-curated',
            ),
            array(
                'identity_uuid' => 'id-still-stale',
                'cluster_uuid' => 'cluster-still-stale',
            ),
        );
        $wpdb->tableRows['wp_acx_sync_conflicts'] = array();
        $wpdb->queries = [];
        $wpdb->onGetResults = static function (string $sql): ?array {
            if (!str_contains($sql, 'FOR UPDATE')) {
                return null;
            }

            global $wpdb;
            foreach ($wpdb->tableRows['wp_acx_clusters'] as $index => $row) {
                $clusterUuid = (string) ($row['cluster_uuid'] ?? '');
                if ('cluster-flip-confirmed' === $clusterUuid) {
                    $wpdb->tableRows['wp_acx_clusters'][$index]['is_user_confirmed'] = 1;
                    continue;
                }
                if ('cluster-flip-bound' === $clusterUuid) {
                    $wpdb->tableRows['wp_acx_clusters'][$index]['person_id'] = 11;
                    continue;
                }
                if ('cluster-flip-curated' === $clusterUuid) {
                    $wpdb->tableRows['wp_acx_clusters'][$index]['curation_state'] = 'confirmed';
                }
            }

            return null;
        };

        $result = $this->merger->prepare_snapshot_merge_for_tenant(
            $tenant,
            array('cluster-keep'),
            true
        );

        $this->assertSame(
            array(
                'tombstoned_clusters' => 1,
                'tombstoned_members' => 1,
                'preserved_curated' => 3,
            ),
            $result
        );
        $this->assertSame(
            array(
                'cluster-flip-bound',
                'cluster-flip-confirmed',
                'cluster-flip-curated',
                'cluster-keep',
            ),
            $this->clusterIdsForTenant($tenant)
        );
        $memberIds = array_values(
            array_map(
                static fn(array $row): string => (string) $row['identity_uuid'],
                $wpdb->tableRows['wp_acx_identity_members']
            )
        );
        sort($memberIds);
        $this->assertSame(
            array('id-flip-bound', 'id-flip-confirmed', 'id-flip-curated', 'id-keep'),
            $memberIds
        );
    }

    /**
     * @return int[]
     */
    private function personIds(): array
    {
        global $wpdb;

        $ids = array();
        foreach ($wpdb->tableRows['wp_acx_persons'] ?? array() as $row) {
            $ids[] = (int) $row['id'];
        }

        return $ids;
    }

    private function personName(int $personId): ?string
    {
        global $wpdb;

        foreach ($wpdb->tableRows['wp_acx_persons'] ?? array() as $row) {
            if ((int) $row['id'] === $personId) {
                return (string) $row['name'];
            }
        }

        return null;
    }

    /**
     * @return string[]
     */
    private function queriesStartingWith(string $prefix): array
    {
        global $wpdb;

        return array_values(
            array_filter(
                $wpdb->queries,
                static fn(string $query): bool => str_starts_with($query, $prefix)
            )
        );
    }

    /**
     * @return string[]
     */
    private function clusterIdsForTenant(string $tenantId): array
    {
        global $wpdb;

        $ids = array();
        foreach ($wpdb->tableRows['wp_acx_clusters'] ?? array() as $row) {
            if ((string) ($row['tenant_id'] ?? '') !== $tenantId) {
                continue;
            }
            $ids[] = (string) $row['cluster_uuid'];
        }
        sort($ids);

        return $ids;
    }

    /**
     * @return string[]
     */
    private function conflictKeys(): array
    {
        global $wpdb;

        $keys = array_map(
            static fn(array $row): string => (string) $row['conflict_code'] . ':' . (string) $row['entity_key'],
            $wpdb->tableRows['wp_acx_sync_conflicts'] ?? array()
        );
        sort($keys);

        return $keys;
    }

    private function seedTombstoneProjection(string $tenant): void
    {
        global $wpdb;

        $wpdb->tableRows['wp_acx_clusters'] = array(
            array(
                'cluster_uuid' => 'cluster-keep',
                'tenant_id' => $tenant,
                'label' => 'Keep',
                'is_user_confirmed' => 0,
            ),
            array(
                'cluster_uuid' => 'cluster-stale-a',
                'tenant_id' => $tenant,
                'label' => 'Stale A',
                'is_user_confirmed' => 0,
                'person_id' => null,
                'curation_state' => 'uncurated',
            ),
            array(
                'cluster_uuid' => 'cluster-stale-b',
                'tenant_id' => $tenant,
                'label' => 'Operator Name',
                'is_user_confirmed' => 0,
                'person_id' => null,
                'curation_state' => '',
            ),
            array(
                'cluster_uuid' => 'cluster-other-tenant',
                'tenant_id' => 'other-tenant',
                'label' => 'Other',
                'is_user_confirmed' => 0,
            ),
        );
        $wpdb->tableRows['wp_acx_identity_members'] = array(
            array(
                'identity_uuid' => 'id-keep',
                'cluster_uuid' => 'cluster-keep',
            ),
            array(
                'identity_uuid' => 'id-stale-a',
                'cluster_uuid' => 'cluster-stale-a',
            ),
            array(
                'identity_uuid' => 'id-stale-b',
                'cluster_uuid' => 'cluster-stale-b',
            ),
        );
        $wpdb->tableRows['wp_acx_persons'] = array(
            array(
                'id' => 9,
                'name' => 'Operator Name',
                'tenant_id' => $tenant,
            ),
        );
        $wpdb->tableRows['wp_acx_sync_conflicts'] = array(
            array(
                'id' => 1,
                'tenant_id' => $tenant,
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-stale-a',
                'conflict_code' => 'cluster_not_found',
                'resolution_status' => 'open',
            ),
            array(
                'id' => 2,
                'tenant_id' => $tenant,
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-keep',
                'conflict_code' => 'version_conflict',
                'resolution_status' => 'open',
            ),
            array(
                'id' => 3,
                'tenant_id' => $tenant,
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-stale-b',
                'conflict_code' => 'cluster_not_found',
                'resolution_status' => 'open',
            ),
        );
    }
}
