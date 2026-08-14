/**
 * Cluster Types and Operations
 */

import type { DataSource, ProjectionStatus } from './dataSource';
import type { BoundingBox, ClusterIdentity, RepresentativeBounds } from './identity';

export interface ClusterSummary {
  id: string;
  label: string | null;
  is_auto_label?: boolean;
  identity_count: number;
  member_ids: string[];
  representative_identity: RepresentativeBounds;
  sample_identities: ClusterIdentity[];
  confidence_score?: number;
  created_at?: string;
  /** Bound person from wp_acx_clusters.person_id → persons.person_uuid. Null when unresolved. */
  person_uuid?: string | null;
}

export interface ClusterListResponse {
  clusters: ClusterSummary[];
  limit: number;
  total: number;
  truncated: boolean;
}

export interface ClusterMembersResponse {
  members: ClusterIdentity[];
  limit: number;
  total: number;
  truncated: boolean;
}

export interface ClusterLabelsResponse {
  labels: string[];
  limit: number;
  total: number;
  truncated: boolean;
}

export interface TopUnlabeledRepresentative {
  id: string;
  /** Normalized from wire `string | null`; null must not coerce to 0. */
  media_id: number | null;
  thumb_url?: string | null;
  media_url?: string | null;
  bbox?: BoundingBox | null;
  /** Internal pin flag; wire name is `is_user_selected`. */
  is_pinned: boolean;
}

/**
 * Top unlabeled cluster response from /clusters/top-unlabeled endpoint.
 * Includes representatives with media IDs for thumbnail display.
 */
export interface TopUnlabeledCluster {
  id: string;
  tenant_id: string;
  label: string | null;
  is_labeled: boolean;
  is_auto_label: boolean;
  identity_count: number;
  user_confirmed: boolean;
  suggested_label?: string | null;
  suggested_label_source?: 'identity' | 'roster' | 'similar_cluster' | 'none' | null;
  suggested_label_confidence?: number | null;
  suggested_target_cluster_id?: string | null;
  representatives: TopUnlabeledRepresentative[];
}

export interface TopUnlabeledClustersResponse {
  clusters: TopUnlabeledCluster[];
  limit: number;
  total: number;
  truncated: boolean;
  singleton_count?: number;
  has_clusters?: boolean;
  data_source: DataSource;
  projection_status?: ProjectionStatus;
}

export interface ClusterListParams {
  limit?: number;
  offset?: number;
  labeled_only?: boolean;
  search?: string;
}

export interface ClusterSuggestion {
  suggestion_id?: string;
  cluster_id: string;
  label: string;
  similarity: number;
  identity_count: number;
}

/**
 * Batch identity-suggestions envelope keyed by identity id (UXP-2 Slice 3b).
 *
 * Matches are grouped per requested identity, ranked server-side, and bounded to `top_k`
 * rows per identity. Requested identities with no eligible suggestion are
 * omitted from the mapping (empty-match handling is the caller's).
 */
export interface IdentityBatchSuggestionsResponse {
  matches: Record<string, ClusterSuggestion[]>;
}

// Cluster operation types

export interface UpdateClusterLabelRequest {
  label: string;
}

export interface MergeClusterRequest {
  target_cluster_id: string;
  target_label?: string;
}

export interface MergeClusterResponse {
  source_id: string;
  source_label: string | null;
  target_id: string;
  target_label: string | null;
  identities_moved: number;
  moved_identity_ids: string[];
  target_identity_count: number;
}

export interface ReassignClusterIdentityRequest {
  identityId: string;
  targetClusterId?: string | null;
  blockFromCluster?: boolean;
}

export interface RevertMergeRequest {
  targetClusterId: string;
  movedIdentityIds: string[];
  sourceLabel?: string | null;
}

export interface RevertMergeResponse {
  restored_cluster_id: string;
  restored_label: string | null;
  restored_identity_count: number;
  target_cluster_id: string;
  target_identity_count: number;
  synced?: boolean;
  status?: 'pending' | 'acknowledged';
}

export interface SplitClusterResponse {
  /** IDs of newly created clusters */
  new_cluster_ids: string[];
  /** Number of identities moved to each new cluster */
  moved_counts: number[];
  /** @deprecated Use new_cluster_ids[0] - Legacy field for backward compatibility */
  new_cluster_id: string | null;
  /** @deprecated Use moved_counts[0] - Legacy field for backward compatibility */
  moved_count: number;
}

export interface AsyncSplitClusterResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface SplitClusterRequest {
  nClusters?: number;
  anchorIdentityId?: string;
  splitMode?: 'auto' | 'forced';
  mode?: 'sync' | 'async';
}

export interface CreateClusterForIdentityRequest {
  identityId: string;
  label: string;
}

export interface CreateClusterForIdentityResponse {
  cluster_id: string;
  label: string;
  identity_id: string;
  message: string;
}
