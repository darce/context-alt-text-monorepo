import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import { parseDataSource, parseProjectionStatus } from './types/dataSource';
import type {
  ClusterListParams,
  ClusterSummary,
  TopUnlabeledCluster,
  TopUnlabeledClustersResponse,
  TopUnlabeledRepresentative,
} from './types';

type TopUnlabeledRepresentativePayload = Omit<TopUnlabeledRepresentative, 'thumb_url'> & {
  thumb_url?: string | null;
};

type TopUnlabeledClusterPayload = Omit<TopUnlabeledCluster, 'representatives'> & {
  representatives?: TopUnlabeledRepresentativePayload[] | null;
};

interface TopUnlabeledClustersResponsePayload {
  clusters?: TopUnlabeledClusterPayload[] | null;
  singleton_count?: number | null;
  data_source?: string | null;
  projection_status?: string | null;
}

const requireTopUnlabeledNumber = (value: unknown, fieldName: string): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Top-unlabeled clusters response must include a numeric ${fieldName}.`);
  }

  return value;
};

const normalizeOptionalUrl = (value: unknown): string | null => {
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
};

const normalizeTopUnlabeledRepresentative = (
  representative: TopUnlabeledRepresentativePayload,
): TopUnlabeledRepresentative => {
  const normalizedThumb = normalizeOptionalUrl(representative.thumb_url ?? null);
  return {
    ...representative,
    thumb_url: normalizedThumb,
    media_url: normalizeOptionalUrl(representative.media_url ?? null),
    bbox: representative.bbox ?? null,
  };
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

  if (!Array.isArray(payload.clusters)) {
    throw new Error('Top-unlabeled clusters response must include a clusters array.');
  }

  const dataSource = parseDataSource(payload.data_source);
  if (!dataSource) {
    throw new Error('Top-unlabeled clusters response must include a valid data_source.');
  }

  const projectionStatus = parseProjectionStatus(payload.projection_status);
  if (!projectionStatus) {
    throw new Error('Top-unlabeled clusters response must include a valid projection_status.');
  }

  return {
    clusters: payload.clusters.map(normalizeTopUnlabeledCluster),
    singleton_count: requireTopUnlabeledNumber(payload.singleton_count, 'singleton_count'),
    data_source: dataSource,
    projection_status: projectionStatus,
  };
};
