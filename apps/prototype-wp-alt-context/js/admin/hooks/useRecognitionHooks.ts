import {
  useMutation,
  useQueries,
  useQuery,
  type UseMutationOptions,
  type UseQueryOptions,
  type UseQueryResult,
} from '@tanstack/react-query';

import {
  acknowledgeProjection,
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
  type AnalyzeResponse,
  type ClusterListParams,
  type ClusterResponse,
  type ClusterSummary,
  type JobStatusResponse,
} from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

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
    refetchInterval: (query) => getJobRefetchInterval(query.state.data),
    retry: (failureCount, error) => {
      if (error.message.includes('404')) {
        return false;
      }
      return failureCount < 3;
    },
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
        refetchInterval: (query) => getJobRefetchInterval(query.state.data),
        retry: (failureCount, error) => {
          if (error.message.includes('404')) {
            return false;
          }
          return failureCount < 3;
        },
      }),
    ),
  });

export const useBatchRunStatus = (runId: string | null, enabled = true) =>
  useQuery<BatchRunStatus>({
    queryKey: queryKeys.jobs.batchRun(runId),
    enabled: Boolean(runId) && enabled,
    queryFn: () => fetchBatchRunStatus(runId!),
    refetchInterval: (query) => getBatchRunRefetchInterval(query.state.data),
    retry: (failureCount, error) => {
      if (error.message.includes('404')) {
        return false;
      }
      return failureCount < 3;
    },
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

export const useAcknowledgeProjection = (
  options?: UseMutationOptions<
    { status: string; snapshot_version: number },
    Error,
    { jobId: string; snapshotVersion: number },
    unknown
  >,
) =>
  useMutation<{ status: string; snapshot_version: number }, Error, { jobId: string; snapshotVersion: number }>({
    mutationFn: ({ jobId, snapshotVersion }) => acknowledgeProjection(jobId, snapshotVersion),
    ...options,
  });

export const useRecognitionClusters = (params: ClusterListParams = {}) =>
  useQuery<ClusterListResponse>({
    queryKey: queryKeys.clusters.list(params),
    queryFn: () => listRecognitionClusters(params),
    refetchInterval: 30_000,
  });

export const useRecognitionCluster = (clusterId: string | null, enabled = true) =>
  useQuery<ClusterSummary>({
    queryKey: queryKeys.clusters.detail(clusterId),
    enabled: Boolean(clusterId) && enabled,
    queryFn: () => getRecognitionCluster(clusterId!),
    staleTime: 30_000,
  });
