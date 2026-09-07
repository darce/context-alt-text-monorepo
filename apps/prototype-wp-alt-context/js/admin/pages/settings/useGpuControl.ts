import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
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
  return state === 'starting' || state === 'warming'
    ? GPU_WARMUP_POLL_INTERVAL_MS
    : GPU_STATUS_POLL_INTERVAL_MS;
};

const getQueryPollInterval = (query: { state: { data: unknown } }): number =>
  getGpuControlPollInterval(query.state.data as GpuStatusResponse | undefined);

const stateCanStart = (state: GpuStatusResponse['gpu_state']['state']): boolean =>
  state === 'stopped' || state === 'unknown' || state === 'degraded';

const stateCanStop = (state: GpuStatusResponse['gpu_state']['state']): boolean =>
  state === 'starting' || state === 'warming' || state === 'ready' || state === 'degraded';

const stateStopReason = (data: GpuStatusResponse): string | null => {
  if (data.gpu_state.state === 'stopped') {
    return 'already stopped';
  }
  if (!stateCanStop(data.gpu_state.state)) {
    return null;
  }
  if (data.gpu_state.intent === GpuIntentAction.STOP) {
    return 'stop already requested';
  }
  if (data.load.has_work) {
    return 'a describe run is in flight — stops once it finishes';
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
  const effectiveState = data && data.snapshot_fresh ? data.gpu_state.state : data ? 'unknown' : undefined;
  const canStart = data
    ? stateCanStart(effectiveState ?? 'unknown') && data.gpu_state.intent !== GpuIntentAction.START
    : false;
  const canStop = data
    ? stateCanStop(data.gpu_state.state) && !data.load.has_work && data.gpu_state.intent !== GpuIntentAction.STOP
    : false;

  return {
    ...statusQuery,
    data,
    canStart,
    canStop,
    stopBlockedReason: data ? stateStopReason(data) : null,
    canReturnToAuto: data?.gpu_state.intent !== undefined && data.gpu_state.intent !== GpuIntentAction.AUTO,
    requestIntent: intentMutation.mutate,
    requestIntentAsync: intentMutation.mutateAsync,
    isIntentPending: intentMutation.isPending,
    intentError: intentMutation.error,
  };
};
