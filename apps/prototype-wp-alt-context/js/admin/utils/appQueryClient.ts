import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';

import { openCooldownFromError } from './recognitionCooldown';
import { getRetryDelay, shouldRetryRequest } from './retryPolicy';

/**
 * App-wide QueryClient (UXP-2): one shared retry policy (slice 1) plus the
 * recognition-cooldown arming seam (slice 2). Every error path funnels through
 * openCooldownFromError, which arms only on the server's explicit "ask again
 * later" (429 / 503-with-Retry-After):
 *
 * - the default retry callback sees a failure on FIRST sighting, so gated
 *   pollers pause immediately instead of waiting for retries to drain;
 * - QueryCache.onError covers queries that override retry (e.g.
 *   useMediaIdentities' deliberate retry: false);
 * - MutationCache.onError covers recognition-backed mutations.
 */
export const createAppQueryClient = (): QueryClient =>
  new QueryClient({
    queryCache: new QueryCache({
      onError: (error) => openCooldownFromError(error),
    }),
    mutationCache: new MutationCache({
      onError: (error) => openCooldownFromError(error),
    }),
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          openCooldownFromError(error);
          return shouldRetryRequest(failureCount, error);
        },
        retryDelay: getRetryDelay,
        refetchOnWindowFocus: false,
      },
    },
  });
