import { fetchApi, fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import { normalizeMergeClusterResponse } from './clusterApiResponseMappers';
import type {
  AsyncSplitClusterResponse,
  CreateClusterForIdentityRequest,
  CreateClusterForIdentityResponse,
  MergeClusterResponse,
  ReassignClusterIdentityRequest,
  RevertMergeRequest,
  RevertMergeResponse,
  SplitClusterRequest,
  SplitClusterResponse,
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
  const response = await fetchRequiredApi<unknown>(url, {
    method: 'POST',
    body: { target_cluster_id: targetClusterId, target_label: targetLabel },
    restNonce: getConfig().nonce,
    signal,
  });
  return normalizeMergeClusterResponse(sourceId, targetLabel, response);
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

export const revertMergeCluster = async (request: RevertMergeRequest): Promise<RevertMergeResponse> => {
  const base = getEndpoint('recognitionRevertMerge');
  return fetchRequiredApi<RevertMergeResponse>(base, {
    method: 'POST',
    body: {
      target_cluster_id: request.targetClusterId,
      moved_identity_ids: request.movedIdentityIds,
      source_label: request.sourceLabel ?? null,
    },
    restNonce: getConfig().nonce,
  });
};

export const pinRepresentative = async (
  clusterId: string,
  representativeId: string,
  isPinned = true,
  signal?: AbortSignal,
): Promise<void> => {
  const base = getEndpoint('recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}/representatives/${representativeId}/pin`;
  await fetchApi(url, {
    method: 'PATCH',
    body: { is_pinned: isPinned },
    restNonce: getConfig().nonce,
    signal,
  });
};

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
  return fetchRequiredApi<SplitClusterResponse | AsyncSplitClusterResponse>(
    `${stripTrailingSlash(base)}/${clusterId}/split`,
    {
      method: 'POST',
      body,
      restNonce: getConfig().nonce,
    },
  );
};

export const createClusterForIdentity = async (
  request: CreateClusterForIdentityRequest,
  signal?: AbortSignal,
): Promise<CreateClusterForIdentityResponse> => {
  const base = getEndpoint('recognitionCreateClusterForIdentity');
  const url = stripTrailingSlash(base);
  const body: Record<string, unknown> = {
    identity_id: request.identityId,
    label: request.label,
  };
  if (typeof request.rosterEntryId === 'number') {
    body.roster_entry_id = request.rosterEntryId;
  }
  return fetchRequiredApi<CreateClusterForIdentityResponse>(url, {
    method: 'POST',
    body,
    restNonce: getConfig().nonce,
    signal,
  });
};

export const dismissCluster = async (clusterId: string, signal?: AbortSignal): Promise<void> => {
  const base = getEndpoint('recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}/dismiss`;
  await fetchApi(url, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal,
  });
};
