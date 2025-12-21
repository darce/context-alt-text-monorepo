/**
 * Cluster Operations API
 *
 * API functions for cluster management: update, merge, split, revert.
 */

import { fetchApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type {
  ClusterSummary,
  ClusterListParams,
  MergeClusterResponse,
  ReassignClusterIdentityRequest,
  ReassignClusterFaceRequest,
  RevertMergeRequest,
  RevertMergeResponse,
  SplitClusterRequest,
  SplitClusterResponse,
  AsyncSplitClusterResponse,
  CreateClusterForIdentityRequest,
  CreateClusterForIdentityResponse,
} from './types';

export const updateClusterLabel = async (clusterId: string, label: string): Promise<void> => {
  const url = `${stripTrailingSlash(getEndpoint('workbenchRecognitionClusters'))}/${clusterId}`;
  await fetchApi(url, {
    method: 'PATCH',
    body: { label },
    restNonce: getConfig().nonce,
  });
};

export const mergeCluster = async (
  sourceId: string,
  targetClusterId: string,
  targetLabel?: string,
): Promise<MergeClusterResponse> => {
  const url = `${stripTrailingSlash(getEndpoint('workbenchRecognitionClusters'))}/${sourceId}/merge`;
  return fetchApi<MergeClusterResponse>(url, {
    method: 'POST',
    body: { target_cluster_id: targetClusterId, target_label: targetLabel },
    restNonce: getConfig().nonce,
  });
};

export const listRecognitionClusters = async (params: ClusterListParams = {}): Promise<ClusterSummary[]> => {
  const base = getEndpoint('workbenchRecognitionClusters', 'workbenchFaceClusters', 'recognitionClusters');
  const url = new URL(base, window.location.origin);
  if (params.limit) {
    url.searchParams.set('limit', String(params.limit));
  }
  if (Number.isFinite(params.offset)) {
    url.searchParams.set('offset', String(params.offset));
  }
  if (params.labeled_only) {
    url.searchParams.set('labeled_only', 'true');
  }

  return fetchApi<ClusterSummary[]>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const getRecognitionCluster = async (clusterId: string): Promise<ClusterSummary> => {
  const base = getEndpoint('workbenchRecognitionClusters', 'workbenchFaceClusters', 'recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}`;

  return fetchApi<ClusterSummary>(url, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const fetchClusterLabels = async (): Promise<string[]> => {
  const base = getEndpoint('workbenchRecognitionClusters', 'workbenchFaceClusters', 'recognitionClusters');
  return fetchApi<string[]>(`${stripTrailingSlash(base)}/labels`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const reassignClusterIdentity = async (request: ReassignClusterIdentityRequest): Promise<void> => {
  let base: string;
  let needsReassignSuffix = true;

  try {
    // Try the dedicated reassign endpoint first (already includes /reassign)
    base = getEndpoint('workbenchRecognitionReassignIdentity');
    needsReassignSuffix = false;
  } catch {
    // Fallback to clusters endpoint (needs /reassign suffix)
    try {
      base = getEndpoint('workbenchRecognitionClusters', 'workbenchFaceClusters', 'recognitionClusters');
    } catch {
      throw new Error('Cluster reassignment endpoint is not configured.');
    }
  }

  const url = needsReassignSuffix ? `${stripTrailingSlash(base)}/reassign` : stripTrailingSlash(base);
  const body: Record<string, unknown> = {
    identity_id: request.identityId,
    target_cluster_id: request.targetClusterId ?? null,
  };
  if (typeof request.blockFromCluster === 'boolean') {
    body.block_from_cluster = request.blockFromCluster;
  }
  await fetchApi(url, {
    method: 'POST',
    body,
    restNonce: getConfig().nonce,
  });
};

export const reassignClusterFace = (request: ReassignClusterFaceRequest): Promise<void> =>
  reassignClusterIdentity({
    identityId: request.faceId,
    targetClusterId: request.targetClusterId,
    blockFromCluster: request.blockFromCluster,
  });

export const revertMergeCluster = async (request: RevertMergeRequest): Promise<RevertMergeResponse> => {
  const base = getEndpoint('workbenchRecognitionRevertMerge', 'recognitionRevertMerge');
  return fetchApi<RevertMergeResponse>(base, {
    method: 'POST',
    body: {
      target_cluster_id: request.targetClusterId,
      moved_identity_ids: request.movedIdentityIds,
      source_label: request.sourceLabel ?? null,
    },
    restNonce: getConfig().nonce,
  });
};

/**
 * Split a cluster using hierarchical clustering.
 * @param clusterId - The cluster to split
 * @param request - Split controls (cluster count, anchor identity)
 */
export const splitCluster = async (
  clusterId: string,
  request: SplitClusterRequest = {},
): Promise<SplitClusterResponse | AsyncSplitClusterResponse> => {
  const base = getEndpoint('workbenchRecognitionClusters', 'workbenchFaceClusters', 'recognitionClusters');
  const { nClusters = 0, anchorIdentityId, splitMode, mode } = request;
  const body: Record<string, unknown> = {
    tenant_id: getConfig().tenant_id,
    n_clusters: nClusters,
  };
  if (anchorIdentityId) {
    body.anchor_identity_id = anchorIdentityId;
  }
  if (splitMode) {
    body.split_mode = splitMode;
  }
  if (mode) {
    body.mode = mode;
  }
  return fetchApi<SplitClusterResponse | AsyncSplitClusterResponse>(`${stripTrailingSlash(base)}/${clusterId}/split`, {
    method: 'POST',
    body,
    restNonce: getConfig().nonce,
  });
};

export const createClusterForIdentity = async (
  request: CreateClusterForIdentityRequest,
): Promise<CreateClusterForIdentityResponse> => {
  const base = getEndpoint(
    'workbenchRecognitionCreateClusterForIdentity',
    'workbenchRecognitionClusters',
    'workbenchFaceClusters',
    'recognitionClusters',
  );
  // If we got the specific endpoint, use it directly; otherwise append path
  const url = base.includes('create-for-identity') ? base : `${stripTrailingSlash(base)}/create-for-identity`;

  return fetchApi<CreateClusterForIdentityResponse>(url, {
    method: 'POST',
    body: {
      identity_id: request.identityId,
      label: request.label,
    },
    restNonce: getConfig().nonce,
  });
};
