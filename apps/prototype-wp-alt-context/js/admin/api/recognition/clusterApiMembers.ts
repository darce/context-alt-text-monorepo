import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { ClusterIdentity, ClusterMembersResponse } from './types';
import { reassignClusterIdentity } from './clusterApiMutations';

interface ClusterMembersResponsePayload {
  members?: ClusterIdentity[] | null;
  limit?: number | null;
  total?: number | null;
  truncated?: boolean | null;
}

const requireClusterMembersNumber = (value: unknown, fieldName: string): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Cluster members response must include a numeric ${fieldName}.`);
  }

  return value;
};

const requireClusterMembersBoolean = (value: unknown, fieldName: string): boolean => {
  if (typeof value !== 'boolean') {
    throw new Error(`Cluster members response must include a boolean ${fieldName}.`);
  }

  return value;
};

export interface FetchClusterMembersParams {
  limit?: number;
  offset?: number;
}

export const fetchClusterMembers = async (
  clusterId: string,
  params: FetchClusterMembersParams = {},
): Promise<ClusterMembersResponse> => {
  const base = getEndpoint('recognitionClusters');
  const url = new URL(`${stripTrailingSlash(base)}/${clusterId}/members`, window.location.origin);
  if (params.limit !== undefined && Number.isFinite(params.limit)) {
    url.searchParams.set('limit', String(params.limit));
  }
  if (params.offset !== undefined && Number.isFinite(params.offset)) {
    url.searchParams.set('offset', String(params.offset));
  }

  const payload = await fetchRequiredApi<ClusterMembersResponsePayload>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });

  if (!Array.isArray(payload.members)) {
    throw new Error('Cluster members response must include a members array.');
  }

  return {
    members: payload.members,
    limit: requireClusterMembersNumber(payload.limit, 'limit'),
    total: requireClusterMembersNumber(payload.total, 'total'),
    truncated: requireClusterMembersBoolean(payload.truncated, 'truncated'),
  };
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
