import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { ClusterListParams, ClusterSummary, TopUnlabeledCluster } from './types';

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

  return fetchRequiredApi<ClusterSummary[]>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal,
  });
};

export const getRecognitionCluster = async (clusterId: string): Promise<ClusterSummary> => {
  const base = getEndpoint('recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}`;

  return fetchRequiredApi<ClusterSummary>(url, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const fetchClusterLabels = async (): Promise<string[]> => {
  const base = getEndpoint('recognitionClusterLabels');
  return fetchRequiredApi<string[]>(stripTrailingSlash(base), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const fetchTopUnlabeledClusters = async (
  tenantId: string,
  limit: number,
  signal?: AbortSignal,
): Promise<TopUnlabeledCluster[]> => {
  const base = getEndpoint('recognitionClusters');
  const url = new URL(`${stripTrailingSlash(base)}/top-unlabeled`, window.location.origin);
  url.searchParams.set('tenant_id', tenantId);
  url.searchParams.set('limit', String(limit));

  return fetchRequiredApi<TopUnlabeledCluster[]>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal,
  });
};
