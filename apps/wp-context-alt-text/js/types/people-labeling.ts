/**
 * Face Detection & Recognition Type Definitions - v2
 * Aligns with CONSOLIDATED_FACE_DETECTION_PLAN.md Section 3.4
 *
 * @fileoverview TypeScript types for unified People labeling flow
 */

// ============================================================================
// Core Detection Types (Frontend)
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

/**
 * Raw detection result from MediaPipe/RetinaFace
 */
export interface RawDetection {
    /** Bounding box in normalized coordinates (0-1) */
    boundingBox: BoundingBox;
    /** Detection confidence score (0-1) */
    confidence: number;
    /** Optional keypoints (landmarks) for face alignment */
    keypoints?: Array<{ x: number; y: number }>;
}

/**
 * Frontend face representation with backend suggestions
 */
export interface DetectedFaceFE {
    /** Unique identifier (frontend-generated or backend-provided) */
    faceId: string;
    /** Bounding box coordinates */
    bbox: BoundingBox;
    /** Attachment post ID this face belongs to */
    attachmentId: number;
    /** Detection confidence from browser detector */
    confidence: number;
    /** Cluster ID from backend (groups unknowns) */
    clusterId: string | null;
    /** Roster suggestions from FAISS search */
    suggestions: Suggestion[];
    /** User's draft label (not yet submitted) */
    labelDraft: Label | null;
    /** Confirmed roster ID after user labels */
    confirmedRosterId: string | null;
}

/**
 * Label assigned to a face (mutually exclusive fields)
 */
