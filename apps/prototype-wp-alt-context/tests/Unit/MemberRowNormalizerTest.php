<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\NormalizesMemberRows;
use AltContext\Tests\TestCase;

require_once dirname(__DIR__, 2) . '/src/sovereign/repositories/trait-normalizes-member-rows.php';

/**
 * @covers \AltContext\Sovereign\Repositories\NormalizesMemberRows
 */
class MemberRowNormalizerTest extends TestCase
{
    public function testEncodeBboxJsonUsesProvidedNormalizedCoordinates(): void
    {
        $normalizer = new class() {
            use NormalizesMemberRows;
        };

        $json = $normalizer->encode_bbox_json([
            'bbox' => [
                'pixels' => ['x' => 10, 'y' => 20, 'width' => 30, 'height' => 40],
                'normalized' => ['x' => 0.1, 'y' => 0.2, 'width' => 0.3, 'height' => 0.4],
            ],
        ]);

        $this->assertStringContainsString('"normalized":{"x":0.1,"y":0.2,"width":0.3,"height":0.4}', $json);
        $this->assertStringContainsString('"coordinate_space":"original_image"', $json);
    }

    public function testSanitizeUuidListRejectsInvalidTokens(): void
    {
        $normalizer = new class() {
            use NormalizesMemberRows;
        };

        $this->assertSame(
            ['valid-uuid-1', 'valid-uuid-2'],
            $normalizer->sanitize_uuid_list([' valid-uuid-1 ', 'bad uuid', 'valid-uuid-2'])
        );
    }
}
