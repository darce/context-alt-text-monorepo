import { idPathSegment } from '../../utils/pathSegment';
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
  ClusterPhotoListParams,
  ClusterPhotoListResponse,
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
  clusters?: ClusterPhotoListResponse['clusters'] | null;
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

/** Explicit opt-in overload; the legacy overload and ReturnType remain unchanged. */
export function listRecognitionClusters(
  params: ClusterPhotoListParams & { min_photos: number },
  signal?: AbortSignal,
): Promise<ClusterPhotoListResponse>;
export function listRecognitionClusters(
  params?: ClusterListParams & { min_photos?: never },
  signal?: AbortSignal,
): Promise<ClusterListResponse>;
export function listRecognitionClusters(
  params: ClusterPhotoListParams = {},
  signal?: AbortSignal,
): Promise<ClusterPhotoListResponse> {
  return listRecognitionClusterPage(params, signal);
}

/** Use this contract when a minimum can be selected or cleared at runtime. */
export const listRecognitionClusterPage = async (
  params: ClusterPhotoListParams = {},
  signal?: AbortSignal,
): Promise<ClusterPhotoListResponse> => {
  const minimum = params.min_photos;
  const filtered = minimum !== undefined;
  if (minimum !== undefined && (!Number.isInteger(minimum) || minimum < 1 || minimum > 2147483647)) {
    throw new Error('min_photos must be an integer between 1 and 2147483647.');
  }
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
  if (filtered) {
    url.searchParams.set('min_photos', String(params.min_photos));
  }

  const payload = await fetchRequiredApi<ClusterListResponsePayload>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal,
  });

  if (!Array.isArray(payload.clusters)) {
    throw new Error('Cluster list response must include a clusters array.');
  }
  for (const cluster of payload.clusters) {
    const count = cluster.photo_count;
    if (count !== undefined && count !== null && (!Number.isInteger(count) || count < 0)) {
      throw new Error('Cluster photo_count must be a nonnegative integer or null.');
    }
  }

  return {
    clusters: payload.clusters,
    limit: requireClusterListNumber(payload.limit, 'limit'),
    total: filtered && payload.total === null ? null : requireClusterListNumber(payload.total, 'total'),
    truncated: requireClusterListBoolean(payload.truncated, 'truncated'),
  };
};

export const getRecognitionCluster = async (clusterId: string): Promise<ClusterSummary> => {
  const base = getEndpoint('recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${idPathSegment(clusterId)}`;

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
