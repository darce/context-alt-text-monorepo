/**
 * Batched loader for inline "Is this X?" suggestions (UXP-2 Slice 3b).
 *
 * One suggestions request per workbench render, for exactly the identities that
 * will render a prompt. The endpoint is bounded per identity (`top_k`), so
 * completeness is structural — no `limit` juggling or truncation heuristic.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  fetchIdentitiesSuggestions,
  type ClusterSuggestion,
  type IdentityBatchSuggestionsResponse,
} from '../../../api/recognition';

export interface InlineSuggestionBatchResult {
  /** Top server-ranked match for an identity, or undefined when none applies. */
  getMatch: (identityId: string | undefined) => ClusterSuggestion | undefined;
  isLoading: boolean;
}

/**
 * Issues the single batched call to `GET /identities/suggestions` with `top_k=1`
 * for the supplied identity ids and indexes the keyed-by-id envelope.
 *
 * The caller derives `identityIds` with the same predicate as the render gate,
 * so an empty set (e.g. label-only mode, no unlabeled cards) fetches nothing.
 */
export const useInlineSuggestionBatch = (identityIds: string[]): InlineSuggestionBatchResult => {
  const { data, isLoading } = useQuery<IdentityBatchSuggestionsResponse>({
    queryKey: queryKeys.suggestions.inlineBatch(identityIds),
    queryFn: () => fetchIdentitiesSuggestions(identityIds, 1),
    enabled: identityIds.length > 0,
    staleTime: 60000,
  });

  const getMatch = React.useCallback(
    (identityId: string | undefined): ClusterSuggestion | undefined => {
      if (!identityId) {
        return undefined;
      }
      // Keyed by identity id; take the first (server-ranked) match.
      return data?.matches?.[identityId]?.[0];
    },
    [data],
  );

  return { getMatch, isLoading };
};
