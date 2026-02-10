<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Media\PngXmpInjector;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Media\PngXmpInjector
 */
class PngXmpInjectorTest extends TestCase
{
    private PngXmpInjector $injector;

    protected function setUp(): void
    {
        parent::setUp();
        $this->injector = new PngXmpInjector();
    }

    public function testInjectPacketInsertsItxtChunkWhenMissing(): void
    {
        $png = $this->buildMinimalPng();
        $packet = '<x:xmpmeta xmlns:x="adobe:ns:meta/"></x:xmpmeta>';

        $updated = $this->injector->inject_packet($png, $packet);

        $this->assertNotSame($png, $updated);
        $this->assertSame($packet, $this->injector->extract_packet($updated));
        $this->assertSame(1, substr_count($updated, 'XML:com.adobe.xmp'));
    }

    public function testInjectPacketReplacesExistingItxtAndRecomputesCrc(): void
    {
        $png = $this->buildMinimalPng();
        $firstPacket = '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF/></x:xmpmeta>';
        $pngWithXmp = $this->injector->inject_packet($png, $firstPacket);

        $secondPacket = '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description/></rdf:RDF></x:xmpmeta>';
        $updated = $this->injector->inject_packet($pngWithXmp, $secondPacket);

        $this->assertSame($secondPacket, $this->injector->extract_packet($updated));

        $itxtChunk = $this->findChunk($updated, 'iTXt');
        $this->assertNotNull($itxtChunk);
        $this->assertIsArray($itxtChunk);

        $computedCrc = (int) sprintf('%u', crc32('iTXt' . $itxtChunk['data']));
        $this->assertSame($computedCrc, $itxtChunk['crc']);
    }

    private function buildMinimalPng(): string
    {
        $signature = "\x89PNG\r\n\x1A\n";
        $ihdrData = pack('N', 1) . pack('N', 1) . "\x08\x02\x00\x00\x00";
        $idatData = "\x78\x9C\x63\x00\x00\x00\x02\x00\x01";

        return $signature
            . $this->buildChunk('IHDR', $ihdrData)
            . $this->buildChunk('IDAT', $idatData)
            . $this->buildChunk('IEND', '');
    }

    private function buildChunk(string $type, string $data): string
    {
        $crc = (int) sprintf('%u', crc32($type . $data));

        return pack('N', strlen($data)) . $type . $data . pack('N', $crc);
    }

    /**
     * @return array{data:string,crc:int}|null
     */
    private function findChunk(string $png, string $targetType): ?array
    {
        $offset = 8;
        $length = strlen($png);

        while ($offset + 12 <= $length) {
            $chunkLength = unpack('Nlength', substr($png, $offset, 4))['length'];
            $chunkType = substr($png, $offset + 4, 4);
            $dataOffset = $offset + 8;
            $crcOffset = $dataOffset + $chunkLength;

            if ($crcOffset + 4 > $length) {
                return null;
            }

            $chunkData = substr($png, $dataOffset, $chunkLength);
            $chunkCrc = (int) unpack('Ncrc', substr($png, $crcOffset, 4))['crc'];

            if ($chunkType === $targetType) {
                return [
                    'data' => $chunkData,
                    'crc' => $chunkCrc,
                ];
            }

            $offset += 12 + $chunkLength;
        }

        return null;
    }
}
