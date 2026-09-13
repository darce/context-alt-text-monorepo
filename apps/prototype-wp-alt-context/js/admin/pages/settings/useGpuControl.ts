import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  GPU_STATE,
  fetchGpuStatus,
  GpuIntentAction,
  GpuIntentStatus,
  postGpuIntent,
  type GpuIntentAction as GpuIntentActionValue,
  type GpuStatusResponse,
} from '../../api/gpuApi';
import { queryKeys } from '../../api/queryKeys';

export const GPU_STATUS_POLL_INTERVAL_MS = 15_000;
export const GPU_WARMUP_POLL_INTERVAL_MS = 5_000;

export const getGpuControlPollInterval = (data: GpuStatusResponse | undefined): number => {
  const state = data?.gpu_state.state;
  return state === GPU_STATE.STARTING || state === GPU_STATE.WARMING
    ? GPU_WARMUP_POLL_INTERVAL_MS
    : GPU_STATUS_POLL_INTERVAL_MS;
};

const getQueryPollInterval = (query: { state: { data: unknown } }): number =>
  getGpuControlPollInterval(query.state.data as GpuStatusResponse | undefined);

const stateCanStart = (state: GpuStatusResponse['gpu_state']['state']): boolean =>
  state === GPU_STATE.STOPPED || state === GPU_STATE.DEGRADED;

const stateCanStop = (state: GpuStatusResponse['gpu_state']['state']): boolean =>
  state === GPU_STATE.STARTING ||
  state === GPU_STATE.WARMING ||
  state === GPU_STATE.READY ||
  state === GPU_STATE.DEGRADED;

const GPU_START_BLOCKED_REASON = {
  STALE_SNAPSHOT: 'Lifecycle telemetry is stale — refresh before starting the GPU.',
  UNKNOWN_STATE: 'GPU state is unknown — refresh before starting the GPU.',
} as const;

const getGpuStartBlockedReason = (data: GpuStatusResponse): string | null => {
  if (!data.snapshot_fresh) {
    return GPU_START_BLOCKED_REASON.STALE_SNAPSHOT;
  }
  if (data.gpu_state.state === GPU_STATE.UNKNOWN) {
    return GPU_START_BLOCKED_REASON.UNKNOWN_STATE;
  }
  return null;
};

const stateStopReason = (data: GpuStatusResponse): string | null => {
  if (data.gpu_state.state === GPU_STATE.STOPPED) {
    return 'already stopped';
  }
  if (!stateCanStop(data.gpu_state.state)) {
    return null;
  }
  if (data.gpu_state.intent === GpuIntentAction.STOP) {
    return 'stop already requested';
  }
  return null;
};

interface GpuMutationContext {
  previous: GpuStatusResponse | undefined;
}

export const useGpuControl = () => {
  const queryClient = useQueryClient();
  const statusKey = queryKeys.gpu.status();
  const statusQuery = useQuery({
    queryKey: statusKey,
    queryFn: fetchGpuStatus,
    refetchInterval: getQueryPollInterval,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const intentMutation = useMutation<GpuStatusResponse, Error, GpuIntentActionValue, GpuMutationContext>({
    mutationFn: (action) => postGpuIntent({ action }),
    retry: false,
    onMutate: async (action) => {
      await queryClient.cancelQueries({ queryKey: statusKey });
      const previous = queryClient.getQueryData<GpuStatusResponse>(statusKey);
      if (previous) {
        queryClient.setQueryData<GpuStatusResponse>(statusKey, {
          ...previous,
          gpu_state: {
            ...previous.gpu_state,
            // STOP has no transitional enum state and can be deferred by active work.
            state: action === GpuIntentAction.START ? GPU_STATE.STARTING : previous.gpu_state.state,
            intent: action,
            intent_status: GpuIntentStatus.PENDING,
          },
        });
      }
      return { previous };
    },
    onError: (_error, _action, context) => {
      if (context?.previous) {
        queryClient.setQueryData(statusKey, context.previous);
      }
    },
    onSuccess: (response) => {
      queryClient.setQueryData(statusKey, response);
    },
  });

  const data = statusQuery.data;
  const effectiveState = data?.snapshot_fresh ? data.gpu_state.state : undefined;
  const canStart = data
    ? effectiveState !== undefined && stateCanStart(effectiveState) && data.gpu_state.intent !== GpuIntentAction.START
    : false;
  const canStop = data ? stateCanStop(data.gpu_state.state) && data.gpu_state.intent !== GpuIntentAction.STOP : false;

  return {
    ...statusQuery,
    data,
    canStart,
    canStop,
    startBlockedReason: data ? getGpuStartBlockedReason(data) : null,
    stopBlockedReason: data ? stateStopReason(data) : null,
    canReturnToAuto: data?.gpu_state.intent !== undefined && data.gpu_state.intent !== GpuIntentAction.AUTO,
    requestIntent: intentMutation.mutate,
    requestIntentAsync: intentMutation.mutateAsync,
    isIntentPending: intentMutation.isPending,
    intentError: intentMutation.error,
  };
};
