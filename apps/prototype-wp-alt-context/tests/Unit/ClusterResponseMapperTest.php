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
}
