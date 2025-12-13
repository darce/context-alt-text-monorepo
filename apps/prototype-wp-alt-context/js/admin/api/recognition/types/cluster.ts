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

export interface ClusterListParams {
  limit?: number;
  offset?: number;
}

export interface ClusterSuggestion {
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
}

export interface ReassignClusterFaceRequest {
  faceId: string;
  targetClusterId?: string | null;
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
