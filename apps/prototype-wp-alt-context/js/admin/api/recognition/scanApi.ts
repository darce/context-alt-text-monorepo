/**
 * Scan Operations API
 *
 * API functions for face scanning and job status.
 */

import { fetchApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { AnalyzeRequest, AnalyzeResponse, JobStatusResponse, ClusterResponse } from './types';

const MAX_MEDIA_IDS_PER_ANALYZE_REQUEST = 300;

const chunkMediaIds = (mediaIds: number[], size: number): number[][] => {
  if (size <= 0) {
    return [mediaIds];
  }

  const batches: number[][] = [];
  for (let index = 0; index < mediaIds.length; index += size) {
    batches.push(mediaIds.slice(index, index + size));
  }
  return batches;
};

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

export const scanFacesBatched = async (request: AnalyzeRequest): Promise<AnalyzeResponse[]> => {
  const batches = chunkMediaIds(request.mediaIds, MAX_MEDIA_IDS_PER_ANALYZE_REQUEST);
  const results: AnalyzeResponse[] = [];
  for (const batch of batches) {
    results.push(await scanFaces({ ...request, mediaIds: batch }));
  }
  return results;
};

export const fetchScanStatus = async (jobId: string): Promise<JobStatusResponse> => {
  const base = getEndpoint('workbenchRecognitionJobs', 'recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchApi<JobStatusResponse>(`${base}${separator}${jobId}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const clusterFaces = async (): Promise<ClusterResponse> => {
  const tenantId = getConfig().tenant_id;
  return fetchApi<ClusterResponse>(
    getEndpoint('workbenchRecognitionCluster', 'workbenchFaceClusters', 'recognitionCluster'),
    {
      method: 'POST',
      body: {
        tenant_id: tenantId,
        mode: 'sync',
      },
      restNonce: getConfig().nonce,
    },
  );
};