export interface Label {
    /** ID of existing roster person (XOR with newName) */
    rosterId?: string;
    /** Display name for new person (XOR with rosterId) */
    newName?: string;
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
    observationId?: number;
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
// Component Props Types
// ============================================================================

/**
 * Props for PeopleOverlay component
 */
export interface PeopleOverlayProps {
    /** Detected faces to render */
    faces: DetectedFaceFE[];
    /** Currently selected face index */
    selectedFaceIndex: number | null;
    /** Callback when face chip is clicked */
    onFaceClick: (index: number) => void;
    /** Callback when user submits a label */
    onLabelSubmit: (faceId: string, label: Label) => Promise<void>;
    /** Whether to show confidence scores */
    showConfidence?: boolean;
    /** Image element for positioning overlays */
    imageElement: HTMLImageElement | null;
}

/**
 * Props for PeopleDrawer component
 */
export interface PeopleDrawerProps {
    /** Clustered unknown faces */
    clusters: FaceCluster[];
    /** Suggestion stacks for known persons */
    suggestions: SuggestionStack[];
    /** Callback for bulk confirming a stack */
    onBulkConfirm: (rosterId: string, faceIds: string[]) => Promise<void>;
    /** Callback for reassigning a face */
    onReassign: (faceId: string, label: Label) => Promise<void>;
    /** Whether drawer is collapsed */
    isCollapsed?: boolean;
}

/**
 * Props for PeoplePicker component
 */
export interface PeoplePickerProps {
    /** Current search query */
    searchQuery: string;
    /** Roster search results */
    rosterResults: RosterPerson[];
    /** Callback when user selects a person */
    onSelect: (rosterId: string) => void;
    /** Callback when user creates new person */
    onCreateNew: (displayName: string) => void;
    /** Currently selected roster ID (for corrections) */
    currentRosterId?: string;
    /** Whether picker is open */
    isOpen: boolean;
    /** Callback to close picker */
    onClose: () => void;
}

// ============================================================================
// Domain Types
// ============================================================================

/**
 * Group of faces likely belonging to same person
 */
export interface FaceCluster {
    /** Cluster identifier from backend */
    clusterId: string;
    /** Faces in this cluster */
    faces: DetectedFaceFE[];
    /** Representative face (highest confidence) */
    representativeFace: DetectedFaceFE;
    /** Number of faces in cluster */
    count: number;
}

/**
 * Stack of faces with same roster suggestion
 */
export interface SuggestionStack {
    /** Roster person ID */
    rosterId: string;
    /** Display name of suggested person */
    display: string;
    /** Avatar URL */
    avatarUrl: string | null;
    /** Faces with this suggestion */
    faces: DetectedFaceFE[];
    /** Number of faces in stack */
    count: number;
    /** Average similarity score across stack */
    avgScore: number;
}

/**
 * Roster person (from WordPress taxonomy)
 */
export interface RosterPerson {
    /** Roster ID (term slug or remote ID) */
    id: string;
    /** Display name */
    displayName: string;
    /** Alternative names/aliases */
    aliases: string[];
    /** Avatar image URL */
    avatarUrl: string | null;
    /** Metadata (JSON) */
    meta: Record<string, unknown>;
    /** Creation timestamp */
    createdAt: string;
}

/**
 * Face observation record (database entity)
 */
export interface FaceObservation {
    /** Observation ID */
    id: number;
    /** Attachment post ID */
    attachmentId: number;
    /** Bounding box X coordinate */
    bboxX: number;
    /** Bounding box Y coordinate */
    bboxY: number;
    /** Bounding box width */
    bboxW: number;
    /** Bounding box height */
    bboxH: number;
    /** Cluster group ID (for unknowns) */
    clusterGroupId: string | null;
    /** Suggested roster ID from FAISS */
    suggestedRosterId: string | null;
    /** Suggestion confidence score */
    suggestedScore: number | null;
    /** Confirmed roster ID (user-labeled) */
    confirmedRosterId: string | null;
    /** Label status */
    labelStatus: LabelStatus;
    /** Created timestamp */
    createdAt: string;
    /** Updated timestamp */
    updatedAt: string;
}

/**
 * Label status enum
 */
export enum LabelStatus {
    /** No label or suggestion yet */
    Unlabeled = "unlabeled",
    /** Backend provided suggestion */
    Suggested = "suggested",
    /** User confirmed suggestion */
    Confirmed = "confirmed",
    /** User rejected as not a face */
    Rejected = "rejected",
    /** User corrected suggestion to different person */
    Corrected = "corrected",
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
    identifyFaces: (attachmentId: number, detections: RawDetection[]) => Promise<void>;
    /** Submit label for a face */
    submitLabel: (faceId: string, label: Label) => Promise<void>;
    /** Bulk confirm roster suggestion */
    bulkConfirm: (rosterId: string, faceIds: string[]) => Promise<void>;
    /** Reset state */
    reset: () => void;
}

/**
 * Return type for useFaceDetection hook (already exists in foundation)
 */
export interface UseFaceDetectionReturn {
    /** Detection state */
    state: "idle" | "loading" | "ready" | "detecting" | "error";
    /** Detected faces */
    detections: RawDetection[];
    /** Error if detection failed */
    error: Error | null;
    /** Whether detector is ready */
    isReady: boolean;
    /** Load MediaPipe model */
    loadDetector: () => Promise<void>;
    /** Run detection on image */
    detect: (image: HTMLImageElement) => Promise<RawDetection[]>;
    /** Unload detector */
    unload: () => void;
    /** Reset state */
    reset: () => void;
}

// ============================================================================
// Settings/Config Types
// ============================================================================

/**
 * Detection provider configuration
 */
export interface DetectionConfig {
    /** Provider type */
    provider: "mediapipe" | "retinaface";
    /** Model confidence threshold */
    minConfidence: number;
    /** Maximum faces to detect per image */
    maxFaces: number;
}

/**
 * Recognition settings
 */
export interface RecognitionSettings {
    /** FAISS similarity threshold for suggestions */
    suggestionThreshold: number;
    /** Top-K suggestions to return */
    topK: number;
    /** Clustering threshold for unknowns */
    clusterThreshold: number;
    /** Auto-apply labels above this confidence */
    autoApplyThreshold: number | null;
}
