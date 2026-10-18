<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Media\JpegXmpInjector;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Media\JpegXmpInjector
 */
class JpegXmpInjectorTest extends TestCase
{
    private JpegXmpInjector $injector;

    protected function setUp(): void
    {
        parent::setUp();
        $this->injector = new JpegXmpInjector();
    }

    public function testInjectPacketInsertsNewApp1WhenXmpMissing(): void
    {
        $jpeg = $this->buildMinimalJpeg([$this->buildApp0Segment()]);
        $packet = '<x:xmpmeta xmlns:x="adobe:ns:meta/"></x:xmpmeta>';

        $updated = $this->injector->inject_packet($jpeg, $packet);

        $this->assertNotSame($jpeg, $updated);
        $this->assertSame($packet, $this->injector->extract_packet($updated));
        $this->assertStringContainsString('JFIF', $updated);
    }

    public function testInjectPacketReplacesExistingXmpAndPreservesNonXmpApp1(): void
    {
        $jpeg = $this->buildMinimalJpeg([
            $this->buildApp0Segment(),
            $this->buildApp1Segment('Exif\x00\x00existing-exif'),
        ]);

        $firstPacket = '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF/></x:xmpmeta>';
        $jpegWithXmp = $this->injector->inject_packet($jpeg, $firstPacket);

        $secondPacket = '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description/></rdf:RDF></x:xmpmeta>';
        $updated = $this->injector->inject_packet($jpegWithXmp, $secondPacket);

        $this->assertSame($secondPacket, $this->injector->extract_packet($updated));
        $this->assertSame(1, substr_count($updated, 'http://ns.adobe.com/xap/1.0/'));
        $this->assertStringContainsString('existing-exif', $updated);
    }

    private function buildMinimalJpeg(array $segments): string
    {
        return "\xFF\xD8" . implode('', $segments) . "\xFF\xDA\x00\x08" . str_repeat("\x00", 6) . 'IMAGEDATA' . "\xFF\xD9";
    }

    private function buildApp0Segment(): string
    {
        $payload = "JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00";
        return "\xFF\xE0" . pack('n', strlen($payload) + 2) . $payload;
    }

    private function buildApp1Segment(string $payload): string
    {
        return "\xFF\xE1" . pack('n', strlen($payload) + 2) . $payload;
    }
}
