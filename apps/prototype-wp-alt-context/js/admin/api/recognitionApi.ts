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
  faces_detected: number;
  error_message?: string;
  created_at?: string;
  completed_at?: string;
};

export type ClusterRequest = {
  similarity_threshold?: number;
};

export type ClusterResponse = {
  clusters_created: number;
  total_faces_clustered: number;
};

export type ClusterFace = {
  id: string;
  media_id: number;
  similarity: number;
  confidence: number;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
};

export type ClusterSummary = {
  id: string;
  label: string;
  face_count: number;
  member_ids: string[];
  representative_face: {
    media_id: number | null;
    bbox: {
      x: number;
      y: number;
      width: number;
      height: number;
    };
  };
  sample_faces: ClusterFace[];
};

export type ClusterListParams = {
  limit?: number;
  offset?: number;
};

export type ReassignClusterFaceRequest = {
  faceId: string;
  targetClusterId?: string | null;
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

  return fetchApi(`${base}${separator}${jobId}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const clusterFaces = async (request: ClusterRequest): Promise<ClusterResponse> => {
  return fetchApi(getEndpoint('workbenchRecognitionCluster', 'workbenchFaceClusters', 'recognitionCluster'), {
    method: 'POST',
    body: { similarity_threshold: request.similarity_threshold ?? 0.6 },
    restNonce: getConfig().nonce,
  });
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

  return fetchApi(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const getRecognitionCluster = async (clusterId: string): Promise<ClusterSummary> => {
  const base = getEndpoint('workbenchRecognitionClusters', 'workbenchFaceClusters', 'recognitionClusters');
  const url = `${stripTrailingSlash(base)}/${clusterId}`;

  return fetchApi(url, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

function stripTrailingSlash(value: string): string {
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

export const reassignClusterFace = async (request: ReassignClusterFaceRequest): Promise<void> => {
  let base: string;
  try {
    base = getEndpoint('workbenchRecognitionClusters', 'workbenchFaceClusters', 'recognitionClusters');
  } catch {
    throw new Error('Cluster reassignment endpoint is not configured.');
  }

  const url = `${stripTrailingSlash(base)}/reassign`;
  await fetchApi(url, {
    method: 'POST',
    body: {
      face_id: request.faceId,
      target_cluster_id: request.targetClusterId ?? null,
    },
    restNonce: getConfig().nonce,
  });
};
