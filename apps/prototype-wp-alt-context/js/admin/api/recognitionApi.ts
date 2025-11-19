import { fetchApi } from '../utils/http';
import { getEndpoint, getConfig } from './config';

export type AnalyzeRequest = {
  mediaIds: number[];
  sensitivity?: 'standard' | 'high';
  clusterId?: string;
};

export type AnalyzeResponse = {
  job_id: string;
  status: string;
  total_media: number;
};

export type ScanStatus = {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  total_media: number;
  processed_media: number;
  identities_detected: number;
  faces_detected?: number;
  error_message?: string;
  created_at?: string;
  completed_at?: string;
};

export type ClusterRequest = {
  similarity_threshold?: number;
};

export type ClusterResponse = {
  clusters_created: number;
  total_identities_clustered: number;
  total_faces_clustered?: number;
};

type RepresentativeBounds = {
  media_id: number | null;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
};

export type ClusterIdentity = {
  id: string;
  media_id: number;
  similarity: number;
  confidence: number;
  bbox: RepresentativeBounds['bbox'];
  thumbnail_url?: string | null;
};

export type MediaIdentitiesResponse = {
  identities_by_media: Record<string, ClusterIdentity[]>;
};

export type DetectedIdentity = {
  id: string;
  media_id: number;
  cluster_id: string | null;
  cluster_label: string | null;
  is_auto_label: boolean;
  bbox: RepresentativeBounds['bbox'];
  confidence: number;
  similarity: number | null;
  detected_at?: string;
  thumbnail_url?: string | null;
};

export type UpdateClusterLabelRequest = {
  label: string;
};

export type MergeClusterRequest = {
  target_label: string;
};

export type ClusterSummary = {
  id: string;
  label: string;
  identity_count: number;
  face_count: number;
  member_ids: string[];
  representative_identity: RepresentativeBounds;
  sample_identities: ClusterIdentity[];
  representative_face: RepresentativeBounds;
  sample_faces: ClusterIdentity[];
};

export type ClusterListParams = {
  limit?: number;
  offset?: number;
};

export type ReassignClusterIdentityRequest = {
  identityId: string;
  targetClusterId?: string | null;
};

export type ReassignClusterFaceRequest = {
  faceId: string;
  targetClusterId?: string | null;
};

export const updateClusterLabel = async (
  clusterId: string,
  label: string,
): Promise<void> => {
  const base = getEndpoint('workbenchRecognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}`;

  await fetchApi(url, {
    method: 'PATCH',
    body: { label },
    restNonce: getConfig().nonce,
  });
};

export const mergeCluster = async (
  sourceId: string,
  targetLabel: string,
): Promise<void> => {
  const base = getEndpoint('workbenchRecognitionClusters');
  const url = `${stripTrailingSlash(base)}/${sourceId}/merge`;

  await fetchApi(url, {
    method: 'POST',
    body: { target_label: targetLabel },
    restNonce: getConfig().nonce,
  });
};

export const scanFaces = async (request: AnalyzeRequest): Promise<AnalyzeResponse> => {
  const body: Record<string, unknown> = { media_ids: request.mediaIds };
  if (request.sensitivity) {
    body.sensitivity = request.sensitivity;
  }
  if (request.clusterId) {
    body.cluster_id = request.clusterId;
  }

  return fetchApi(getEndpoint('workbenchRecognitionAnalyze', 'workbenchFaceScan', 'recognitionAnalyze'), {
    method: 'POST',
    body,
    restNonce: getConfig().nonce,
  });
};

export const fetchScanStatus = async (jobId: string): Promise<ScanStatus> => {
  const base = getEndpoint('workbenchRecognitionJobs', 'recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  const response = await fetchApi<ScanStatus>(`${base}${separator}${jobId}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
  return {
    ...response,
    faces_detected: response.faces_detected ?? response.identities_detected ?? 0,
    identities_detected: response.identities_detected ?? response.faces_detected ?? 0,
  };
};

export const clusterFaces = async (request: ClusterRequest): Promise<ClusterResponse> => {
  const response = await fetchApi<ClusterResponse>(getEndpoint('workbenchRecognitionCluster', 'workbenchFaceClusters', 'recognitionCluster'), {
    method: 'POST',
    body: { similarity_threshold: request.similarity_threshold ?? 0.6 },
    restNonce: getConfig().nonce,
  });
  return {
    ...response,
    total_faces_clustered: response.total_faces_clustered ?? response.total_identities_clustered ?? 0,
    total_identities_clustered: response.total_identities_clustered ?? response.total_faces_clustered ?? 0,
  };
};

export const listRecognitionClusters = async (params: ClusterListParams = {}): Promise<ClusterSummary[]> => {
  const base = getEndpoint('workbenchRecognitionClusters', 'workbenchFaceClusters', 'recognitionClusters');
  const url = new URL(base, window.location.origin);
  if (params.limit) {
    url.searchParams.set('limit', String(params.limit));
  }
  if (Number.isFinite(params.offset)) {
    url.searchParams.set('offset', String(params.offset));
  }

  const response = await fetchApi<ClusterSummary[]>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
  return response.map(normalizeClusterSummary);
};

export const fetchMediaIdentities = async (mediaIds: number[]): Promise<MediaIdentitiesResponse> => {
  if (mediaIds.length === 0) {
    return { identities_by_media: {} };
  }

  const endpoint = getEndpoint('workbenchRecognitionMediaIdentities');
  const url = new URL(endpoint, window.location.origin);
  mediaIds.forEach((id) => {
    url.searchParams.append('media_ids[]', String(id));
  });

  return fetchApi(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const getRecognitionCluster = async (clusterId: string): Promise<ClusterSummary> => {
  const base = getEndpoint('workbenchRecognitionClusters', 'workbenchFaceClusters', 'recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}`;

  const response = await fetchApi<ClusterSummary>(url, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
  return normalizeClusterSummary(response);
};

function stripTrailingSlash(value: string): string {
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

export const reassignClusterIdentity = async (request: ReassignClusterIdentityRequest): Promise<void> => {
  let base: string;
  try {
    base = getEndpoint(
      'workbenchRecognitionReassignIdentity',
      'workbenchRecognitionClusters',
      'workbenchFaceClusters',
      'recognitionClusters',
    );
  } catch {
    throw new Error('Cluster reassignment endpoint is not configured.');
  }

  const url = `${stripTrailingSlash(base)}/reassign`;
  await fetchApi(url, {
    method: 'POST',
    body: {
      identity_id: request.identityId,
      target_cluster_id: request.targetClusterId ?? null,
    },
    restNonce: getConfig().nonce,
  });
};

export const reassignClusterFace = async (request: ReassignClusterFaceRequest): Promise<void> => {
  return reassignClusterIdentity({ identityId: request.faceId, targetClusterId: request.targetClusterId });
};

function normalizeClusterSummary(summary: ClusterSummary): ClusterSummary {
  const representativeIdentity = summary.representative_identity ?? summary.representative_face ?? {
    media_id: null,
    bbox: { x: 0, y: 0, width: 0, height: 0 },
  };
  const sampleIdentities = summary.sample_identities ?? summary.sample_faces ?? [];

  return {
    ...summary,
    identity_count: summary.identity_count ?? summary.face_count ?? 0,
    face_count: summary.face_count ?? summary.identity_count ?? 0,
    representative_identity: representativeIdentity,
    representative_face: summary.representative_face ?? representativeIdentity,
    sample_identities: sampleIdentities,
    sample_faces: summary.sample_faces ?? sampleIdentities,
  };
}
