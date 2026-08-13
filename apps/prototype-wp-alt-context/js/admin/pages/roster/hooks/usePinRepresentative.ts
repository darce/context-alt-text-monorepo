import { useMutation, useQueryClient } from '@tanstack/react-query';
import { __ } from '@wordpress/i18n';

import { pinRepresentative } from '../../../api/recognition/clusterApiMutations';
import { queryKeys } from '../../../api/queryKeys';

export const PIN_REPRESENTATIVE_ERROR_COPY = __(
  'Could not set this face as representative.',
  'alt-context',
);

const isAbortError = (err: unknown): boolean =>
  Boolean(err && typeof err === 'object' && 'name' in err && (err as { name: string }).name === 'AbortError');

interface PinRepresentativeVariables {
  clusterId: string;
  representativeId: string;
  isPinned: boolean;
  signal?: AbortSignal;
}

export const usePinRepresentative = (): {
  pin: (clusterId: string, representativeId: string, isPinned?: boolean, signal?: AbortSignal) => void;
  isPinning: boolean;
  pinError: unknown;
} => {
  const queryClient = useQueryClient();

  const pinMutation = useMutation<void, Error, PinRepresentativeVariables>({
    mutationKey: ['pin-representative'],
    mutationFn: async ({ clusterId, representativeId, isPinned, signal }) => {
      const pinSignal = signal ?? new AbortController().signal;
      await pinRepresentative(clusterId, representativeId, isPinned, pinSignal);
    },
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
    },
  });

  const pinError = pinMutation.isError && !isAbortError(pinMutation.error) ? pinMutation.error : null;

  return {
    pin: (clusterId, representativeId, isPinned = true, signal?) => {
      if (pinMutation.isPending) {
        return;
      }
      pinMutation.mutate({ clusterId, representativeId, isPinned, signal });
    },
    isPinning: pinMutation.isPending,
    pinError,
  };
};
