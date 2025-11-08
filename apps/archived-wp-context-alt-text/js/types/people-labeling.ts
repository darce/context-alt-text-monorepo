/**
 * Recognition Type Definitions
 *
 * Shared TypeScript contracts for the remote recognition pipeline.
 */

// ============================================================================
// Core Recognition Types (Frontend)
// ============================================================================

/**
 * Bounding box coordinates for detected faces
 * Normalized to 0-1 range relative to image dimensions
 */
export interface BoundingBox {
    /** X coordinate (0-1 normalized or pixels depending on context) */
    x: number;
    /** Y coordinate (0-1 normalized or pixels) */
    y: number;
    /** Width of bounding box */
    width: number;
    /** Height of bounding box */
    height: number;
}

export interface DetectedFaceFE {
    /** Unique identifier (frontend-generated or backend-provided) */
    faceId: string;
    /** Bounding box coordinates */
    bbox: BoundingBox;
    /** Attachment post ID this face belongs to */
    attachmentId: number;
    /** Confidence score supplied by recognition service */
    confidence: number;
    /** Cluster ID from backend (groups unknowns) */
    clusterId: string | null;
    /** Roster suggestions from FAISS search */
    suggestions: Suggestion[];
    /** User's draft label (not yet submitted) */
    labelDraft: Label | null;
    /** Confirmed roster ID after user labels */
    confirmedRosterId: string | null;
    /** Observation identifier when record already exists */
    observationId?: string | number | null;
}

/**
 * Label assigned to a face (mutually exclusive fields)
 */
export interface Label {
    /** ID of existing roster person (XOR with newName) */
    rosterId?: string;
    /** Display name for new person (XOR with rosterId) */
    newName?: string;
    /** Display name (used when rosterId is provided to show correct label in UI) */
    displayName?: string;
}

/**
 * Suggestion from backend FAISS search
 */
export interface Suggestion {
    /** Roster person ID */
    rosterId: string;
    /** Display name of suggested person */
    display: string;
    /** Similarity score (0-1, higher is better) */
    score: number;
    /** Optional avatar URL for UI */
    avatarUrl?: string;
}

// ============================================================================
// API Request/Response Types
// ============================================================================

/**
 * Face in request payload (detection or labeling)
 */
export interface DetectedFaceRequest {
    /** Bounding box coordinates */
    bbox: BoundingBox;
    /** Frontend temporary ID for reconciliation */
    faceId?: string;
    /** Existing observation identifier (if already tracked) */
    observationId?: string | number;
    /** Label if user has named this face */
    label?: Label;
}

/**
 * Face in response payload (with suggestions)
 */
export interface DetectedFaceResponse {
    /** Reconciliation ID (echoed or generated) */
    faceId: string;
    /** Cluster ID for grouping unknowns */
    clusterId?: string;
    /** Ordered suggestions from FAISS */
    suggestions: Suggestion[];
    /** Database observation ID (only if label provided) */
    observationId?: number | string;
    /** Roster ID (returned when label is persisted) */
    rosterId?: string;
    /** Sync status for FAISS embedding */
    syncStatus?: string;
    /** Sync error message if sync failed */
    syncError?: string;
}

/**
 * POST /wp-json/cat/v1/recognition/identify request
 */
export interface IdentifyRequest {
    /** WordPress attachment post ID */
    attachmentId: number;
    /** Array of detected faces (with optional labels) */
    faces: DetectedFaceRequest[];
    /** Coordinate system: "normalized" (0-1) or "pixels" */
    imageCoordinateSystem?: "normalized" | "pixels";
}

/**
 * POST /wp-json/cat/v1/recognition/identify response
 */
export interface IdentifyResponse {
    /** Array of faces with suggestions and cluster IDs */
    faces: DetectedFaceResponse[];
    /** Error message if request failed */
    error?: string;
}

// ============================================================================
// Domain Types
// ============================================================================

/**
 * Roster person (from WordPress taxonomy)
 */
/**
 * Roster person entry
 *
 * Aligned with recognition service RosterEntry schema:
 * - uniqueId: Primary identifier (UUID from recognition service)
 * - name: Internal canonical name
 * - displayName: User-facing display name
 */
export interface RosterPerson {
    /** Unique identifier (UUID from recognition service) */
    uniqueId: string;
    /** Internal canonical name */
    name: string;
    /** User-facing display name */
    displayName: string;
    /** Sync status with recognition service */
    status: "LOCAL" | "SYNCED" | "CONFLICT";
    /** Avatar image URL */
    avatarUrl: string | null;
    /** Avatar attachment ID */
    avatarId: number | null;
    /** Metadata (JSON) */
    metadata: Record<string, unknown>;
    /** Number of reference images */
    referenceImageCount: number;
    /** Last update timestamp (ISO 8601) */
    updatedAt: string | null;
}

// ============================================================================
// Hook Return Types
// ============================================================================

/**
 * Return type for usePeopleSuggestions hook
 */
export interface UsePeopleSuggestionsReturn {
    /** Current face detections */
    faces: DetectedFaceFE[];
    /** Whether identify request is in flight */
    isLoading: boolean;
    /** Error from last identify request */
    error: Error | null;
    /** Submit faces for identification */
    identifyFaces: (attachmentId: number, faces: DetectedFaceRequest[]) => Promise<void>;
    /** Hydrate hook with pre-fetched faces */
    hydrateFaces: (attachmentId: number, faces: DetectedFaceFE[]) => void;
    /** Submit label for a face */
    submitLabel: (faceId: string, label: Label) => Promise<void>;
    /** Bulk confirm roster suggestion */
    bulkConfirm: (rosterId: string, faceIds: string[]) => Promise<void>;
    /** Reset state */
    reset: () => void;
}
