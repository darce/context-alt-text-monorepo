/**
 * Cluster Types and Operations
 */

import type { ClusterIdentity, RepresentativeBounds } from './identity';

export interface ClusterSummary {
  id: string;
  label: string;
  is_auto_label?: boolean;
  identity_count: number;
  member_ids: string[];
  representative_identity: RepresentativeBounds;
  sample_identities: ClusterIdentity[];
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
  representatives: Array<{
    id: string;
    media_id: number;
    thumb_url?: string;
    is_pinned: boolean;
  }>;
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

export interface IdentitySuggestionsResponse {
  matches: ClusterSuggestion[];
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

export interface ReassignClusterFaceRequest {
  faceId: string;
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

import type { DebugMetrics } from './identity';

export interface ClusterRepresentative {
  id: string;
  media_id: number;
  thumb_url?: string;
  is_pinned?: boolean;
  debug_metrics?: DebugMetrics | null;
}

export interface PinRepresentativeRequest {
  tenant_id: string;
  is_pinned: boolean;
}
