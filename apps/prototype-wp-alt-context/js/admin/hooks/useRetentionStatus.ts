import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  exportTenantData,
  fetchRetentionStatus,
  purgeTenantData,
  updateRetentionPolicy,
  type PurgeTenantDataRequest,
  type RetentionExportResponse,
  type RetentionPolicy,
  type RetentionStatusResponse,
  type UpdateRetentionPolicyRequest,
} from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

export const useRetentionStatus = () =>
  useQuery<RetentionStatusResponse>({
    queryKey: queryKeys.retention.status(),
    queryFn: () => fetchRetentionStatus(),
    staleTime: 60_000,
  });

export const useUpdateRetentionPolicy = () => {
  const queryClient = useQueryClient();

  return useMutation<RetentionPolicy, Error, UpdateRetentionPolicyRequest>({
    mutationFn: (request: UpdateRetentionPolicyRequest) => updateRetentionPolicy(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.retention.status() });
    },
  });
};

export const useExportTenantData = () => {
  const queryClient = useQueryClient();

  return useMutation<RetentionExportResponse, Error, void>({
    mutationFn: () => exportTenantData(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.retention.status() });
    },
  });
};

export const usePurgeTenantData = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: PurgeTenantDataRequest) => purgeTenantData(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.retention.status() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sync.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
  });
};
