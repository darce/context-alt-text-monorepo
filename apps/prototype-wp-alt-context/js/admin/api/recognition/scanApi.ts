/**
 * Scan Operations API
 *
 * API functions for face scanning and job status.
 */

import { fetchRequiredApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type {
  AnalyzeRequest,
  AnalyzeResponse,
  BatchAnalyzeResponse,
  BatchRunStatus,
  RecentBatchRunsResponse,
  JobStatusResponse,
  ClusterResponse,
} from './types';
import { createRecognitionTimeoutSignal } from './requestTimeout';
import { chunkMediaIds, createBatchRunId, getEffectiveBatchSize } from './scanBatchHelpers';

const recordClientBatchFailure = async (
  batchRunId: string,
  batchIndex: number,
  submittedTotal: number,
  mediaIds: number[],
): Promise<void> => {
  const base = getEndpoint('recognitionBatchRuns');
  const separator = base.endsWith('/') ? '' : '/';

  await fetchRequiredApi<{ status: string }>(`${base}${separator}${batchRunId}/client-failures`, {
    method: 'POST',
    body: {
      batch_index: batchIndex,
      submitted_total: submittedTotal,
      media_ids: mediaIds,
    },
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(15_000),
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
  if (request.batchRunId) {
    body.batch_run_id = request.batchRunId;
    body.batch_index = request.batchIndex ?? 0;
    body.submitted_total = request.submittedTotal ?? request.mediaIds.length;
  }

  return fetchRequiredApi<AnalyzeResponse>(getEndpoint('recognitionAnalyze'), {
    method: 'POST',
    body,
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(30_000),
  });
};

export const scanFacesBatched = async (request: AnalyzeRequest): Promise<BatchAnalyzeResponse> => {
  const batchRunId = request.batchRunId ?? createBatchRunId();
  const batchSize = getEffectiveBatchSize();
  if (request.mediaIds.length <= batchSize) {
    try {
      const result = await scanFaces({
        ...request,
        batchRunId,
        batchIndex: 0,
        submittedTotal: request.mediaIds.length,
      });
      return { batchRunId, jobs: [result] };
    } catch {
      await recordClientBatchFailure(batchRunId, 0, request.mediaIds.length, request.mediaIds).catch(() => {
        // Best effort only: if the browser cannot report the synthetic failure,
        // the caller still receives an empty jobs list for the batch run.
      });
      return { batchRunId, jobs: [] };
    }
  }

  const batches = chunkMediaIds(request.mediaIds, batchSize);
  const results: AnalyzeResponse[] = [];
  for (const [index, batch] of batches.entries()) {
    try {
      results.push(
        await scanFaces({
          ...request,
          mediaIds: batch,
          batchRunId,
          batchIndex: index,
          submittedTotal: request.mediaIds.length,
        }),
      );
    } catch {
      await recordClientBatchFailure(batchRunId, index, request.mediaIds.length, batch).catch(() => {
        // Best effort only: if the browser cannot report the synthetic failure,
        // the caller still receives the successfully submitted jobs.
      });
    }
  }
  return { batchRunId, jobs: results };
};

export const fetchBatchRunStatus = async (runId: string): Promise<BatchRunStatus> => {
  const base = getEndpoint('recognitionBatchRuns');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchRequiredApi<BatchRunStatus>(`${base}${separator}${runId}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(15_000),
  });
};

export const fetchRecentBatchRuns = async (limit = 5): Promise<RecentBatchRunsResponse> => {
  const base = getEndpoint('recognitionBatchRuns');
  const query = limit > 0 ? `?limit=${encodeURIComponent(String(limit))}` : '';

  return fetchRequiredApi<RecentBatchRunsResponse>(`${base}${query}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(15_000),
  });
};

export const fetchScanStatus = async (jobId: string, signal?: AbortSignal): Promise<JobStatusResponse> => {
  const base = getEndpoint('recognitionJobs');
  const separator = base.endsWith('/') ? '' : '/';

  return fetchRequiredApi<JobStatusResponse>(`${base}${separator}${jobId}`, {
    method: 'GET',
    restNonce: getConfig().nonce,
    // The caller owns cancellation; fetchApi composes it with this deadline.
    // RES-02/RES-13 (heuristics-canon-research/lexicons/engineering.md:113,124):
    // both the wait bound and the integration containment path must be explicit.
    signal,
    timeoutMs: 15_000,
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
