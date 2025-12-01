/**
 * Scan Operations API
 *
 * API functions for face scanning and job status.
 */

import { fetchApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { AnalyzeRequest, AnalyzeResponse, ScanStatus, ClusterRequest, ClusterResponse } from './types';

export const scanFaces = async (request: AnalyzeRequest): Promise<AnalyzeResponse> => {
  const body: Record<string, unknown> = { media_ids: request.mediaIds };
  if (request.sensitivity) {
    body.sensitivity = request.sensitivity;
  }
  if (request.clusterId) {
    body.cluster_id = request.clusterId;
  }

  const response = await fetchApi<AnalyzeResponse>(
    getEndpoint('workbenchRecognitionAnalyze', 'workbenchFaceScan', 'recognitionAnalyze'),
    {
      method: 'POST',
      body,
      restNonce: getConfig().nonce,
    },
  );

  // Normalize job_id for backward compatibility with multi-job responses
  const normalizedJobId = response.job_id ?? response.job_ids?.[0] ?? null;
  return { ...response, job_id: normalizedJobId };
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
  const response = await fetchApi<ClusterResponse>(
    getEndpoint('workbenchRecognitionCluster', 'workbenchFaceClusters', 'recognitionCluster'),
    {
      method: 'POST',
      body: { similarity_threshold: request.similarity_threshold ?? 0.6 },
      restNonce: getConfig().nonce,
    },
  );
  return {
    ...response,
    total_faces_clustered: response.total_faces_clustered ?? response.total_identities_clustered ?? 0,
    total_identities_clustered: response.total_identities_clustered ?? response.total_faces_clustered ?? 0,
  };
};
