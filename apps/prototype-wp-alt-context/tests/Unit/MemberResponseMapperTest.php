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
        $this->assertSame('http://example.test/media/50.jpg', $payload[0]['media_url']);
    }

    public function testMapMediaIdentitiesGroupsByMediaId(): void
    {
        $rows = [
            [
                'identity_uuid' => 'identity-1',
                'attachment_id' => 101,
                'bbox_json' => '{"pixels":{"x":1,"y":1,"width":1,"height":1}}',
            ],
        ];

        $payload = $this->mapper->map_media_identities($rows);

        $this->assertArrayHasKey('101', $payload);
        $this->assertSame('identity-1', $payload['101'][0]['identity_id']);
    }
}
