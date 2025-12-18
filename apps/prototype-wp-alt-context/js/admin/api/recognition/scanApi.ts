/**
 * Scan Operations API
 *
 * API functions for face scanning and job status.
 */

import { fetchApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { AnalyzeRequest, AnalyzeResponse, JobStatusResponse, ClusterResponse } from './types';

type TenantTier = 'free' | 'pro' | 'business' | 'enterprise';

interface TenantLimits {
  maxMediaPerBatch: number;
  tier: TenantTier;
}

const TIER_VALUES: TenantTier[] = ['free', 'pro', 'business', 'enterprise'];

const isTenantTier = (value: unknown): value is TenantTier =>
  typeof value === 'string' && TIER_VALUES.includes(value as TenantTier);

const getTenantLimits = (): TenantLimits => {
  const config = getConfig();
  const tier: TenantTier = isTenantTier(config.tier) ? config.tier : 'free';

  const rawMax = Number(config.max_media_per_batch ?? 50);
  const maxMediaPerBatch = Number.isFinite(rawMax) && rawMax > 0 ? rawMax : 50;

  return { maxMediaPerBatch, tier };
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
  const { maxMediaPerBatch } = getTenantLimits();
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
  const base = getEndpoint('workbenchRecognitionJobs', 'recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchApi<JobStatusResponse>(`${base}${separator}${jobId}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const cancelScanJob = async (jobId: string): Promise<JobStatusResponse> => {
  const base = getEndpoint('workbenchRecognitionJobs', 'recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchApi<JobStatusResponse>(`${base}${separator}${jobId}${separator}cancel`, {
    method: 'POST',
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
