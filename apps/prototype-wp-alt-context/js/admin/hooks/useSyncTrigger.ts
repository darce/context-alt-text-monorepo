import { useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { triggerSync, type SyncTriggerResponse } from '../api/recognition';
import { queryKeys } from '../api/queryKeys';

/**
 * Auto-trigger a single sync attempt when local projection is stale.
 *
 * Calls POST /acx/v1/recognition/sync/trigger once per stale cycle:
 * - immediately when `isStale` is true
 * - again only after stale becomes false and then true
 *
 * On success the hook invalidates cluster, sync, and identity queries
 * so the UI refreshes automatically.
 */
export const useSyncTrigger = (isStale: boolean) => {
  const queryClient = useQueryClient();
  const shouldAutoTrigger = isStale;
  const attemptedForCurrentStaleRef = useRef(false);

  const mutation = useMutation<SyncTriggerResponse>({
    mutationFn: () => triggerSync(),
    onSuccess: (data) => {
      if (data.synced) {
        // Sync succeeded — refresh queries.
        void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
        void queryClient.invalidateQueries({ queryKey: queryKeys.sync.all });
        void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      }
    },
  });

  useEffect(() => {
    if (!shouldAutoTrigger) {
      attemptedForCurrentStaleRef.current = false;
      return;
    }

    if (attemptedForCurrentStaleRef.current || mutation.isPending) {
      return;
    }

    attemptedForCurrentStaleRef.current = true;
    mutation.mutate();
    // mutation.mutate is stable across renders (React Query guarantee).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shouldAutoTrigger, mutation.isPending]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!shouldAutoTrigger || document.visibilityState !== 'visible' || mutation.isPending) {
        return;
      }
      attemptedForCurrentStaleRef.current = false;
      attemptedForCurrentStaleRef.current = true;
      mutation.mutate();
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
    // mutation.mutate is stable across renders (React Query guarantee).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shouldAutoTrigger, mutation.isPending]);

  return mutation;
};
