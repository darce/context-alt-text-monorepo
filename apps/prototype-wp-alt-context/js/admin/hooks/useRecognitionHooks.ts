import { useMutation, useQuery, type UseMutationOptions } from '@tanstack/react-query';

import {
  clusterFaces,
  fetchScanStatus,
  getRecognitionCluster,
  listRecognitionClusters,
  scanFaces,
  type AnalyzeResponse,
  type ClusterListParams,
  type ClusterResponse,
  type ClusterSummary,
  type ScanStatus,
} from '../api/recognitionApi';

export const useScanIdentities = (options?: UseMutationOptions<AnalyzeResponse, Error, number[], unknown>) =>
  useMutation<AnalyzeResponse, Error, number[]>({
    mutationFn: (mediaIds) => scanFaces({ mediaIds }),
    ...options,
  });

export const useScanStatus = (jobId: string | null, enabled = true) =>
  useQuery<ScanStatus>({
    queryKey: ['recognition-status', jobId],
    enabled: Boolean(jobId) && enabled,
    queryFn: () => fetchScanStatus(jobId as string),
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 1500 : false),
  });

export const useClusterIdentities = (options?: UseMutationOptions<ClusterResponse, Error, void, unknown>) =>
  useMutation<ClusterResponse, Error, void>({
    mutationFn: () => clusterFaces({ similarity_threshold: 0.6 }),
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
    queryFn: () => getRecognitionCluster(clusterId as string),
    staleTime: 30_000,
  });
