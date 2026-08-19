import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import {
  normalizeTopUnlabeledRepresentative,
  type TopUnlabeledRepresentativePayload,
} from './normalizeTopUnlabeledRepresentative';
import { parseDataSource, parseProjectionStatus } from './types/dataSource';
import type {
  ClusterListResponse,
  ClusterListParams,
  ClusterSummary,
  TopUnlabeledCluster,
  TopUnlabeledClustersResponse,
} from './types';

type TopUnlabeledClusterPayload = Omit<TopUnlabeledCluster, 'representatives'> & {
  representatives?: TopUnlabeledRepresentativePayload[] | null;
};

interface TopUnlabeledClustersResponsePayload {
  clusters?: TopUnlabeledClusterPayload[] | null;
  limit?: number | null;
  total?: number | null;
  truncated?: boolean | null;
  repair_pending?: boolean | null;
  singleton_count?: number | null;
  has_clusters?: boolean | null;
  data_source?: string | null;
  projection_status?: string | null;
}

interface ClusterListResponsePayload {
  clusters?: ClusterSummary[] | null;
  limit?: number | null;
  total?: number | null;
  truncated?: boolean | null;
}

const requireTopUnlabeledNumber = (value: unknown, fieldName: string): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Top-unlabeled clusters response must include a numeric ${fieldName}.`);
  }

  return value;
};

const requireTopUnlabeledBoolean = (value: unknown, fieldName: string): boolean => {
  if (typeof value !== 'boolean') {
    throw new Error(`Top-unlabeled clusters response must include a boolean ${fieldName}.`);
  }

  return value;
};

const requireClusterListNumber = (value: unknown, fieldName: string): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Cluster list response must include a numeric ${fieldName}.`);
  }

  return value;
};

const requireClusterListBoolean = (value: unknown, fieldName: string): boolean => {
  if (typeof value !== 'boolean') {
    throw new Error(`Cluster list response must include a boolean ${fieldName}.`);
  }

  return value;
};

const normalizeTopUnlabeledCluster = (cluster: TopUnlabeledClusterPayload): TopUnlabeledCluster => ({
  ...cluster,
  representatives: Array.isArray(cluster.representatives)
    ? cluster.representatives.map(normalizeTopUnlabeledRepresentative)
    : [],
});

export const listRecognitionClusters = async (
  params: ClusterListParams = {},
  signal?: AbortSignal,
): Promise<ClusterListResponse> => {
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

  const payload = await fetchRequiredApi<ClusterListResponsePayload>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal,
  });

  if (!Array.isArray(payload.clusters)) {
    throw new Error('Cluster list response must include a clusters array.');
  }

  return {
    clusters: payload.clusters,
    limit: requireClusterListNumber(payload.limit, 'limit'),
    total: requireClusterListNumber(payload.total, 'total'),
    truncated: requireClusterListBoolean(payload.truncated, 'truncated'),
  };
};

export const getRecognitionCluster = async (clusterId: string): Promise<ClusterSummary> => {
  const base = getEndpoint('recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}`;

  return fetchRequiredApi<ClusterSummary>(url, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const fetchTopUnlabeledClusters = async (
  tenantId: string,
  limit: number,
  signal?: AbortSignal,
): Promise<TopUnlabeledClustersResponse> => {
  const base = getEndpoint('recognitionClusters');
  const url = new URL(`${stripTrailingSlash(base)}/top-unlabeled`, window.location.origin);
  url.searchParams.set('tenant_id', tenantId);
  url.searchParams.set('limit', String(limit));

  const payload = await fetchRequiredApi<TopUnlabeledClustersResponsePayload>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal,
  });

  return normalizeTopUnlabeledClustersResponse(payload);
};

export const normalizeTopUnlabeledClustersResponse = (
  payload: TopUnlabeledClustersResponsePayload,
): TopUnlabeledClustersResponse => {
  if (!Array.isArray(payload.clusters)) {
    throw new Error('Top-unlabeled clusters response must include a clusters array.');
  }

  const dataSource = parseDataSource(payload.data_source);
  if (!dataSource) {
    throw new Error('Top-unlabeled clusters response must include a valid data_source.');
  }

  const projectionStatus = parseProjectionStatus(payload.projection_status);
  if (dataSource === 'unavailable' && !projectionStatus) {
    throw new Error('Top-unlabeled clusters response must include a valid projection_status.');
  }

  const singletonCount =
    dataSource === 'backend_proxy' ? undefined : requireTopUnlabeledNumber(payload.singleton_count, 'singleton_count');
  const hasClusters =
    dataSource === 'local_projection' ? requireTopUnlabeledBoolean(payload.has_clusters, 'has_clusters') : undefined;

  return {
    clusters: payload.clusters.map(normalizeTopUnlabeledCluster),
    limit: requireTopUnlabeledNumber(payload.limit, 'limit'),
    total: requireTopUnlabeledNumber(payload.total, 'total'),
    truncated: requireTopUnlabeledBoolean(payload.truncated, 'truncated'),
    repair_pending: payload.repair_pending === true,
    singleton_count: singletonCount,
    has_clusters: hasClusters,
    data_source: dataSource,
    projection_status: projectionStatus ?? undefined,
  };
};
