/**
 * Batched loader for inline "Is this X?" suggestions (UXP-2 Slice 3b / UXP-3 0b-1).
 *
 * One suggestions request per workbench render, for exactly the identities that
 * will render a prompt. Fetches PROJECTION_TOP_K per identity through the shared
 * projection key, adapts rows to ProjectedSuggestion, and surfaces the first
 * truthy-labeled match in server order.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import { fetchIdentitiesSuggestions, type IdentityBatchSuggestionsResponse } from '../../../api/recognition';
import {
  PROJECTION_TOP_K,
  fromIdentityMatch,
  identityBatchIdsKey,
  type ProjectedSuggestion,
} from './suggestionProjection';

export interface InlineSuggestionBatchResult {
  /** Top server-ranked match for an identity, or undefined when none applies. */
  getMatch: (identityId: string | undefined) => ProjectedSuggestion | undefined;
  isLoading: boolean;
}

/** Commit-1 local eligibility: truthy trimmed label (auto cluster-* labels still surface). */
const isTruthyLabel = (label: string | null | undefined): boolean => Boolean(label?.trim());

/**
 * Issues the single batched call to `GET /identities/suggestions` with
 * `top_k=PROJECTION_TOP_K` for the supplied identity ids and indexes the
 * keyed-by-id envelope under the shared projection cache key.
 *
 * The caller derives `identityIds` with the same predicate as the render gate,
 * so an empty set (e.g. label-only mode, no unlabeled cards) fetches nothing.
 */
export const useInlineSuggestionBatch = (identityIds: string[]): InlineSuggestionBatchResult => {
  const { data, isLoading } = useQuery<IdentityBatchSuggestionsResponse>({
    queryKey: queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey(identityIds)),
    queryFn: () => fetchIdentitiesSuggestions(identityIds, PROJECTION_TOP_K),
    enabled: identityIds.length > 0,
    staleTime: 60000,
  });

  const getMatch = React.useCallback(
    (identityId: string | undefined): ProjectedSuggestion | undefined => {
      if (!identityId) {
        return undefined;
      }
      const rows = data?.matches?.[identityId] ?? [];
      // First truthy-labeled row in server order (commit-1 eligibility).
      return rows
        .map((match) => fromIdentityMatch(identityId, match))
        .find((projected) => isTruthyLabel(projected.label));
    },
    [data],
  );

  return { getMatch, isLoading };
};
