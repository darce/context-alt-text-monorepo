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
 * A persisted unknown face awaiting user confirmation.
 */
export interface UnknownFace {
    /** Database identifier for the stored face record */
    id: string;
    /** WordPress attachment the face was detected in */
    attachmentId: number;
    /** Cropped bounding box expressed in pixels */
    bbox: BoundingBox;
    /** Embedding identifier (stored locally or in the recognition service) */
    embeddingId: string | null;
    /** Cluster identifier assigned by the clustering pipeline */
    clusterId: string | null;
    /** Timestamp (ISO 8601) when the face was detected */
    detectedAt: string;
    /** Optional roster person this face was resolved to */
    rosterId?: string | null;
    /** Timestamp when the face was resolved (ISO 8601) */
    resolvedAt?: string | null;
}

/**
 * Aggregated grouping of visually similar faces.
 */
export interface FaceCluster {
    /** Unique cluster identifier */
    id: string;
    /** Ordered list of face record identifiers belonging to the cluster */
    faceIds: string[];
    /** Representative face identifier used for thumbnails */
    sampleFaceId: string;
    /** Optional roster suggestion associated with the cluster */
    suggestedRosterId?: string | null;
    /** Confidence score for the suggestion (0-1) */
    confidence?: number | null;
    /** Timestamp when the cluster was created */
    createdAt: string;
    /** Timestamp of the most recent update */
    updatedAt: string;
}

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
