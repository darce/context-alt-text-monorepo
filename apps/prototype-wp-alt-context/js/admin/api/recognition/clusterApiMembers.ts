import { fetchApi, fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { ClusterIdentity } from './types';
import { reassignClusterIdentity } from './clusterApiMutations';

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
  return fetchRequiredApi<ClusterIdentity[]>(url, {
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
