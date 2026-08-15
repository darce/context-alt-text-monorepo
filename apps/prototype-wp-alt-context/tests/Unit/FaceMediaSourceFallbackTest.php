<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Tests\TestCase;

/**
 * E21-21: a deleted WordPress original must not be served as a 404 beside a
 * bbox in its pixel space. The mapper degrades to the largest surviving
 * sub-size and rescales the bbox into it, or reports no image at all.
 *
 * @covers \AltContext\Sovereign\Mappers\MapsResponseFields
 */
class FaceMediaSourceFallbackTest extends TestCase
{
    private const MEDIA_ID = 6712;

    private string $uploadDir = '';

    private MemberResponseMapper $mapper;

    protected function setUp(): void
    {
        parent::setUp();
        $this->mapper = new MemberResponseMapper();
        $this->uploadDir = sys_get_temp_dir() . '/acx-e21-21-' . uniqid('', true);
        mkdir($this->uploadDir, 0777, true);
    }

    protected function tearDown(): void
    {
        if ('' !== $this->uploadDir && is_dir($this->uploadDir)) {
            foreach ((array) glob($this->uploadDir . '/*') as $file) {
                if (is_string($file)) {
                    unlink($file);
                }
            }
            rmdir($this->uploadDir);
        }
        parent::tearDown();
    }

    public function testKeepsOriginalUrlAndBboxWhenTheFileIsStillOnDisk(): void
    {
        $this->seedAttachment(originalOnDisk: true, sizeFilesOnDisk: ['medium_large']);

        $member = $this->mapMember();

        $this->assertSame('http://example.test/uploads/original.jpg', $member['media_url']);
        $this->assertSame('http://example.test/uploads/original.jpg', $member['attachment_url']);
        $this->assertSame(['x' => 380, 'y' => 72, 'width' => 120, 'height' => 162], $member['bbox']);
    }

    public function testFallsBackToLargestSurvivingSizeAndRescalesTheBbox(): void
    {
        $this->seedAttachment(
            originalOnDisk: false,
            sizeFilesOnDisk: ['thumbnail', 'medium', 'medium_large'],
        );

        $member = $this->mapMember();

        $this->assertSame('http://example.test/uploads/original-768x512.jpg', $member['media_url']);
        $this->assertSame('http://example.test/uploads/original-768x512.jpg', $member['attachment_url']);
        // 768 / 800 = 0.96 applied to {380, 72, 120, 162}.
        $this->assertSame(['x' => 365, 'y' => 69, 'width' => 115, 'height' => 156], $member['bbox']);
    }

    public function testSkipsRegisteredSizesWhoseFilesAreAlsoDeleted(): void
    {
        $this->seedAttachment(originalOnDisk: false, sizeFilesOnDisk: ['medium']);

        $member = $this->mapMember();

        $this->assertSame('http://example.test/uploads/original-300x200.jpg', $member['media_url']);
        // 300 / 800 = 0.375 applied to {380, 72, 120, 162}.
        $this->assertSame(['x' => 143, 'y' => 27, 'width' => 45, 'height' => 61], $member['bbox']);
    }

    public function testReportsNoImageWhenEveryLocalFileIsGone(): void
    {
        $this->seedAttachment(originalOnDisk: false, sizeFilesOnDisk: []);

        $member = $this->mapMember();

        $this->assertNull($member['media_url']);
        $this->assertNull($member['attachment_url']);
        $this->assertNull($member['thumb_url']);
        $this->assertNull($member['bbox']);
    }

    public function testDropsTheBboxRatherThanGuessingWhenTheAttachmentWidthIsUnknown(): void
    {
        $this->seedAttachment(originalOnDisk: false, sizeFilesOnDisk: ['medium_large']);
        unset($GLOBALS['__ac_attachment_metadata'][self::MEDIA_ID]['width']);

        $member = $this->mapMember();

        $this->assertSame('http://example.test/uploads/original-768x512.jpg', $member['media_url']);
        $this->assertNull($member['bbox']);
    }

    public function testLeavesOffloadedMediaUntouchedWhenNoLocalUploadDirExists(): void
    {
        $this->seedAttachment(originalOnDisk: false, sizeFilesOnDisk: []);
        $GLOBALS['__ac_attached_file'][self::MEDIA_ID] = '/nonexistent-acx-e21-21/uploads/original.jpg';

        $member = $this->mapMember();

        $this->assertSame('http://example.test/uploads/original.jpg', $member['media_url']);
        $this->assertSame(['x' => 380, 'y' => 72, 'width' => 120, 'height' => 162], $member['bbox']);
    }

    public function testDedicatedFaceThumbBlobStillWinsOverTheFallbackSize(): void
    {
        $this->seedAttachment(originalOnDisk: false, sizeFilesOnDisk: ['medium_large']);

        $member = $this->mapMember([
            'thumb_path' => 'http://example.test/wp-json/acx/v1/recognition/face-thumbs/rep-1.jpg',
        ]);

        $this->assertSame(
            'http://example.test/wp-json/acx/v1/recognition/face-thumbs/rep-1.jpg',
            $member['thumb_url'],
        );
        $this->assertSame('http://example.test/uploads/original-768x512.jpg', $member['attachment_url']);
        $this->assertSame(['x' => 365, 'y' => 69, 'width' => 115, 'height' => 156], $member['bbox']);
    }

    /**
     * @param array<string,mixed> $overrides
     * @return array<string,mixed>
     */
    private function mapMember(array $overrides = []): array
    {
        $payload = $this->mapper->map_cluster_members([
            array_merge(
                [
                    'identity_uuid' => 'identity-6712',
                    'attachment_id' => self::MEDIA_ID,
                    'similarity' => 0.9,
                    'bbox_json' => '{"pixels":{"x":380,"y":72,"width":120,"height":162}}',
                ],
                $overrides,
            ),
        ]);

        return $payload[0];
    }

    /**
     * @param array<int,string> $sizeFilesOnDisk registered size names to materialize
     */
    private function seedAttachment(bool $originalOnDisk, array $sizeFilesOnDisk): void
    {
        $sizes = [
            'thumbnail' => ['file' => 'original-150x150.jpg', 'width' => 150, 'height' => 150],
            'medium' => ['file' => 'original-300x200.jpg', 'width' => 300, 'height' => 200],
            'medium_large' => ['file' => 'original-768x512.jpg', 'width' => 768, 'height' => 512],
        ];

        $originalPath = $this->uploadDir . '/original.jpg';
        if ($originalOnDisk) {
            file_put_contents($originalPath, 'jpeg');
        }

        foreach ($sizeFilesOnDisk as $sizeName) {
            file_put_contents($this->uploadDir . '/' . $sizes[$sizeName]['file'], 'jpeg');
        }

        $GLOBALS['__ac_attachment_urls'][self::MEDIA_ID] = 'http://example.test/uploads/original.jpg';
        $GLOBALS['__ac_attached_file'][self::MEDIA_ID] = $originalPath;
        $GLOBALS['__ac_attachment_metadata'][self::MEDIA_ID] = [
            'width' => 800,
            'height' => 533,
            'file' => '2025/12/original.jpg',
            'sizes' => $sizes,
        ];

        foreach ($sizes as $sizeName => $size) {
            $GLOBALS['__ac_attachment_image_src'][self::MEDIA_ID][$sizeName] = [
                'http://example.test/uploads/' . $size['file'],
                $size['width'],
                $size['height'],
            ];
        }
    }
}
