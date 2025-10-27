<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use RuntimeException;
use function array_key_exists;
use function base64_decode;
use function file_exists;
use function file_put_contents;
use function is_array;
use function is_string;
use function sprintf;
use function trailingslashit;
use function wp_mkdir_p;
use function wp_json_encode;
use function md5;
use function str_starts_with;

/**
 * Thumbnail provider that caches cropped face images under the uploads directory.
 */
final class CachedFaceThumbnailProvider implements FaceThumbnailProvider
{
    private const DEFAULT_WIDTH = 160;
    private const DEFAULT_HEIGHT = 160;
    private ImageCropUtility $imageCropUtility;

    public function __construct(?ImageCropUtility $imageCropUtility = null)
    {
        $this->imageCropUtility = $imageCropUtility ?? new ImageCropUtility();
    }

    /**
     * @param array<string,mixed> $face
     */
    public function generateThumbnail(array $face): ?string
    {
        $attachmentId = (int) ($face['attachmentId'] ?? 0);
        $bbox = $face['bbox'] ?? null;

        if ($attachmentId <= 0 || !is_array($bbox)) {
            error_log(sprintf('[CachedFaceThumbnailProvider] Invalid input: attachmentId=%d, bbox=%s', $attachmentId, is_array($bbox) ? 'array' : 'not-array'));
            return null;
        }

        $uploadDir = wp_upload_dir();

        if (!is_array($uploadDir) || isset($uploadDir['error']) && $uploadDir['error'] !== false && $uploadDir['error'] !== '') {
            return null;
        }

        $baseDir = trailingslashit((string) ($uploadDir['basedir'] ?? ''));
        $baseUrl = trailingslashit((string) ($uploadDir['baseurl'] ?? ''));

        if ($baseDir === '/' || $baseDir === '') {
            return null;
        }

        $cacheDir = $baseDir . 'cat-face-crops';
        if (!wp_mkdir_p($cacheDir)) {
            return null;
        }

        $hash = substr(md5((string) wp_json_encode([$attachmentId, $bbox])), 0, 16);
        $filename = sprintf('%d-%s.jpg', $attachmentId, $hash);
        $filePath = trailingslashit($cacheDir) . $filename;

        if (!file_exists($filePath)) {
            $result = $this->imageCropUtility->cropFaceRegion($attachmentId, $this->normaliseBoundingBox($bbox));

            if ($result instanceof \WP_Error) {
                error_log(sprintf('[CachedFaceThumbnailProvider] Crop failed for attachment %d: %s', $attachmentId, $result->get_error_message()));
                return null;
            }

            if (!is_string($result) || !str_starts_with($result, 'data:image')) {
                error_log(sprintf('[CachedFaceThumbnailProvider] Invalid crop result for attachment %d: %s', $attachmentId, gettype($result)));
                return null;
            }

            $base64 = explode(',', $result, 2)[1] ?? '';
            $binary = base64_decode($base64);

            if ($binary === false || $binary === '') {
                error_log(sprintf('[CachedFaceThumbnailProvider] Base64 decode failed for attachment %d', $attachmentId));
                return null;
            }

            $bytesWritten = @file_put_contents($filePath, $binary);

            if ($bytesWritten === false) {
                error_log(sprintf('[CachedFaceThumbnailProvider] Failed to write file: %s', $filePath));
                return null;
            }
            
            error_log(sprintf('[CachedFachedThumbnailProvider] Generated thumbnail for attachment %d: %s', $attachmentId, $filename));
        }

        return trailingslashit($baseUrl) . 'cat-face-crops/' . $filename;
    }

    /**
     * The ImageCropUtility expects normalized (0-1) coordinates, so convert when pixel values are provided.
     *
     * @param array<string,mixed> $bbox
     * @return array{x:float,y:float,width:float,height:float}
     */
    private function normaliseBoundingBox(array $bbox): array
    {
        if ($this->bboxIsNormalised($bbox)) {
            return [
                'x' => (float) $bbox['x'],
                'y' => (float) $bbox['y'],
                'width' => (float) $bbox['width'],
                'height' => (float) $bbox['height'],
            ];
        }

        $imageWidth = (float) ($bbox['imageWidth'] ?? self::DEFAULT_WIDTH);
        $imageHeight = (float) ($bbox['imageHeight'] ?? self::DEFAULT_HEIGHT);

        if ($imageWidth <= 0) {
            $imageWidth = self::DEFAULT_WIDTH;
        }

        if ($imageHeight <= 0) {
            $imageHeight = self::DEFAULT_HEIGHT;
        }

        return [
            'x' => max(0.0, (float) ($bbox['x'] ?? 0.0) / $imageWidth),
            'y' => max(0.0, (float) ($bbox['y'] ?? 0.0) / $imageHeight),
            'width' => max(0.0, (float) ($bbox['width'] ?? $imageWidth) / $imageWidth),
            'height' => max(0.0, (float) ($bbox['height'] ?? $imageHeight) / $imageHeight),
        ];
    }

    /**
     * Detect whether bbox coordinates already appear normalised (0-1 range).
     *
     * @param array<string,mixed> $bbox
     */
    private function bboxIsNormalised(array $bbox): bool
    {
        foreach (['x', 'y', 'width', 'height'] as $key) {
            if (!array_key_exists($key, $bbox)) {
                return false;
            }

            $value = (float) $bbox[$key];
            if ($value < 0.0 || $value > 1.0) {
                return false;
            }
        }

        return true;
    }
}
