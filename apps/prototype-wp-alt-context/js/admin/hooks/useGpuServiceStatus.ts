/**
 * Idle Description Service status poller for the workbench chip (GPUFLOW-2 A8).
 *
 * Settings cadence while no run/Suggest is pending; the in-flight run's
 * `gpu_state` wins while this poll is paused (INT-10, OBS-08).
 */
import { useQuery } from '@tanstack/react-query';

import {
  fetchGpuStatus,
  GPU_STATE,
  type GpuIntentAction,
  type GpuState,
  type GpuStatusResponse,
} from '../api/gpuApi';
import { queryKeys } from '../api/queryKeys';
import { gateRefetchInterval } from '../utils/recognitionCooldown';

/** Same idle cadence as Settings `useGpuControl` (15 s). */
export const GPU_SERVICE_STATUS_POLL_INTERVAL_MS = 15_000;
/** Same warming cadence as Settings `useGpuControl` (5 s). */
export const GPU_SERVICE_STATUS_WARMUP_POLL_INTERVAL_MS = 5_000;
/** Backoff after a failed idle poll; never a client-invented warmup ceiling. */
export const GPU_SERVICE_STATUS_ERROR_BACKOFF_MS = 30_000;

export interface UseGpuServiceStatusOptions {
  /** True while a describe run or Suggest is in flight — pause idle polls. */
  isRunPending?: boolean;
}

export interface GpuServiceStatus {
  data: GpuStatusResponse | undefined;
  gpuState: GpuState;
  snapshotFresh: boolean;
  intent: GpuIntentAction | null;
  reason: string | null;
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  isPolling: boolean;
  refetch: () => void;
}

export const getGpuServiceStatusPollInterval = (
  data: GpuStatusResponse | undefined,
  isError = false,
): number => {
  if (isError) {
    return GPU_SERVICE_STATUS_ERROR_BACKOFF_MS;
  }
  const state = data?.gpu_state.state;
  return state === GPU_STATE.STARTING || state === GPU_STATE.WARMING
    ? GPU_SERVICE_STATUS_WARMUP_POLL_INTERVAL_MS
    : GPU_SERVICE_STATUS_POLL_INTERVAL_MS;
};

export const useGpuServiceStatus = ({
  isRunPending = false,
}: UseGpuServiceStatusOptions = {}): GpuServiceStatus => {
  const statusQuery = useQuery<GpuStatusResponse, Error>({
    queryKey: queryKeys.gpu.status(),
    queryFn: fetchGpuStatus,
    enabled: !isRunPending,
    refetchOnWindowFocus: false,
    retry: false,
    refetchInterval: gateRefetchInterval((query: { state: { data: GpuStatusResponse | undefined; status: string } }) => {
      if (isRunPending) {
        return false;
      }
      return getGpuServiceStatusPollInterval(query.state.data, query.state.status === 'error');
    }),
  });

  const data = statusQuery.data;
  const gpuState = data?.gpu_state.state ?? GPU_STATE.UNKNOWN;

  return {
    data,
    gpuState,
    snapshotFresh: data?.snapshot_fresh ?? false,
    intent: data?.gpu_state.intent ?? null,
    reason: data?.gpu_state.reason ?? null,
    isLoading: statusQuery.isLoading,
    isFetching: statusQuery.isFetching,
    isError: statusQuery.isError,
    isPolling: !isRunPending,
    refetch: () => {
      void statusQuery.refetch();
    },
  };
};
