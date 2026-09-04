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

/**
 * FEBT2-W2-R-01: `signal` is threaded here for the same reason it is on `mergeCluster`,
 * `renameCluster` and `reassignClusterIdentity` — not to bound the wait (utils/http already
 * gives every call `DEFAULT_FETCH_TIMEOUT_MS`), but so a superseded revert can be abandoned
 * before it lands. Without it the caller has no way to disown an in-flight revert, and the
 * write of an undo the operator already moved past still commits (RES-10: a holder whose
 * authority has lapsed must not still be able to write).
 */
export const revertMergeCluster = async (
  request: RevertMergeRequest,
  signal?: AbortSignal,
): Promise<RevertMergeResponse> => {
  const base = getEndpoint('recognitionRevertMerge');
  return fetchRequiredApi<RevertMergeResponse>(base, {
    method: 'POST',
    body: {
      target_cluster_id: request.targetClusterId,
      moved_identity_ids: request.movedIdentityIds,
      source_label: request.sourceLabel ?? null,
    },
    restNonce: getConfig().nonce,
    signal,
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

/**
 * FEBT2-W2-LANE-05: `signal` is threaded for the same reason as on `revertMergeCluster`
 * and `mergeCluster` — not to bound the wait (`utils/http` already applies
 * `DEFAULT_FETCH_TIMEOUT_MS`) but so a superseded split can be disowned before it lands.
 * Split is the heaviest write in this module, so the blast radius of a landed-but-abandoned
 * split is the largest here (RES-10: authority that has lapsed must not still be able to
 * write). It is the trailing optional parameter every sibling mutation already uses, so
 * existing two-argument call sites are unchanged (NAME-04).
 */
export const splitCluster = async (
  clusterId: string,
  request: SplitClusterRequest = {},
  signal?: AbortSignal,
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
      signal,
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
