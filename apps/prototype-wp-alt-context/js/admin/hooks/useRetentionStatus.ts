import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import {
  applyRetentionPreset,
  downloadExportJobData,
  exportTenantData,
  fetchAuditEvents,
  fetchRetentionStatus,
  getExportJobStatus,
  importTenantData,
  purgeTenantData,
  updateRetentionPolicy,
  type ApplyRetentionPresetRequest,
  type ApplyRetentionPresetResponse,
  type AuditEventListResponse,
  type ExportJobStatusResponse,
  type ImportTenantDataRequest,
  type ImportTenantDataResponse,
  type PurgeTenantDataRequest,
  type RetentionExportResponse,
  type RetentionPolicy,
  type RetentionStatusResponse,
  type StartExportJobResponse,
  type UpdateRetentionPolicyRequest,
} from '../api/recognition';
import { queryKeys } from '../api/queryKeys';
import { gateRefetchInterval } from '../utils/recognitionCooldown';

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

  return useMutation<StartExportJobResponse, Error, void>({
    mutationFn: () => exportTenantData(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.retention.status() });
    },
  });
};

export const useExportJobStatus = (jobId: string | null): UseQueryResult<ExportJobStatusResponse, Error> =>
  useQuery<ExportJobStatusResponse>({
    queryKey: queryKeys.retention.exportJob(jobId ?? ''),
    queryFn: () => {
      if (jobId === null) {
        throw new Error('useExportJobStatus called without a valid jobId');
      }
      return getExportJobStatus(jobId);
    },
    enabled: jobId !== null,
    // Gated on the shared recognition cooldown (UXP-2 slice 2, 7th poller): the
    // 2s status poll reaches recognition via RetentionController::get_export_job_status
    // (proxy_request to /retention/export/{id}/status), so a 429 must quiet it too.
    refetchInterval: gateRefetchInterval((query) => {
      const status = query.state.data?.status;
      if (status === 'completed' || status === 'failed') {
        return false;
      }
      return 2000;
    }),
  });

export const useDownloadExportJobData = () =>
  useMutation<RetentionExportResponse, Error, string>({
    mutationFn: (jobId: string) => downloadExportJobData(jobId),
  });

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

export const useImportTenantData = () => {
  const queryClient = useQueryClient();

  return useMutation<ImportTenantDataResponse, Error, ImportTenantDataRequest>({
    mutationFn: (request: ImportTenantDataRequest) => importTenantData(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.retention.status() });
    },
  });
};

export const useAuditEvents = (params: {
  limit?: number;
  offset?: number;
  event_type?: string;
}): UseQueryResult<AuditEventListResponse, Error> =>
  useQuery<AuditEventListResponse>({
    queryKey: queryKeys.retention.audit(params),
    queryFn: () => fetchAuditEvents(params),
    staleTime: 30_000,
  });

export const useApplyRetentionPreset = () => {
  const queryClient = useQueryClient();
  return useMutation<ApplyRetentionPresetResponse, Error, ApplyRetentionPresetRequest>({
    mutationFn: (request) => applyRetentionPreset(request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.retention.status() });
    },
  });
};
