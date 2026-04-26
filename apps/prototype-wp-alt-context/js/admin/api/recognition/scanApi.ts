/**
 * Scan Operations API
 *
 * API functions for face scanning and job status.
 */

import { fetchRequiredApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { AnalyzeRequest, AnalyzeResponse, JobStatusResponse, ClusterResponse } from './types';
import { createRecognitionTimeoutSignal } from './requestTimeout';

// Hard cap enforced server-side at AnalysisJobsController::MULTIPART_MAX_IMAGES.
// Sending more than this in one POST returns 400 too_many_multipart_images.
const MULTIPART_MAX_IMAGES = 5;

const getEffectiveBatchSize = (): number => {
  const configured = getConfig().maxMediaPerBatch;
  if (!Number.isFinite(configured) || configured <= 0) {
    return MULTIPART_MAX_IMAGES;
  }
  return Math.min(configured, MULTIPART_MAX_IMAGES);
};

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
    signal: createRecognitionTimeoutSignal(30_000),
  });
};

export const scanFacesBatched = async (request: AnalyzeRequest): Promise<AnalyzeResponse[]> => {
  const batchSize = getEffectiveBatchSize();
  if (request.mediaIds.length <= batchSize) {
    const result = await scanFaces(request);
    return [result];
  }

  const batches = chunkMediaIds(request.mediaIds, batchSize);
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
    signal: createRecognitionTimeoutSignal(15_000),
  });
};

export const cancelScanJob = async (jobId: string): Promise<JobStatusResponse> => {
  const base = getEndpoint('recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchRequiredApi<JobStatusResponse>(`${base}${separator}${jobId}/cancel`, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(15_000),
  });
};

export const acknowledgeProjection = async (
  jobId: string,
  snapshotVersion: number,
): Promise<{ status: string; snapshot_version: number }> => {
  const base = getEndpoint('recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchRequiredApi<{ status: string; snapshot_version: number }>(
    `${base}${separator}${jobId}/acknowledge-projection`,
    {
      method: 'POST',
      body: { snapshot_version: snapshotVersion },
      restNonce: getConfig().nonce,
      // Projection acknowledgement can legitimately take longer than a
      // client round-trip during curation, so keep the browser timeout wide.
      signal: createRecognitionTimeoutSignal(30_000),
    },
  );
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
    signal: createRecognitionTimeoutSignal(15_000),
  });
};
