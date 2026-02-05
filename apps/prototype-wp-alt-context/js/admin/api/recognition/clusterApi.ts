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
  ClusterIdentity,
} from './types';

export const updateClusterLabel = async (clusterId: string, label: string, signal?: AbortSignal): Promise<void> => {
  const url = `${stripTrailingSlash(getEndpoint('recognitionClusters'))}/${clusterId}`;
  await fetchApi(url, {
    method: 'PATCH',
    body: { label },
    restNonce: getConfig().nonce,
    signal,
  });
};

export const mergeCluster = async (
  sourceId: string,
  targetClusterId: string,
  targetLabel?: string,
  signal?: AbortSignal,
): Promise<MergeClusterResponse> => {
  const url = `${stripTrailingSlash(getEndpoint('recognitionClusters'))}/${sourceId}/merge`;
  return fetchApi<MergeClusterResponse>(url, {
    method: 'POST',
    body: { target_cluster_id: targetClusterId, target_label: targetLabel },
    restNonce: getConfig().nonce,
    signal,
  });
};

export const listRecognitionClusters = async (
  params: ClusterListParams = {},
  signal?: AbortSignal,
): Promise<ClusterSummary[]> => {
  const base = getEndpoint('recognitionClusters');
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
  if (params.search) {
    url.searchParams.set('search', params.search);
  }

  return fetchApi<ClusterSummary[]>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal,
  });
};

export const getRecognitionCluster = async (clusterId: string): Promise<ClusterSummary> => {
  const base = getEndpoint('recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}`;

  return fetchApi<ClusterSummary>(url, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const fetchClusterLabels = async (): Promise<string[]> => {
  const base = getEndpoint('recognitionClusterLabels');
  return fetchApi<string[]>(stripTrailingSlash(base), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const reassignClusterIdentity = async (
  request: ReassignClusterIdentityRequest,
  signal?: AbortSignal,
): Promise<void> => {
  const base = getEndpoint('recognitionReassignIdentity');
  const url = stripTrailingSlash(base);
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
    signal,
  });
};

export const reassignClusterFace = (request: ReassignClusterFaceRequest): Promise<void> =>
  reassignClusterIdentity({
    identityId: request.faceId,
    targetClusterId: request.targetClusterId,
    blockFromCluster: request.blockFromCluster,
  });

export const revertMergeCluster = async (request: RevertMergeRequest): Promise<RevertMergeResponse> => {
  const base = getEndpoint('recognitionRevertMerge');
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
  const base = getEndpoint('recognitionClusters');
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
  signal?: AbortSignal,
): Promise<CreateClusterForIdentityResponse> => {
  const base = getEndpoint('recognitionCreateClusterForIdentity');
  const url = stripTrailingSlash(base);

  return fetchApi<CreateClusterForIdentityResponse>(url, {
    method: 'POST',
    body: {
      identity_id: request.identityId,
      label: request.label,
    },
    restNonce: getConfig().nonce,
    signal,
  });
};

export const pinRepresentative = async (
  clusterId: string,
  representativeId: string,
  isPinned: boolean,
): Promise<void> => {
  const base = getEndpoint('recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}/representatives/${representativeId}/pin`;
  await fetchApi(url, {
    method: 'PATCH',
    body: { is_pinned: isPinned },
    restNonce: getConfig().nonce,
  });
};

export const fetchClusterMembers = async (clusterId: string): Promise<ClusterIdentity[]> => {
  const base = getEndpoint('recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}/members`;
  return fetchApi<ClusterIdentity[]>(url, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const removeClusterMember = async (identityId: string, block = true, signal?: AbortSignal): Promise<void> => {
  return reassignClusterIdentity(
    {
      identityId,
      targetClusterId: null,
      blockFromCluster: block,
    },
    signal,
  );
};
