/**
 * Identity and Detection Types
 */

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface RepresentativeBounds {
  media_id: number | null;
  bbox: BoundingBox;
}

export interface ClusterIdentity {
  identity_id: string;
  media_id: number;
  similarity: number;
  confidence: number;
  bbox: BoundingBox;
  thumbnail_url?: string | null;
  media_url?: string | null;
}

/**
 * InsightFace debug metrics extracted from extended embeddings.
 * Only populated when include_debug=true query param is passed.
 */
export interface DebugMetrics {
  pose: {
    pitch: number;
    yaw: number;
    roll: number;
  };
  age: number;
  gender: 'female' | 'male';
  det_score: number;
  bbox_area: number;
  landmark_quality: number;
  // Clustering decision info
  clustering_method: string | null;
  clustering_algorithm: string | null;
  similarity_threshold: number | null;
  match_similarity: number | null;
}

export interface DetectedIdentity {
  identity_id: string;
  representative_id?: string | null;
  media_id: number;
  cluster_id: string | null;
  cluster_label: string | null;
  is_auto_label: boolean;
  is_pinned?: boolean;
  bbox: BoundingBox;
  confidence: number;
  similarity: number | null;
  detected_at?: string;
  thumbnail_url?: string | null;
  media_url?: string | null;
  debug_metrics?: DebugMetrics | null;
}

export interface MediaIdentitiesResponse {
  identities_by_media: Record<string, DetectedIdentity[]>;
}
