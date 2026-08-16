<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Mappers\ClusterResponseMapper
 */
class ClusterResponseMapperTest extends TestCase
{
    private ClusterResponseMapper $mapper;

    protected function setUp(): void
    {
        parent::setUp();
        $this->mapper = new ClusterResponseMapper();
    }

    public function testMapTopUnlabeledClustersPreservesPinnedRepresentatives(): void
    {
        $GLOBALS['__ac_attachment_urls'][99] = 'http://example.test/media/99.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-top',
                'label' => '',
                'identity_count' => 1,
                'is_user_confirmed' => 0,
            ],
        ];

        $members = [
            'cluster-top' => [
                [
                    'identity_uuid' => 'identity-99',
                    'attachment_id' => 99,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                    'is_pinned' => 1,
                ],
            ],
        ];

        $payload = $this->mapper->map_top_unlabeled_clusters($clusters, $members, 'tenant-1');

        $this->assertTrue($payload[0]['representatives'][0]['is_pinned']);
    }

    public function testMapClusterListUsesMemberRowsForSamples(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 1,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-1',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertSame('cluster-1', $payload[0]['id']);
        $this->assertSame('Alice', $payload[0]['label']);
        $this->assertSame('identity-1', $payload[0]['sample_identities'][0]['identity_id']);
        $this->assertSame('http://example.test/media/12.jpg', $payload[0]['sample_identities'][0]['thumb_url']);
    }

    public function testMapClusterListUsesObservedEmptyMemberCountOnCounterMismatch(): void
    {
        $GLOBALS['__ac_error_log'] = [];
        $payload = $this->mapper->map_cluster_list(
            [
                [
                    'cluster_uuid' => 'cluster-stale-count',
                    'identity_count' => 1,
                ],
            ],
            ['cluster-stale-count' => []],
            4
        );

        $this->assertSame(0, $payload[0]['identity_count']);
        $this->assertStringContainsString('cluster-stale-count', \implode("\n", $GLOBALS['__ac_error_log']));
        $this->assertStringContainsString('projected=1 observed=0', \implode("\n", $GLOBALS['__ac_error_log']));
    }

    /**
     * Production repository shape: clusters with zero members have no key in the
     * members map (sparse). With members fetched (preview limit provided), that
     * absence must mean observed 0 — not "not loaded".
     */
    public function testMapClusterListTreatsSparseMissingKeyAsEmptyWhenMembersFetched(): void
    {
        $GLOBALS['__ac_error_log'] = [];

        // Real list_for_cluster_uuids output: only clusters with rows appear.
        $sparse_members = [
            'cluster-with-members' => [
                [
                    'identity_uuid' => 'identity-1',
                    'attachment_id' => 12,
                ],
            ],
            // 'cluster-stale-empty' intentionally absent — zero member rows.
        ];

        $payload = $this->mapper->map_cluster_list(
            [
                [
                    'cluster_uuid' => 'cluster-with-members',
                    'identity_count' => 1,
                ],
                [
                    'cluster_uuid' => 'cluster-stale-empty',
                    'identity_count' => 1,
                ],
            ],
            $sparse_members,
            4
        );

        $this->assertSame(1, $payload[0]['identity_count']);
        $this->assertSame(0, $payload[1]['identity_count']);
        $log = \implode("\n", $GLOBALS['__ac_error_log']);
        $this->assertStringContainsString('cluster-stale-empty', $log);
        $this->assertStringContainsString('projected=1 observed=0', $log);
    }

    /**
     * Mapper-level densify for top-unlabeled: a sparse members map (cluster UUID
     * with no key) plus a non-null preview_limit must treat observed zero as
     * authoritative over a stale projected identity_count. Does not go through
     * ClusterFacade so facade densify cannot mask a missing preview_limit.
     */
    public function testMapTopUnlabeledClustersTreatsSparseMissingKeyAsEmptyWhenPreviewLimitSet(): void
    {
        $GLOBALS['__ac_error_log'] = [];

        // Sparse map: cluster-stale-empty has no key at all (not even []).
        $sparse_members = [];

        $payload = $this->mapper->map_top_unlabeled_clusters(
            [
                [
                    'cluster_uuid' => 'cluster-stale-empty',
                    'label' => '',
                    'identity_count' => 7,
                    'is_user_confirmed' => 0,
                ],
            ],
            $sparse_members,
            'tenant-1',
            4
        );

        $this->assertCount(1, $payload);
        $this->assertSame(0, $payload[0]['identity_count'], 'observed empty after densify must win over projected count');
        $this->assertSame([], $payload[0]['representatives']);
        $log = \implode("\n", $GLOBALS['__ac_error_log']);
        $this->assertStringContainsString('cluster-stale-empty', $log);
        $this->assertStringContainsString('projected=7 observed=0', $log);
    }

    public function testMapClusterListKeepsProjectedCountWhenMembersNotFetched(): void
    {
        $GLOBALS['__ac_error_log'] = [];

        $payload = $this->mapper->map_cluster_list(
            [
                [
                    'cluster_uuid' => 'cluster-projected-only',
                    'identity_count' => 7,
                ],
            ],
            []
        );

        $this->assertSame(7, $payload[0]['identity_count']);
        $this->assertSame([], $GLOBALS['__ac_error_log']);
    }

    public function testMapClusterListDoesNotLogExpectedPreviewTruncation(): void
    {
        $GLOBALS['__ac_error_log'] = [];

        $members = [
            'cluster-truncated' => [
                ['identity_uuid' => 'id-1', 'attachment_id' => 1],
                ['identity_uuid' => 'id-2', 'attachment_id' => 2],
                ['identity_uuid' => 'id-3', 'attachment_id' => 3],
                ['identity_uuid' => 'id-4', 'attachment_id' => 4],
            ],
        ];

        $payload = $this->mapper->map_cluster_list(
            [
                [
                    'cluster_uuid' => 'cluster-truncated',
                    'identity_count' => 9,
                ],
            ],
            $members,
            4
        );

        $this->assertSame(9, $payload[0]['identity_count']);
        $this->assertSame([], $GLOBALS['__ac_error_log']);
    }

    public function testMapClusterListLogsWhenObservedBelowPreviewLimit(): void
    {
        $GLOBALS['__ac_error_log'] = [];

        $members = [
            'cluster-shortfall' => [
                ['identity_uuid' => 'id-1', 'attachment_id' => 1],
                ['identity_uuid' => 'id-2', 'attachment_id' => 2],
            ],
        ];

        $payload = $this->mapper->map_cluster_list(
            [
                [
                    'cluster_uuid' => 'cluster-shortfall',
                    'identity_count' => 9,
                ],
            ],
            $members,
            4
        );

        $this->assertSame(9, $payload[0]['identity_count']);
        $log = \implode("\n", $GLOBALS['__ac_error_log']);
        $this->assertStringContainsString('cluster-shortfall', $log);
        $this->assertStringContainsString('projected=9 observed=2', $log);
    }

    public function testMapClusterListIncludesPinnedRepresentativeState(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 1,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-1',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                    'is_pinned' => 1,
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertTrue($payload[0]['representative_identity']['is_pinned']);
    }

    public function testMapClusterListFallsBackToClusterPinnedRepresentativeState(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 1,
                'representative_id' => 'identity-1',
                'is_pinned' => 1,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-1',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertTrue($payload[0]['representative_identity']['is_pinned']);
    }

    public function testMapTopUnlabeledClustersIncludesRepresentatives(): void
    {
        $GLOBALS['__ac_attachment_urls'][99] = 'http://example.test/media/99.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-top',
                'label' => '',
                'identity_count' => 2,
                'is_user_confirmed' => 0,
            ],
        ];

        $members = [
            'cluster-top' => [
                [
                    'identity_uuid' => 'identity-99',
                    'attachment_id' => 99,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_top_unlabeled_clusters($clusters, $members, 'tenant-1');

        $this->assertSame('cluster-top', $payload[0]['id']);
        $this->assertFalse($payload[0]['is_labeled']);
        $this->assertSame('http://example.test/media/99.jpg', $payload[0]['representatives'][0]['thumb_url']);
        $this->assertFalse($payload[0]['representatives'][0]['is_pinned']);
    }

    public function testMapTopUnlabeledClustersRewritesBlobThumbPathWhenAttachmentUrlMissing(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-top',
                'label' => '',
                'identity_count' => 2,
                'is_user_confirmed' => 0,
            ],
        ];

        $members = [
            'cluster-top' => [
                [
                    'identity_uuid' => 'identity-99',
                    'attachment_id' => 6731,
                    'thumb_path' => 'file:///private/tmp/acx-recognition-blobs/tenant-x/job-y/6731.bin',
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_top_unlabeled_clusters($clusters, $members, 'tenant-1');

        $parts = \parse_url($payload[0]['representatives'][0]['thumb_url']);
        $this->assertSame('/wp-json/acx/v1/recognition/blobs/job-y/6731', $parts['path']);
    }

    public function testMapTopUnlabeledClustersPrefersFaceThumbPathOverAttachmentUrl(): void
    {
        $GLOBALS['__ac_attachment_urls'][6731] = 'http://example.test/uploads/6731.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-top',
                'label' => '',
                'identity_count' => 2,
                'is_user_confirmed' => 0,
            ],
        ];

        $members = [
            'cluster-top' => [
                [
                    'identity_uuid' => 'identity-99',
                    'attachment_id' => 6731,
                    'thumb_path' => '/recognition/face-thumbs/job-y/6731?x=1&y=2&width=30&height=40',
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":30,"height":40}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_top_unlabeled_clusters($clusters, $members, 'tenant-1');

        $parts = \parse_url($payload[0]['representatives'][0]['thumb_url']);
        $this->assertSame('/wp-json/acx/v1/recognition/face-thumbs/job-y/6731', $parts['path']);
        $this->assertStringNotContainsString('/uploads/6731.jpg', $payload[0]['representatives'][0]['thumb_url']);
        $this->assertSame('http://example.test/uploads/6731.jpg', $payload[0]['representatives'][0]['attachment_url']);
        $this->assertSame(
            array(
                'x' => 1,
                'y' => 2,
                'width' => 30,
                'height' => 40,
            ),
            $payload[0]['representatives'][0]['bbox']
        );
    }

    public function testMapClusterListEmitsAttachmentUrlAndBboxBesideFaceThumb(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 1,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-1',
                    'attachment_id' => 12,
                    'thumb_path' => '/recognition/face-thumbs/job-1/12?x=1&y=2&width=3&height=4',
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $parts = \parse_url($payload[0]['sample_identities'][0]['thumb_url']);
        $this->assertSame('/wp-json/acx/v1/recognition/face-thumbs/job-1/12', $parts['path']);
        $this->assertSame('http://example.test/media/12.jpg', $payload[0]['sample_identities'][0]['attachment_url']);
        $this->assertSame(
            array(
                'x' => 1,
                'y' => 2,
                'width' => 3,
                'height' => 4,
            ),
            $payload[0]['sample_identities'][0]['bbox']
        );
    }

    public function testMapTopUnlabeledClustersEmitsNullAttachmentUrlWhenUnknown(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-top',
                'label' => '',
                'identity_count' => 1,
                'is_user_confirmed' => 0,
            ],
        ];

        $members = [
            'cluster-top' => [
                [
                    'identity_uuid' => 'identity-99',
                    'attachment_id' => 99,
                    'thumb_path' => '/recognition/face-thumbs/job-y/99?x=1&y=2&width=30&height=40',
                ],
            ],
        ];

        $payload = $this->mapper->map_top_unlabeled_clusters($clusters, $members, 'tenant-1');

        $this->assertNull($payload[0]['representatives'][0]['attachment_url']);
        $this->assertNull($payload[0]['representatives'][0]['bbox']);
    }

    public function testMapTopUnlabeledClustersFallsBackToClusterRepresentativeMetadata(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-top',
                'label' => '',
                'identity_count' => 2,
                'is_user_confirmed' => 0,
                'representative_id' => 'identity-99',
                'is_pinned' => 1,
            ],
        ];

        $members = [
            'cluster-top' => [
                [
                    'identity_uuid' => 'identity-99',
                    'attachment_id' => 99,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_top_unlabeled_clusters($clusters, $members, 'tenant-1');

        $this->assertTrue($payload[0]['representatives'][0]['is_pinned']);
    }

    public function testMapTopUnlabeledClustersReadsSuggestedLabelFromRow(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-inferred',
                'label' => '',
                'identity_count' => 5,
                'is_user_confirmed' => 0,
                'suggested_label' => 'Alice',
                'suggested_label_source' => 'similar_cluster',
                'suggested_label_confidence' => '0.92',
                'suggested_target_cluster_id' => 'cluster-target',
            ],
        ];

        $payload = $this->mapper->map_top_unlabeled_clusters($clusters, [], 'tenant-1');

        $this->assertSame('Alice', $payload[0]['suggested_label']);
        $this->assertSame('similar_cluster', $payload[0]['suggested_label_source']);
        $this->assertEqualsWithDelta(0.92, $payload[0]['suggested_label_confidence'], 0.001);
        $this->assertSame('cluster-target', $payload[0]['suggested_target_cluster_id']);
    }

    public function testMapTopUnlabeledClustersReturnsNullWhenSuggestedLabelAbsent(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-nosugg',
                'label' => '',
                'identity_count' => 2,
                'is_user_confirmed' => 0,
            ],
        ];

        $payload = $this->mapper->map_top_unlabeled_clusters($clusters, [], 'tenant-1');

        $this->assertNull($payload[0]['suggested_label']);
        $this->assertNull($payload[0]['suggested_label_source']);
        $this->assertNull($payload[0]['suggested_label_confidence']);
        $this->assertNull($payload[0]['suggested_target_cluster_id']);
    }

    public function testMapTopUnlabeledClustersTreatsSyntheticClusterLabelsAsAutoLabels(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-auto',
                'label' => 'cluster-12345678',
                'identity_count' => 2,
                'is_user_confirmed' => 0,
            ],
        ];

        $payload = $this->mapper->map_top_unlabeled_clusters($clusters, [], 'tenant-1');

        $this->assertNull($payload[0]['label']);
        $this->assertFalse($payload[0]['is_labeled']);
        $this->assertTrue($payload[0]['is_auto_label']);
        $this->assertFalse($payload[0]['user_confirmed']);
    }

    public function testMapClusterListTreatsSyntheticClusterLabelsAsAutoLabels(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-list-auto',
                'label' => 'cluster-12345678',
                'identity_count' => 3,
                'is_user_confirmed' => 0,
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, []);

        $this->assertNull($payload[0]['label']);
        $this->assertTrue($payload[0]['is_auto_label']);
    }

    public function testMapClusterListPassesThroughPersonUuidFromPersonsJoin(): void
    {
        $clusters = [
            [
                'cluster_uuid' => 'cluster-bound',
                'label' => 'Alice',
                'identity_count' => 2,
                'person_uuid' => '11111111-1111-1111-1111-111111111111',
            ],
            [
                'cluster_uuid' => 'cluster-unresolved',
                'label' => '',
                'identity_count' => 3,
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, []);

        $this->assertSame('11111111-1111-1111-1111-111111111111', $payload[0]['person_uuid']);
        $this->assertArrayHasKey('person_uuid', $payload[1]);
        $this->assertNull($payload[1]['person_uuid']);
    }

    public function testMapClusterListDoesNotInventTopologyFields(): void
    {
        $payload = $this->mapper->map_cluster_list(
            [
                [
                    'cluster_uuid' => 'cluster-plain',
                    'label' => 'Bob',
                    'identity_count' => 2,
                    'person_uuid' => '22222222-2222-2222-2222-222222222222',
                    'merged_into_cluster_id' => 'should-not-pass',
                    'superseded_by' => 'should-not-pass',
                    'status' => 'merged',
                ],
            ],
            []
        );

        $this->assertSame('22222222-2222-2222-2222-222222222222', $payload[0]['person_uuid']);
        $this->assertArrayNotHasKey('merged_into_cluster_id', $payload[0]);
        $this->assertArrayNotHasKey('superseded_by', $payload[0]);
        $this->assertArrayNotHasKey('status', $payload[0]);
    }

    public function testMapClusterDetailPassesThroughPersonUuid(): void
    {
        $payload = $this->mapper->map_cluster_detail(
            [
                'cluster_uuid' => 'cluster-detail',
                'label' => 'Dana',
                'identity_count' => 4,
                'person_uuid' => '33333333-3333-3333-3333-333333333333',
            ],
            []
        );

        $this->assertSame('33333333-3333-3333-3333-333333333333', $payload['person_uuid']);
    }

    public function testMapClusterListNormalizesEmptyAndWhitespacePersonUuidToNull(): void
    {
        $payload = $this->mapper->map_cluster_list(
            [
                [
                    'cluster_uuid' => 'cluster-empty',
                    'label' => 'Empty',
                    'identity_count' => 2,
                    'person_uuid' => '',
                ],
                [
                    'cluster_uuid' => 'cluster-whitespace',
                    'label' => 'Whitespace',
                    'identity_count' => 2,
                    'person_uuid' => '   ',
                ],
            ],
            []
        );

        $this->assertArrayHasKey('person_uuid', $payload[0]);
        $this->assertNull($payload[0]['person_uuid']);
        $this->assertArrayHasKey('person_uuid', $payload[1]);
        $this->assertNull($payload[1]['person_uuid']);
    }

    public function testMapClusterDetailNormalizesEmptyAndWhitespacePersonUuidToNull(): void
    {
        $empty = $this->mapper->map_cluster_detail(
            [
                'cluster_uuid' => 'cluster-empty-detail',
                'label' => 'Empty',
                'identity_count' => 2,
                'person_uuid' => '',
            ],
            []
        );
        $whitespace = $this->mapper->map_cluster_detail(
            [
                'cluster_uuid' => 'cluster-whitespace-detail',
                'label' => 'Whitespace',
                'identity_count' => 2,
                'person_uuid' => " \t ",
            ],
            []
        );

        $this->assertArrayHasKey('person_uuid', $empty);
        $this->assertNull($empty['person_uuid']);
        $this->assertArrayHasKey('person_uuid', $whitespace);
        $this->assertNull($whitespace['person_uuid']);
    }

    public function testMapClusterListEmitsNullBboxWhenBboxJsonIsNotValidJson(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 1,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-1',
                    'attachment_id' => 12,
                    'bbox_json' => 'not-json',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertArrayHasKey('bbox', $payload[0]['sample_identities'][0]);
        $this->assertNull($payload[0]['sample_identities'][0]['bbox']);
        $this->assertSame('identity-1', $payload[0]['sample_identities'][0]['identity_id']);
    }

    public function testMapClusterListEmitsNullBboxWhenPixelsOmitAnEdge(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';
        $GLOBALS['__ac_attachment_urls'][13] = 'http://example.test/media/13.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 2,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-omit-height',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3}}',
                ],
                [
                    'identity_uuid' => 'identity-omit-y',
                    'attachment_id' => 13,
                    'bbox_json' => '{"pixels":{"x":1,"width":3,"height":4}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertArrayHasKey('bbox', $payload[0]['sample_identities'][0]);
        $this->assertNull($payload[0]['sample_identities'][0]['bbox']);
        $this->assertSame('identity-omit-height', $payload[0]['sample_identities'][0]['identity_id']);
        $this->assertArrayHasKey('bbox', $payload[0]['sample_identities'][1]);
        $this->assertNull($payload[0]['sample_identities'][1]['bbox']);
        $this->assertSame('identity-omit-y', $payload[0]['sample_identities'][1]['identity_id']);
    }

    public function testMapClusterListEmitsNullBboxWhenPixelsIsNotAnObject(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';
        $GLOBALS['__ac_attachment_urls'][13] = 'http://example.test/media/13.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 2,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-scalar-pixels',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":5}',
                ],
                [
                    'identity_uuid' => 'identity-list-pixels',
                    'attachment_id' => 13,
                    'bbox_json' => '{"pixels":[1,2,3,4]}',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertArrayHasKey('bbox', $payload[0]['sample_identities'][0]);
        $this->assertNull($payload[0]['sample_identities'][0]['bbox']);
        $this->assertSame('identity-scalar-pixels', $payload[0]['sample_identities'][0]['identity_id']);
        $this->assertArrayHasKey('bbox', $payload[0]['sample_identities'][1]);
        $this->assertNull($payload[0]['sample_identities'][1]['bbox']);
        $this->assertSame('identity-list-pixels', $payload[0]['sample_identities'][1]['identity_id']);
    }

    public function testMapClusterListEmitsNullBboxWhenEdgeIsNonNumeric(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 1,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-non-numeric-width',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":"abc","height":4}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertArrayHasKey('bbox', $payload[0]['sample_identities'][0]);
        $this->assertNull($payload[0]['sample_identities'][0]['bbox']);
        $this->assertSame('identity-non-numeric-width', $payload[0]['sample_identities'][0]['identity_id']);
    }

    public function testMapClusterListEmitsNullBboxWhenExtentsAreNegative(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';
        $GLOBALS['__ac_attachment_urls'][13] = 'http://example.test/media/13.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 2,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-negative-width',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":-40,"height":4}}',
                ],
                [
                    'identity_uuid' => 'identity-negative-height',
                    'attachment_id' => 13,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":-40}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertArrayHasKey('bbox', $payload[0]['sample_identities'][0]);
        $this->assertNull($payload[0]['sample_identities'][0]['bbox']);
        $this->assertSame('identity-negative-width', $payload[0]['sample_identities'][0]['identity_id']);
        $this->assertArrayHasKey('bbox', $payload[0]['sample_identities'][1]);
        $this->assertNull($payload[0]['sample_identities'][1]['bbox']);
        $this->assertSame('identity-negative-height', $payload[0]['sample_identities'][1]['identity_id']);
    }

    public function testMapClusterListEmitsNullBboxWhenWidthIsZero(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 1,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-zero-width',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":0,"height":4}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertArrayHasKey('bbox', $payload[0]['sample_identities'][0]);
        $this->assertNull($payload[0]['sample_identities'][0]['bbox']);
        $this->assertSame('identity-zero-width', $payload[0]['sample_identities'][0]['identity_id']);
    }

    public function testMapClusterListEmitsIntegerBboxWhenPixelsAreNumericAndPositive(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';

        $clusters = [
            [
                'cluster_uuid' => 'cluster-1',
                'label' => 'Alice',
                'identity_count' => 1,
            ],
        ];

        $members = [
            'cluster-1' => [
                [
                    'identity_uuid' => 'identity-happy-bbox',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":{"x":10,"y":20,"width":30,"height":40}}',
                ],
            ],
        ];

        $payload = $this->mapper->map_cluster_list($clusters, $members);

        $this->assertSame('identity-happy-bbox', $payload[0]['sample_identities'][0]['identity_id']);
        $this->assertSame(
            array(
                'x' => 10,
                'y' => 20,
                'width' => 30,
                'height' => 40,
            ),
            $payload[0]['sample_identities'][0]['bbox']
        );
    }

    public function testMapClusterDetailEmitsBboxOnHappyPathAndNullWhenAbsent(): void
    {
        $GLOBALS['__ac_attachment_urls'][12] = 'http://example.test/media/12.jpg';
        $GLOBALS['__ac_attachment_urls'][13] = 'http://example.test/media/13.jpg';

        $payload = $this->mapper->map_cluster_detail(
            [
                'cluster_uuid' => 'cluster-detail-bbox',
                'label' => 'Dana',
                'identity_count' => 2,
            ],
            [
                [
                    'identity_uuid' => 'identity-with-bbox',
                    'attachment_id' => 12,
                    'bbox_json' => '{"pixels":{"x":1,"y":2,"width":3,"height":4}}',
                ],
                [
                    'identity_uuid' => 'identity-without-bbox',
                    'attachment_id' => 13,
                ],
            ]
        );

        $this->assertSame('cluster-detail-bbox', $payload['id']);
        $this->assertSame('Dana', $payload['label']);
        $this->assertSame('identity-with-bbox', $payload['sample_identities'][0]['identity_id']);
        $this->assertSame(
            array(
                'x' => 1,
                'y' => 2,
                'width' => 3,
                'height' => 4,
            ),
            $payload['sample_identities'][0]['bbox']
        );
        $this->assertSame('identity-without-bbox', $payload['sample_identities'][1]['identity_id']);
        $this->assertArrayHasKey('bbox', $payload['sample_identities'][1]);
        $this->assertNull($payload['sample_identities'][1]['bbox']);
        $this->assertSame(
            array(
                'x' => 1,
                'y' => 2,
                'width' => 3,
                'height' => 4,
            ),
            $payload['representative_identity']['bbox']
        );
    }
}
