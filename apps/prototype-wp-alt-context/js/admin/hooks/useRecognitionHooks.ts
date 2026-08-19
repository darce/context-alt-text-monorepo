import {
  useMutation,
  useQueries,
  useQuery,
  type UseMutationOptions,
  type UseQueryOptions,
  type UseQueryResult,
} from '@tanstack/react-query';

import {
  clusterFaces,
  fetchBatchRunStatus,
  fetchScanStatus,
  cancelScanJob,
  type BatchAnalyzeResponse,
  type BatchRunStatus,
  type ClusterListResponse,
  getRecognitionCluster,
  listRecognitionClusters,
  scanFacesBatched,
  type ClusterListParams,
  type ClusterResponse,
  type ClusterSummary,
  type JobStatusResponse,
} from '../api/recognition';
import { queryKeys } from '../api/queryKeys';
import { gateRefetchInterval } from '../utils/recognitionCooldown';

/**
 * Returns the polling interval for a recognition job status query.
 * Exported so tests can exercise the real logic rather than duplicating it.
 */
export const getJobRefetchInterval = (data: JobStatusResponse | undefined): number | false => {
  const isActive = data?.status === 'running' || data?.status === 'pending';
  const isAwaitingProjection = data?.progress?.phase === 'awaiting_projection';
  return isActive || isAwaitingProjection ? 1500 : false;
};

export const getBatchRunRefetchInterval = (data: BatchRunStatus | undefined): number | false =>
  data && !data.terminal_state ? 1500 : false;

export const useScanIdentities = (options?: UseMutationOptions<BatchAnalyzeResponse, Error, number[], unknown>) =>
  useMutation<BatchAnalyzeResponse, Error, number[]>({
    mutationFn: async (mediaIds) => {
      if (mediaIds.length === 0) {
        throw new Error('No media IDs provided for analysis.');
      }
      return scanFacesBatched({ mediaIds });
    },
    ...options,
  });

export const useScanStatus = (jobId: string | null, enabled = true) =>
  useQuery<JobStatusResponse>({
    queryKey: queryKeys.jobs.status(jobId),
    enabled: Boolean(jobId) && enabled,
    queryFn: () => fetchScanStatus(jobId!),
    refetchInterval: gateRefetchInterval((query) => getJobRefetchInterval(query.state.data)),
  });

export const useCancelScanJobs = (options?: UseMutationOptions<JobStatusResponse[], Error, string[], unknown>) =>
  useMutation<JobStatusResponse[], Error, string[]>({
    mutationFn: async (jobIds) => Promise.all(jobIds.map((jobId) => cancelScanJob(jobId))),
    ...options,
  });

export const useMultiScanStatus = (jobIds: string[], enabled = true) =>
  useQueries({
    queries: jobIds.map(
      (jobId): UseQueryOptions<JobStatusResponse, Error> => ({
        queryKey: queryKeys.jobs.status(jobId),
        queryFn: () => fetchScanStatus(jobId),
        enabled: Boolean(jobId) && enabled,
        refetchInterval: gateRefetchInterval((query) => getJobRefetchInterval(query.state.data)),
      }),
    ),
  });

export const useBatchRunStatus = (runId: string | null, enabled = true) =>
  useQuery<BatchRunStatus>({
    queryKey: queryKeys.jobs.batchRun(runId),
    enabled: Boolean(runId) && enabled,
    queryFn: () => fetchBatchRunStatus(runId!),
    refetchInterval: gateRefetchInterval((query) => getBatchRunRefetchInterval(query.state.data)),
  });

/**
 * Combined hook for tracking both single and multi-scan status.
 * Reduces hook count in components that need both status trackers.
 */
export interface CombinedScanStatus {
  /** Status query for the primary/selected job */
  scanStatusQuery: UseQueryResult<JobStatusResponse, Error>;
  /** Status queries for all active batch jobs */
  multiScanStatus: UseQueryResult<JobStatusResponse, Error>[];
  /** Aggregate status for the active batch run */
  batchRunStatusQuery: UseQueryResult<BatchRunStatus, Error>;
}

export const useCombinedScanStatus = (
  jobId: string | null,
  activeJobIds: string[],
  batchRunId: string | null,
): CombinedScanStatus => {
  const scanStatusQuery = useScanStatus(jobId, Boolean(jobId));
  const multiScanStatus = useMultiScanStatus(activeJobIds, activeJobIds.length > 0);
  const batchRunStatusQuery = useBatchRunStatus(batchRunId, Boolean(batchRunId));
  return { scanStatusQuery, multiScanStatus, batchRunStatusQuery };
};

export const useClusterIdentities = (options?: UseMutationOptions<ClusterResponse, Error, void, unknown>) =>
  useMutation<ClusterResponse, Error, void>({
    mutationFn: () => clusterFaces(),
    ...options,
  });

/**
 * Quarantined. Zero roster/UI callers — RosterPage uses useRecognitionCluster
 * (detail) only. Kept solely as UXP-2 cooldown-gate membership: the six-poller
 * contract in recognitionCooldown.ts + recognitionCooldownGate.test.tsx mounts
 * this hook. Those files are outside this lane; deleting the export here would
 * shrink the gated set without a replacement poller.
 * Follow-up: UXW2-5 drop useRecognitionClusters from the UXP-2 poller set and
 * delete this export once a cooldown-gate lane owns that contract. Not a bulk
 * surface to re-attach.
 */
export const useRecognitionClusters = (params: ClusterListParams = {}) =>
  useQuery<ClusterListResponse>({
    queryKey: queryKeys.clusters.list(params),
    queryFn: () => listRecognitionClusters(params),
    refetchInterval: gateRefetchInterval(30_000),
  });

export const useRecognitionCluster = (clusterId: string | null, enabled = true) =>
  useQuery<ClusterSummary>({
    queryKey: queryKeys.clusters.detail(clusterId),
    enabled: Boolean(clusterId) && enabled,
    queryFn: () => getRecognitionCluster(clusterId!),
    staleTime: 30_000,
  });
