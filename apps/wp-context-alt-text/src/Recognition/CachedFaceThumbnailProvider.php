<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

/**
 * Thumbnail provider that uses base64-encoded thumbnails from the recognition service.
 * 
 * The recognition service generates thumbnails during face detection and includes them
 * in the API response. This provider simply converts the base64 data to a data URI
 * for display in the browser.
 */
final class CachedFaceThumbnailProvider implements FaceThumbnailProvider
{
    /**
     * @param array<string,mixed> $face
     */
    public function generateThumbnail(array $face): ?string
    {
        // Use thumbnail from recognition service if available
        $thumbnail = $face['thumbnail'] ?? null;
        
        if (!is_string($thumbnail) || trim($thumbnail) === '') {
            error_log(sprintf(
                '[CachedFaceThumbnailProvider] No thumbnail provided from recognition service. Face keys: %s',
                implode(', ', array_keys($face))
            ));
            return null;
        }
        
        error_log(sprintf(
            '[CachedFaceThumbnailProvider] Using thumbnail from recognition service (length: %d chars)',
            strlen($thumbnail)
        ));
        
        // Return as data URI for direct display
        return 'data:image/jpeg;base64,' . $thumbnail;
    }
}
