/**
 * Scan Operations API
 *
 * API functions for face scanning and job status.
 */

import { fetchRequiredApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { AnalyzeRequest, AnalyzeResponse, JobStatusResponse, ClusterResponse } from './types';

const getMaxMediaPerBatch = (): number => getConfig().maxMediaPerBatch;

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

  return fetchRequiredApi<AnalyzeResponse>(getEndpoint('recognitionAnalyze'), {
    method: 'POST',
    body,
    restNonce: getConfig().nonce,
  });
};

export const scanFacesBatched = async (request: AnalyzeRequest): Promise<AnalyzeResponse[]> => {
  const maxMediaPerBatch = getMaxMediaPerBatch();
  if (request.mediaIds.length <= maxMediaPerBatch) {
    const result = await scanFaces(request);
    return [result];
  }

  const batches = chunkMediaIds(request.mediaIds, maxMediaPerBatch);
  const results: AnalyzeResponse[] = [];
  for (const batch of batches) {
    results.push(await scanFaces({ ...request, mediaIds: batch }));
  }
  return results;
};

export const fetchScanStatus = async (jobId: string): Promise<JobStatusResponse> => {
  const base = getEndpoint('recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchRequiredApi<JobStatusResponse>(`${base}${separator}${jobId}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const cancelScanJob = async (jobId: string): Promise<JobStatusResponse> => {
  const base = getEndpoint('recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchRequiredApi<JobStatusResponse>(`${base}${separator}${jobId}${separator}cancel`, {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

export const clusterFaces = async (mode: 'sync' | 'async' = 'async'): Promise<ClusterResponse> => {
  const tenantId = getConfig().tenant_id;
  return fetchRequiredApi<ClusterResponse>(getEndpoint('recognitionCluster'), {
    method: 'POST',
    body: {
      tenant_id: tenantId,
      mode,
    },
    restNonce: getConfig().nonce,
  });
};
