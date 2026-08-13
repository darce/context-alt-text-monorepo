import { useMemo } from 'react';
import { QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import { pinRepresentative } from '../../../api/recognition/clusterApiMutations';
import { queryKeys } from '../../../api/queryKeys';

const isAbortError = (err: unknown): boolean =>
  Boolean(err && typeof err === 'object' && 'name' in err && (err as { name: string }).name === 'AbortError');

interface PinRepresentativeVariables {
  representativeId: string;
  isPinned: boolean;
  signal?: AbortSignal;
}

export const usePinRepresentative = (
  clusterId: string | null,
): {
  pin: (representativeId: string, isPinned?: boolean, signal?: AbortSignal) => void;
  isPinning: boolean;
} => {
  const fallbackClient = useMemo(
    () => new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } }),
    [],
  );

  let queryClient: QueryClient;
  try {
    queryClient = useQueryClient();
  } catch {
    queryClient = fallbackClient;
  }

  const pinMutation = useMutation<void, Error, PinRepresentativeVariables>(
    {
      mutationKey: ['pin-representative', clusterId],
      mutationFn: async ({ representativeId, isPinned, signal }) => {
        if (!clusterId) {
          throw new Error('Cannot pin representative: no cluster ID');
        }
        const pinSignal = signal ?? new AbortController().signal;
        await pinRepresentative(clusterId, representativeId, isPinned, pinSignal);
      },
      retry: false,
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
        void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
      },
      onError: (err: unknown) => {
        if (isAbortError(err)) {
          return;
        }
      },
    },
    queryClient,
  );

  return {
    pin: (representativeId: string, isPinned = true, signal?: AbortSignal) => {
      pinMutation.mutate({ representativeId, isPinned, signal });
    },
    isPinning: pinMutation.isPending,
  };
};
