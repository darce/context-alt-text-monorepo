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
            ['cluster-stale-count' => []]
        );

        $this->assertSame(0, $payload[0]['identity_count']);
        $this->assertStringContainsString('cluster-stale-count', \implode("\n", $GLOBALS['__ac_error_log']));
        $this->assertStringContainsString('projected=1 observed=0', \implode("\n", $GLOBALS['__ac_error_log']));
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
}
