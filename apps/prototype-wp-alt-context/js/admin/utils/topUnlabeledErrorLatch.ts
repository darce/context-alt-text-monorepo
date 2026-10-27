import { partialMatchKey, type Query, type QueryClient } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';

// Every tenant's top-unlabeled key: the builder's shape minus the tenant segment.
const TOP_UNLABELED_KEY_PREFIX = queryKeys.clusters.topUnlabeled('').slice(0, -1);

const settledErrorsByClient = new WeakMap<QueryClient, WeakMap<Query, unknown>>();

const isTopUnlabeledQuery = (query: Query): boolean =>
  partialMatchKey(query.queryKey, TOP_UNLABELED_KEY_PREFIX);

/**
 * RLSE-04 / REF-19: the one owner of each QueryClient's last settled
 * top-unlabeled error. RQ v5 clears `error` when a no-data query refetches, so
 * readers fall back to this map to keep the error class (auth expiry above
 * all) through the fetching / paused gap. It watches every producer of the
 * key — Roster total, job-effects refetch, queue hook — for every tenant, so
 * it must exist before any of them settles; createAppQueryClient installs it
 * at creation. Idempotent: one cache subscription per client.
 */
export const installTopUnlabeledErrorLatch = (queryClient: QueryClient): WeakMap<Query, unknown> => {
  const installed = settledErrorsByClient.get(queryClient);
  if (installed) return installed;

  const settledErrors = new WeakMap<Query, unknown>();
  settledErrorsByClient.set(queryClient, settledErrors);
  const queryCache = queryClient.getQueryCache();
  // A client not built by createAppQueryClient installs lazily, after its
  // cache may already hold a settled error this subscription never saw.
  for (const query of queryCache.getAll()) {
    if (isTopUnlabeledQuery(query) && query.state.status === 'error' && query.state.error != null) {
      settledErrors.set(query, query.state.error);
    }
  }
  // Only final errors are latched; intermediate retry attempts emit `failed`.
  queryCache.subscribe((event) => {
    // Cache events type the query with `any` generics; the latch keys on identity only.
    const query = event.query as Query;
    if (!isTopUnlabeledQuery(query)) return;
    if (event.type === 'removed') {
      settledErrors.delete(query);
    } else if (event.type === 'updated') {
      if (event.action.type === 'error') {
        settledErrors.set(query, event.action.error);
      } else if (event.action.type === 'success') {
        settledErrors.delete(query);
      }
    }
  });
  return settledErrors;
};
