<?php

declare(strict_types=1);

namespace ContextAltText\Shared\Constants;

/**
 * Shared recognition-related constants referenced across PHP and JS layers.
 */
final class RecognitionConstants
{
    /**
     * Similarity threshold required for local roster suggestions.
     *
     * Aligns with the recognition service default (0.92) so that local-only
     * matching behaves consistently with FAISS-backed matching and avoids
     * aggressive false positives.
     */
    public const LOCAL_SUGGESTION_THRESHOLD = 0.92;
}
