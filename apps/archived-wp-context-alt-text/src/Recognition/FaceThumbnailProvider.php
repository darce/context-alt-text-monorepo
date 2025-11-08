<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

/**
 * Generates or retrieves cached thumbnails for face crops.
 */
interface FaceThumbnailProvider
{
    /**
     * @param array<string,mixed> $face Normalised face payload from ClusteringService.
     */
    public function generateThumbnail(array $face): ?string;
}
