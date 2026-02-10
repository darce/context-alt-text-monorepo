<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Media\XmpImageRegionPacketBuilder;
use AltContext\Tests\TestCase;
use DOMDocument;

/**
 * @covers \AltContext\Media\XmpImageRegionPacketBuilder
 */
class XmpImageRegionPacketBuilderTest extends TestCase
{
    private XmpImageRegionPacketBuilder $builder;

    protected function setUp(): void
    {
        parent::setUp();
        $this->builder = new XmpImageRegionPacketBuilder();
    }

    public function testBuildPacketCreatesValidNamespacesAndFields(): void
    {
        $packet = $this->builder->build_packet([
            [
                'name' => 'Daniel',
                'rbX' => 0.32,
                'rbY' => 0.15,
                'rbW' => 0.18,
                'rbH' => 0.24,
                'acx_pitch' => -12.3,
                'acx_yaw' => 8.7,
                'acx_roll' => -2.1,
                'acx_det_score' => 0.94,
                'acx_landmark_quality' => 0.87,
            ],
        ]);

        $dom = new DOMDocument();
        $this->assertTrue($dom->loadXML($packet));

        $this->assertSame(1, $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::IPTC_NS, 'ImageRegion')->length);
        $this->assertSame(1, $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::IPTC_NS, 'Name')->length);
        $this->assertSame(1, $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::ACX_NS, 'Pitch')->length);
        $this->assertStringNotContainsString('Age', $packet);
        $this->assertStringNotContainsString('Gender', $packet);
    }

    public function testBuildPacketReplacesImageRegionInsteadOfDuplicating(): void
    {
        $initialPacket = $this->builder->build_packet([
            [
                'name' => 'Original',
                'rbX' => 0.10,
                'rbY' => 0.10,
                'rbW' => 0.10,
                'rbH' => 0.10,
                'acx_pitch' => 1.0,
                'acx_yaw' => 1.0,
                'acx_roll' => 1.0,
                'acx_det_score' => 0.5,
                'acx_landmark_quality' => 0.5,
            ],
        ]);

        $updatedPacket = $this->builder->build_packet([
            [
                'name' => 'Updated',
                'rbX' => 0.20,
                'rbY' => 0.20,
                'rbW' => 0.20,
                'rbH' => 0.20,
                'acx_pitch' => 2.0,
                'acx_yaw' => 2.0,
                'acx_roll' => 2.0,
                'acx_det_score' => 0.9,
                'acx_landmark_quality' => 0.9,
            ],
        ], $initialPacket);

        $dom = new DOMDocument();
        $this->assertTrue($dom->loadXML($updatedPacket));

        $this->assertSame(1, $dom->getElementsByTagNameNS(XmpImageRegionPacketBuilder::IPTC_NS, 'ImageRegion')->length);
        $this->assertStringContainsString('Updated', $updatedPacket);
        $this->assertStringNotContainsString('Original', $updatedPacket);
    }
}
