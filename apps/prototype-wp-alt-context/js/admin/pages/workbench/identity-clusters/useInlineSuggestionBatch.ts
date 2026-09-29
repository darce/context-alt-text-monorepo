/**
 * Batched loader for inline "Is this X?" suggestions (UXP-2 Slice 3b / UXP-3 0b-2).
 *
 * One suggestions request per workbench render, for exactly the identities that
 * will render a prompt. Fetches PROJECTION_TOP_K per identity through the shared
 * projection key, projects via projectIdentityWindow (isHumanLabeledTarget),
 * surfaces top-1 eligible match.
 */

import React from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  fetchIdentitiesSuggestions,
  type IdentityBatchSuggestionsResponse,
} from '../../../api/recognition';
import { IDENTITY_SUGGESTIONS_MAX_BATCH_SIZE } from '../../../api/recognition/identityQueriesApi';
import {
  IDENTITY_BATCH_STALE_MS,
  PROJECTION_TOP_K,
  identityBatchIdsKey,
  projectIdentityWindow,
  seedIdentityBatchSingles,
  type ProjectedSuggestion,
} from './suggestionProjection';

export interface InlineSuggestionBatchResult {
  /** Top server-ranked eligible match for an identity, or undefined when none applies. */
  getMatch: (identityId: string | undefined) => ProjectedSuggestion | undefined;
  isLoading: boolean;
  isError: boolean;
}

const MAX_CONCURRENT_SUGGESTION_BATCHES = 4;

/**
 * Issues bounded batched calls to `GET /identities/suggestions` with
 * `top_k=PROJECTION_TOP_K` and indexes the merged keyed-by-id envelope under
 * the shared projection cache key.
 *
 * Also seeds per-identity cache entries (BR-10) so the single-id dropdown loader
 * reuses this response instead of opening a divergent cache entry.
 *
 * The caller derives `identityIds` with the same predicate as the render gate,
 * so an empty set (e.g. label-only mode, no unlabeled cards) fetches nothing.
 * Any failed chunk leaves the query in an error state so missing matches are
 * not reported as a clean no-suggestion result.
 */
export const useInlineSuggestionBatch = (identityIds: string[]): InlineSuggestionBatchResult => {
  const queryClient = useQueryClient();
  // WHY the disable: the rule wants every queryFn dependency mirrored into queryKey, but the only
  // uncovered one is `queryClient` — a provider-scoped singleton used here purely to seed sibling
  // cache entries. It is not an input to the request, and serialising a client instance into a cache
  // key would fragment the cache on client identity rather than on data. `identityIds`, the real
  // request input, is already in the key.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  const batchQueryKey = queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey(identityIds));
  const { data, isLoading, isError } = useQuery<IdentityBatchSuggestionsResponse>({
    queryKey: batchQueryKey,
    queryFn: async () => {
      const batches: string[][] = [];
      for (let offset = 0; offset < identityIds.length; offset += IDENTITY_SUGGESTIONS_MAX_BATCH_SIZE) {
        batches.push(identityIds.slice(offset, offset + IDENTITY_SUGGESTIONS_MAX_BATCH_SIZE));
      }

      type BatchOutcome =
        | { succeeded: true; identityIds: string[]; response: IdentityBatchSuggestionsResponse }
        | { succeeded: false };
      const outcomes: BatchOutcome[] = batches.map(() => ({ succeeded: false }));
      let nextBatchIndex = 0;
      const workers = Array.from(
        { length: Math.min(MAX_CONCURRENT_SUGGESTION_BATCHES, batches.length) },
        async () => {
          while (true) {
            const batchIndex = nextBatchIndex;
            nextBatchIndex += 1;
            const batch = batches[batchIndex];
            if (!batch) {
              return;
            }

            try {
              outcomes[batchIndex] = {
                succeeded: true,
                identityIds: batch,
                response: await fetchIdentitiesSuggestions(batch, PROJECTION_TOP_K),
              };
            } catch {
              outcomes[batchIndex] = { succeeded: false };
            }
          }
        },
      );
      await Promise.all(workers);

      const hasFailedBatch = outcomes.some((outcome) => !outcome?.succeeded);
      const matches: IdentityBatchSuggestionsResponse['matches'] = {};
      const successfulIdentityIds: string[] = [];
      for (const outcome of outcomes) {
        if (!outcome?.succeeded) {
          continue;
        }
        successfulIdentityIds.push(...outcome.identityIds);
        Object.assign(matches, outcome.response.matches);
      }

      const response = { matches };
      seedIdentityBatchSingles(queryClient, response, successfulIdentityIds);
      if (hasFailedBatch) {
        queryClient.setQueryData(batchQueryKey, response);
        throw new Error('One or more identity suggestion batches failed.');
      }
      return response;
    },
    enabled: identityIds.length > 0,
    staleTime: IDENTITY_BATCH_STALE_MS,
  });

  const getMatch = React.useCallback(
    (identityId: string | undefined): ProjectedSuggestion | undefined => {
      if (!identityId) {
        return undefined;
      }
      const rows = data?.matches?.[identityId] ?? [];
      // Human-label predicate inside PROJECTION_TOP_K; first projected row (server order).
      return projectIdentityWindow(identityId, rows)[0];
    },
    [data],
  );

  return { getMatch, isLoading, isError };
};
