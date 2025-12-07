/**
 * Scan Operations API
 *
 * API functions for face scanning and job status.
 */

import { fetchApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { AnalyzeRequest, AnalyzeResponse, JobStatusResponse, ClusterRequest, ClusterResponse } from './types';

export const scanFaces = async (request: AnalyzeRequest): Promise<AnalyzeResponse> => {
  const body: Record<string, unknown> = { media_ids: request.mediaIds };
  if (request.sensitivity) {
    body.sensitivity = request.sensitivity;
  }
  if (request.clusterId) {
    body.cluster_id = request.clusterId;
  }

  return fetchApi<AnalyzeResponse>(
    getEndpoint('workbenchRecognitionAnalyze', 'workbenchFaceScan', 'recognitionAnalyze'),
    {
      method: 'POST',
      body,
      restNonce: getConfig().nonce,
    },
  );
};

export const fetchScanStatus = async (jobId: string): Promise<JobStatusResponse> => {
  const base = getEndpoint('workbenchRecognitionJobs', 'recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchApi<JobStatusResponse>(`${base}${separator}${jobId}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const clusterFaces = async (request: ClusterRequest): Promise<ClusterResponse> => {
  const tenantId = getConfig().tenant_id;
  return fetchApi<ClusterResponse>(
    getEndpoint('workbenchRecognitionCluster', 'workbenchFaceClusters', 'recognitionCluster'),
    {
      method: 'POST',
      body: {
        tenant_id: tenantId,
        mode: 'sync',
        similarity_threshold: request.similarity_threshold ?? 0.6,
      },
      restNonce: getConfig().nonce,
    },
  );
};
