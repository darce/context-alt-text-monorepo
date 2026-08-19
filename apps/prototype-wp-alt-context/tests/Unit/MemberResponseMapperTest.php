<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Mappers\MemberResponseMapper
 */
class MemberResponseMapperTest extends TestCase
{
    private MemberResponseMapper $mapper;

    protected function setUp(): void
    {
        parent::setUp();
        $this->mapper = new MemberResponseMapper();
    }

    public function testMapClusterMembersHydratesMediaUrls(): void
    {
        $GLOBALS['__ac_attachment_urls'][50] = 'http://example.test/media/50.jpg';

        $rows = [
            [
                'identity_uuid' => 'identity-50',
                'attachment_id' => 50,
                'similarity' => 0.91,
                'bbox_json' => '{"pixels":{"x":2,"y":3,"width":4,"height":5}}',
            ],
        ];

        $payload = $this->mapper->map_cluster_members($rows);

        $this->assertSame('identity-50', $payload[0]['identity_id']);
        $this->assertSame('http://example.test/media/50.jpg', $payload[0]['thumb_url']);
        $this->assertSame('http://example.test/media/50.jpg', $payload[0]['media_url']);
        $this->assertFalse($payload[0]['is_pinned']);
    }

    public function testMapMediaIdentitiesGroupsByMediaId(): void
    {
        $rows = [
            [
                'identity_uuid' => 'identity-1',
                'attachment_id' => 101,
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
                'is_pinned' => 'true',
            ],
        ];

        $payload = $this->mapper->map_media_identities($rows);

        $this->assertArrayHasKey('101', $payload);
        $this->assertSame('identity-1', $payload['101'][0]['identity_id']);
        $this->assertTrue($payload['101'][0]['is_pinned']);
    }

    public function testMapMediaIdentitiesFallsBackToClusterRepresentativeMetadata(): void
    {
        $rows = [
            [
                'identity_uuid' => 'identity-2',
                'attachment_id' => 202,
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
                'representative_id' => 'identity-2',
                'is_pinned' => 1,
            ],
        ];

        $payload = $this->mapper->map_media_identities($rows);

        $this->assertSame('identity-2', $payload['202'][0]['representative_id']);
        $this->assertTrue($payload['202'][0]['is_pinned']);
    }

    public function testMapAppliesPersonNameOverStaleClusterLabel(): void
    {
        $payload = $this->mapper->map_media_identities([
            [
                'identity_uuid' => 'bound',
                'attachment_id' => 9,
                'cluster_label' => 'stale',
                'person_name' => 'Ada Lovelace',
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
            ],
        ]);

        $this->assertSame('Ada Lovelace', $payload['9'][0]['cluster_label']);
    }

    public function testMapMediaIdentitiesAppliesLabelAuthorityOnLocalProjectionRows(): void
    {
        $payload = $this->mapper->map_media_identities([
            [
                'identity_uuid' => 'unbound',
                'attachment_id' => 22,
                'cluster_label' => 'Tory Guzman',
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
            ],
            [
                'identity_uuid' => 'auto',
                'attachment_id' => 22,
                'cluster_label' => 'cluster-abcdef01',
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
            ],
            [
                'identity_uuid' => 'bound',
                'attachment_id' => 22,
                'cluster_label' => 'stale',
                'person_name' => 'Ada Lovelace',
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
            ],
        ]);

        $this->assertNull($payload['22'][0]['cluster_label']);
        $this->assertSame('cluster-abcdef01', $payload['22'][1]['cluster_label']);
        $this->assertSame('Ada Lovelace', $payload['22'][2]['cluster_label']);
    }

    public function testMapClusterMembersTreatsSyntheticClusterLabelsAsAutoLabels(): void
    {
        $rows = [
            [
                'identity_uuid' => 'identity-auto',
                'attachment_id' => 303,
                'cluster_uuid' => 'cluster-303',
                'cluster_label' => 'cluster-12345678',
                'is_user_confirmed' => 0,
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
            ],
        ];

        $payload = $this->mapper->map_cluster_members($rows);

        $this->assertSame('cluster-12345678', $payload[0]['cluster_label']);
        $this->assertTrue($payload[0]['is_auto_label']);
    }

    public function testMapMediaIdentitiesAppliesLabelAuthorityRows(): void
    {
        $payload = $this->mapper->map_media_identities([
            [
                'identity_uuid' => 'unbound',
                'attachment_id' => 1,
                'cluster_label' => null,
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
            ],
            [
                'identity_uuid' => 'auto',
                'attachment_id' => 1,
                'cluster_label' => 'cluster-abcdef01',
                'is_user_confirmed' => 0,
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
            ],
            [
                'identity_uuid' => 'bound',
                'attachment_id' => 1,
                'cluster_label' => 'Ada Lovelace',
                'person_name' => 'Ada Lovelace',
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
            ],
        ]);

        $this->assertNull($payload['1'][0]['cluster_label']);
        $this->assertSame('cluster-abcdef01', $payload['1'][1]['cluster_label']);
        $this->assertTrue($payload['1'][1]['is_auto_label']);
        $this->assertSame('Ada Lovelace', $payload['1'][2]['cluster_label']);
    }

