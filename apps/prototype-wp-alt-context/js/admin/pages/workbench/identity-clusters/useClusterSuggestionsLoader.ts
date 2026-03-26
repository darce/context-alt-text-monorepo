/**
 * Loader hook for cluster label suggestions.
 *
 * Fetches identity-based similarity suggestions and label search results.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  fetchIdentitySuggestions,
  listRecognitionClusters,
  type ClusterSummary,
  type IdentitySuggestionsResponse,
} from '../../../api/recognition';

export interface ClusterSuggestionsLoaderOptions {
  /** Identity ID to fetch suggestions for */
  identityId: string | undefined;
  /** Whether to enable the suggestions query */
  enabled: boolean;
  /** Current typed label for searching existing clusters */
  labelInput?: string;
  /** Debounce delay for searching (ms) */
  debounceMs?: number;
}

export interface ClusterSuggestionsLoaderResult {
  /** Raw suggestions from identity similarity */
  identitySuggestions?: IdentitySuggestionsResponse;
  /** Raw label search matches */
  labelMatches?: ClusterSummary[];
  /** Whether suggestion queries are loading */
  isLoading: boolean;
  /** Find cluster ID by label (case-insensitive) */
  findClusterByLabel: (label: string, signal?: AbortSignal) => Promise<{ id: string; label: string } | null>;
}

const DEFAULT_DEBOUNCE_MS = 300;

export const useClusterSuggestionsLoader = ({
  identityId,
  enabled,
  labelInput = '',
  debounceMs = DEFAULT_DEBOUNCE_MS,
}: ClusterSuggestionsLoaderOptions): ClusterSuggestionsLoaderResult => {
  const [debouncedLabel, setDebouncedLabel] = React.useState(labelInput);
  const debouncedValue = debounceMs <= 0 ? labelInput : debouncedLabel;

  React.useEffect(() => {
    if (!enabled || debounceMs <= 0) {
      return;
    }

    const timer = window.setTimeout(() => setDebouncedLabel(labelInput), debounceMs);
    return () => window.clearTimeout(timer);
  }, [labelInput, debounceMs, enabled]);

  const { data: identitySuggestions, isLoading: suggestionsLoading } = useQuery<IdentitySuggestionsResponse>({
    queryKey: queryKeys.suggestions.identityFor(identityId),
    queryFn: () => fetchIdentitySuggestions(identityId!, 5),
    enabled: Boolean(identityId && enabled),
    staleTime: 30000,
  });

  const { data: labelMatches, isLoading: labelMatchesLoading } = useQuery({
    queryKey: queryKeys.clusters.labelSearch(debouncedValue),
    queryFn: () =>
      listRecognitionClusters({
        limit: 20,
        offset: 0,
        labeled_only: true,
        search: debouncedValue,
      }),
    enabled: Boolean(enabled && debouncedValue.length >= 2),
    staleTime: 30000,
  });

  const findClusterByLabel = React.useCallback(
    async (label: string, signal?: AbortSignal): Promise<{ id: string; label: string } | null> => {
      const normalizedLabel = label.toLowerCase().trim();
      if (!normalizedLabel) {
        return null;
      }

      try {
        const results = await listRecognitionClusters({ search: label, limit: 10, labeled_only: true }, signal);
        const match = results.find((cluster) => cluster.label.toLowerCase() === normalizedLabel);
        if (match?.id && match.label) {
          return { id: match.id, label: match.label };
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          return null;
        }
        if (err instanceof Error && err.name === 'AbortError') {
          return null;
        }
        console.warn('Failed to find cluster by label:', err);
      }

      return null;
    },
    [],
  );

  return {
    identitySuggestions,
    labelMatches,
    isLoading: suggestionsLoading || labelMatchesLoading,
    findClusterByLabel,
  };
};
