/**
 * Assisted Face Identification Types
 *
 * Shared TypeScript interfaces supporting unknown face discovery, clustering,
 * and assisted identification workflows. These types are referenced across
 * React hooks, API clients, and test fixtures. Keep them in sync with the
 * contracts documented under docs/architecture/contracts.
 */

import type { BoundingBox } from "./people-labeling";

/**
 * Suggestion result mapping a cluster to a roster candidate.
 */
export interface ClusterSuggestion {
    /** Cluster identifier the suggestion is associated with */
    clusterId: string;
    /** Roster identifier for the suggested person */
    rosterId: string;
    /** Display name for the roster entry */
    displayName: string;
    /** Confidence score (0-1) representing similarity */
    confidence: number;
    /** Optional explanation for how the suggestion was generated */
    reason?: string | null;
    /** Relative confidence tier (high, medium, low) */
    confidenceLevel?: "high" | "medium" | "low";
    /** Number of faces contributing to the suggestion */
    matchCount?: number;
    /** Remote face identifiers that matched this suggestion */
    faceIds?: string[];
}

/**
 * Sample face used for cluster previews.
 */
export interface ClusterSampleFace {
    attachmentId: number;
    thumbnailUrl: string | null;
    bbox: ClusterBoundingBox | null;
}

/**
 * Summary payload for a face cluster card.
 */
export interface ClusterSummary {
    id: string;
    faceCount: number;
    sampleFace: ClusterSampleFace | null;
    suggestion?: {
        rosterId: string;
        displayName: string;
        confidence: number | null;
        reason?: string | null;
    } | null;
    createdAt: string | null;
    updatedAt: string | null;
}

export interface ClusterBoundingBox extends BoundingBox {
    imageWidth?: number | null;
    imageHeight?: number | null;
}

export interface ClusterFaceDetail {
    id: string;
    attachmentId: number;
    databaseId?: number | null;
    bbox: ClusterBoundingBox;
    thumbnailUrl: string | null;
    clusterId?: string | null;
    detectedAt?: string | null;
    resolvedAt?: string | null;
    rosterId?: string | null;
    embeddingId?: string | null;
}