    public function testMapClusterMembersPrefersFaceThumbPathOverAttachmentUrl(): void
    {
        $GLOBALS['__ac_attachment_urls'][50] = 'http://example.test/uploads/50.jpg';

        $rows = [
            [
                'identity_uuid' => 'identity-50',
                'attachment_id' => 50,
                'thumb_path' => '/recognition/face-thumbs/job-50/50?x=2&y=3&width=40&height=50',
                'bbox_json' => '{"pixels":{"x":2,"y":3,"width":40,"height":50}}',
            ],
        ];

        $payload = $this->mapper->map_cluster_members($rows);

        $parts = \parse_url($payload[0]['thumb_url']);
        $this->assertSame('/wp-json/acx/v1/recognition/face-thumbs/job-50/50', $parts['path']);
        $this->assertStringNotContainsString('/uploads/50.jpg', $payload[0]['thumb_url']);
    }

    /**
     * E21-15 / STOR-07: blob thumb_url stays first-choice; durable attachment_url + bbox
     * are emitted beside it so clients can crop after scan-time blobs are cleaned up.
     */
    public function testMapClusterMembersEmitsAttachmentUrlAndBboxBesideFaceThumb(): void
    {
        $GLOBALS['__ac_attachment_urls'][50] = 'http://example.test/uploads/50.jpg';

        $rows = [
            [
                'identity_uuid' => 'identity-50',
                'attachment_id' => 50,
                'thumb_path' => '/recognition/face-thumbs/job-50/50?x=2&y=3&width=40&height=50',
                'bbox_json' => '{"pixels":{"x":2,"y":3,"width":40,"height":50}}',
            ],
        ];

        $payload = $this->mapper->map_cluster_members($rows);

        $parts = \parse_url($payload[0]['thumb_url']);
        $this->assertSame('/wp-json/acx/v1/recognition/face-thumbs/job-50/50', $parts['path']);
        $this->assertSame('http://example.test/uploads/50.jpg', $payload[0]['attachment_url']);
        $this->assertSame(
            array(
                'x' => 2,
                'y' => 3,
                'width' => 40,
                'height' => 50,
            ),
            $payload[0]['bbox']
        );
    }

    public function testMapClusterMembersEmitsNullAttachmentUrlWhenUnknown(): void
    {
        $rows = [
            [
                'identity_uuid' => 'identity-50',
                'attachment_id' => 50,
                'thumb_path' => '/recognition/face-thumbs/job-50/50?x=2&y=3&width=40&height=50',
            ],
        ];

        $payload = $this->mapper->map_cluster_members($rows);

        $this->assertNull($payload[0]['attachment_url']);
        $this->assertNull($payload[0]['bbox']);
    }

    /**
     * UXW2-4-R8-02 / M3: member + media-identities REST rows must copy SQL
     * label_state, and fall back to the trait when the column is absent.
     */
    public function testMapClusterMembersAndMediaIdentitiesEmitLabelState(): void
    {
        $members = $this->mapper->map_cluster_members(
            [
                [
                    'identity_uuid' => 'id-person',
                    'attachment_id' => 11,
                    'cluster_label' => 'Ada',
                    'person_name' => 'Ada Lovelace',
                    'label_state' => 'person',
                    'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
                ],
            ]
        );

        $this->assertArrayHasKey('label_state', $members[0]);
        $this->assertSame('person', $members[0]['label_state']);

        $media = $this->mapper->map_media_identities(
            [
                [
                    'identity_uuid' => 'id-unbound',
                    'attachment_id' => 22,
                    'cluster_label' => 'Tory Guzman',
                    'label_state' => 'unbound',
                    'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
                ],
            ]
        );

        $this->assertArrayHasKey('label_state', $media['22'][0]);
        $this->assertSame('unbound', $media['22'][0]['label_state']);

        $fallback = $this->mapper->map_cluster_members(
            [
                [
                    'identity_uuid' => 'id-fallback',
                    'attachment_id' => 33,
                    'cluster_label' => 'Tory Guzman',
                    'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
                ],
            ]
        );

        $this->assertArrayHasKey('label_state', $fallback[0]);
        $this->assertSame('unbound', $fallback[0]['label_state']);
    }
}
