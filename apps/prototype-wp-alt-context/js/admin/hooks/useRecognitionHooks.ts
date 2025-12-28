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
  fetchScanStatus,
  cancelScanJob,
  getRecognitionCluster,
  listRecognitionClusters,
  scanFacesBatched,
  type AnalyzeResponse,
  type ClusterListParams,
  type ClusterResponse,
  type ClusterSummary,
  type JobStatusResponse,
} from '../api/recognition';

export const useScanIdentities = (options?: UseMutationOptions<AnalyzeResponse[], Error, number[], unknown>) =>
  useMutation<AnalyzeResponse[], Error, number[]>({
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
    queryKey: ['recognition-status', jobId],
    enabled: Boolean(jobId) && enabled,
    queryFn: () => fetchScanStatus(jobId!),
    refetchInterval: (query) =>
      query.state.data?.status === 'running' || query.state.data?.status === 'pending' ? 1500 : false,
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
        queryKey: ['recognition-status', jobId],
        queryFn: () => fetchScanStatus(jobId),
        enabled: Boolean(jobId) && enabled,
        refetchInterval: (query) =>
          query.state.data?.status === 'running' || query.state.data?.status === 'pending' ? 1500 : false,
        retry: (failureCount, error) => {
          if (error.message.includes('404')) {
            return false;
          }
          return failureCount < 3;
        },
      }),
    ),
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
}

export const useCombinedScanStatus = (jobId: string | null, activeJobIds: string[]): CombinedScanStatus => {
  const scanStatusQuery = useScanStatus(jobId, Boolean(jobId));
  const multiScanStatus = useMultiScanStatus(activeJobIds, activeJobIds.length > 0);
  return { scanStatusQuery, multiScanStatus };
};

export const useClusterIdentities = (options?: UseMutationOptions<ClusterResponse, Error, void, unknown>) =>
  useMutation<ClusterResponse, Error, void>({
    mutationFn: () => clusterFaces(),
    ...options,
  });

export const useRecognitionClusters = (params: ClusterListParams = {}) =>
  useQuery<ClusterSummary[]>({
    queryKey: ['recognition-clusters', params],
    queryFn: () => listRecognitionClusters(params),
    refetchInterval: 30_000,
  });

export const useRecognitionCluster = (clusterId: string | null, enabled = true) =>
  useQuery<ClusterSummary>({
    queryKey: ['recognition-cluster', clusterId],
    enabled: Boolean(clusterId) && enabled,
    queryFn: () => getRecognitionCluster(clusterId!),
    staleTime: 30_000,
  });
