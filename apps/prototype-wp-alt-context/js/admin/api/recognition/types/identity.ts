/**
 * Identity and Detection Types
 */

import type { DataSource } from './dataSource';

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
  similarity: number | null;
  confidence: number | null;
  clustering_pending?: boolean;
  bbox: BoundingBox | null;
  thumb_url?: string | null;
  /** Durable WP attachment URL used to crop after scan-time blobs expire. */
  attachment_url?: string | null;
  media_url?: string | null;
  cluster_id?: string | null;
  cluster_label?: string | null;
  is_auto_label?: boolean;
  is_pinned?: boolean;
  detected_at?: string | null;
  representative_id?: string | null;
  debug_metrics?: DebugMetrics | null;
}

/**
 * Debug metrics from recognition include_debug responses.
 * Age/gender removed (FIR-2 S4); pose retained for quality/clustering UI.
 * Only populated when include_debug=true query param is passed.
 */
export interface DebugMetrics {
  pose: {
    pitch: number;
    yaw: number;
    roll: number;
  };
  det_score: number;
  bbox_area: number;
  landmark_quality: number;
  // Clustering decision info
  clustering_method: string | null;
  clustering_algorithm: string | null;
  similarity_threshold: number | null;
  match_similarity: number | null;
  representative_count?: number;
  pose_buckets?: {
    filled: number;
    total: number;
    current_bucket?: [number, number];
  };
}

export interface DetectedIdentity {
  identity_id: string;
  representative_id?: string | null;
  media_id: number;
  cluster_id: string | null;
  cluster_label: string | null;
  is_auto_label: boolean;
  is_pinned?: boolean;
  /** True if clustering job hasn't processed this identity yet */
  clustering_pending?: boolean;
  bbox: BoundingBox;
  confidence: number;
  similarity: number | null;
  detected_at?: string;
  thumb_url?: string | null;
  /** Durable WP attachment URL used to crop after scan-time blobs expire. */
  attachment_url?: string | null;
  media_url?: string | null;
  debug_metrics?: DebugMetrics | null;
}

export interface MediaIdentitiesResponse {
  identities_by_media: Record<string, DetectedIdentity[]>;
  data_source?: DataSource;
}
