import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { ClusterIdentity } from './types';
import { reassignClusterIdentity } from './clusterApiMutations';

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
