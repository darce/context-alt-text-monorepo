<?php

declare(strict_types=1);

use ContextAltText\Recognition\ImageCropUtility;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class ImageCropUtilityTest extends TestCase
{
    private ImageCropUtility $utility;

    protected function setUp(): void
    {
        parent::setUp();

        // Reset global state
        $GLOBALS['__cat_posts'] = [];
        $GLOBALS['__cat_attached_file'] = [];
        $GLOBALS['__cat_image_editor'] = null;
        $GLOBALS['__cat_image_editor_error'] = null;
        $GLOBALS['__cat_existing_files'] = []; // Track which files "exist" in tests

        $this->utility = new ImageCropUtility();
    }

    public function test_returns_error_for_invalid_attachment(): void
    {
        // No attachment in global state
        $result = $this->utility->cropFaceRegion(99999, [
            'x' => 0.1,
            'y' => 0.2,
            'width' => 0.3,
            'height' => 0.4,
        ]);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('invalid_attachment', $result->get_error_code());
    }

    public function test_returns_error_for_invalid_bbox_coordinates(): void
    {
        // Mock attachment
        $GLOBALS['__cat_posts'][123] = (object) [
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        // Missing width
        $result = $this->utility->cropFaceRegion(123, [
            'x' => 0.1,
            'y' => 0.2,
            'height' => 0.4,
        ]);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('invalid_bbox', $result->get_error_code());
    }

    public function test_returns_error_when_attachment_file_missing(): void
    {
        // Mock attachment without file
        $GLOBALS['__cat_posts'][123] = (object) [
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        $GLOBALS['__cat_attached_file'][123] = null;

        $result = $this->utility->cropFaceRegion(123, [
            'x' => 0.1,
            'y' => 0.2,
            'width' => 0.3,
            'height' => 0.4,
        ]);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('file_not_found', $result->get_error_code());
    }

    public function test_crops_and_resizes_face_region(): void
    {
        // Setup attachment
        $attachmentId = 123;
        $filePath = '/fake/path/image.jpg';
        
        $GLOBALS['__cat_posts'][$attachmentId] = (object)[
            'ID' => $attachmentId,
            'post_type' => 'attachment',
        ];
        $GLOBALS['__cat_attached_file'][$attachmentId] = $filePath;
        $GLOBALS['__cat_existing_files'][$filePath] = true; // Mark file as "existing"

        // Mock image editor
        $mockImage = new class {
            public function get_size(): array
            {
                return ['width' => 1000, 'height' => 800];
            }

            public function crop(int $x, int $y, int $width, int $height): bool
            {
                return true;
            }

            public function resize(int $width, int $height, bool $crop = false): bool
            {
                return true;
            }

            public function get_quality(): int
            {
                return 90;
            }

            public function set_quality(int $quality): bool
            {
                return true;
            }

            public function stream(string $mime_type): bool
            {
                echo base64_encode('fake-image-data');
                return true;
            }
        };

        $GLOBALS['__cat_image_editor'] = $mockImage;

        $result = $this->utility->cropFaceRegion($attachmentId, [
            'x' => 0.2,
            'y' => 0.3,
            'width' => 0.15,
            'height' => 0.2,
        ]);

        $this->assertIsString($result);
        $this->assertStringStartsWith('data:image/jpeg;base64,', $result);
    }

    public function test_handles_bbox_at_image_edges(): void
    {
        // Mock attachment
        $filePath = '/fake/path/image.jpg';
        
        $GLOBALS['__cat_posts'][123] = (object) [
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        $GLOBALS['__cat_attached_file'][123] = $filePath;
        $GLOBALS['__cat_existing_files'][$filePath] = true; // Mark file as "existing"

        $mockImage = new class {
            public $width = 800;
            public $height = 600;
            public $croppedRegion = null;

            public function get_size(): array
            {
                return ['width' => $this->width, 'height' => $this->height];
            }

            public function crop(int $x, int $y, int $width, int $height): bool
            {
                $this->croppedRegion = ['x' => $x, 'y' => $y, 'width' => $width, 'height' => $height];
                return true;
            }

            public function resize(int $width, int $height, bool $crop = false): bool
            {
                return true;
            }

            public function get_quality(): int
            {
                return 90;
            }

            public function set_quality(int $quality): bool
            {
                return true;
            }

            public function stream(string $mime_type): bool
            {
                echo base64_encode('fake-image-data');
                return true;
            }
        };

        $GLOBALS['__cat_image_editor'] = $mockImage;

        // Bbox at right edge
        $result = $this->utility->cropFaceRegion(123, [
            'x' => 0.8,
            'y' => 0.1,
            'width' => 0.2,  // Goes to 1.0 (edge)
            'height' => 0.3,
        ]);

        $this->assertIsString($result);

        // Should clamp to image bounds (800px width)
        $this->assertSame(640, $mockImage->croppedRegion['x']);
        $this->assertLessThanOrEqual(800, $mockImage->croppedRegion['x'] + $mockImage->croppedRegion['width']);
    }

    public function test_returns_error_on_crop_failure(): void
    {
        $filePath = '/fake/path/image.jpg';
        
        $GLOBALS['__cat_posts'][123] = (object) [
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        $GLOBALS['__cat_attached_file'][123] = $filePath;
        $GLOBALS['__cat_existing_files'][$filePath] = true; // Mark file as "existing"

        // Mock image that fails to crop
        $mockImage = new class {
            public function get_size(): array
            {
                return ['width' => 1000, 'height' => 800];
            }

            public function crop(int $x, int $y, int $width, int $height): bool
            {
                return false; // Crop fails
            }

            public function resize(int $width, int $height): bool
            {
                return true;
            }

            public function stream(string $mimeType): string
            {
                return 'fake-image-data';
            }
        };

        $GLOBALS['__cat_image_editor'] = $mockImage;

        $result = $this->utility->cropFaceRegion(123, [
            'x' => 0.1,
            'y' => 0.2,
            'width' => 0.3,
            'height' => 0.4,
        ]);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('crop_failed', $result->get_error_code());
    }

    public function test_returns_error_on_resize_failure(): void
    {
        $filePath = '/fake/path/image.jpg';
        
        $GLOBALS['__cat_posts'][123] = (object) [
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        $GLOBALS['__cat_attached_file'][123] = $filePath;
        $GLOBALS['__cat_existing_files'][$filePath] = true; // Mark file as "existing"

        // Mock image that fails to resize
        $mockImage = new class {
            public function get_size(): array
            {
                return ['width' => 1000, 'height' => 800];
            }

            public function crop(int $x, int $y, int $width, int $height): bool
            {
                return true;
            }

            public function resize(int $width, int $height, bool $crop = false): bool
            {
                return false; // Resize fails
            }

            public function stream(string $mime_type = 'image/jpeg'): bool
            {
                return true;
            }
        };

        $GLOBALS['__cat_image_editor'] = $mockImage;

        $result = $this->utility->cropFaceRegion(123, [
            'x' => 0.1,
            'y' => 0.2,
            'width' => 0.3,
            'height' => 0.4,
        ]);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('resize_failed', $result->get_error_code());
    }

    public function test_validates_bbox_values_are_between_0_and_1(): void
    {
        $GLOBALS['__cat_posts'][123] = (object) [
            'ID' => 123,
            'post_type' => 'attachment',
        ];

        // Bbox with value > 1.0
        $result = $this->utility->cropFaceRegion(123, [
            'x' => 0.1,
            'y' => 0.2,
            'width' => 1.5, // Invalid
            'height' => 0.4,
        ]);

        $this->assertInstanceOf(\WP_Error::class, $result);
        $this->assertSame('invalid_bbox', $result->get_error_code());
    }
}
