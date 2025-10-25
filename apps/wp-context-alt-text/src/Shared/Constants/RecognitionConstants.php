<?php

declare(strict_types=1);

namespace ContextAltText\Shared\Constants;

/**
 * Shared recognition-related constants referenced across PHP and JS layers.
 */
final class RecognitionConstants
{
    /**
     * Similarity threshold used when clustering face embeddings locally.
     *
     * When the frontend and backend rely on MediaPipe embeddings for grouping
     * similar faces, this threshold defines the minimum cosine similarity for
     * faces to be merged into the same cluster.
     */
    public const CLUSTER_SIMILARITY_THRESHOLD = 0.65;

    /**
     * Similarity threshold required for local roster suggestions.
     *
     * Aligns with the recognition service default (0.92) so that local-only
     * matching behaves consistently with FAISS-backed matching and avoids
     * aggressive false positives.
     */
    public const LOCAL_SUGGESTION_THRESHOLD = 0.92;
}
