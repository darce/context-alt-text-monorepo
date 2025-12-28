/**
 * Hook for fetching and formatting cluster label suggestions.
 *
 * Combines identity-based similarity suggestions with existing labels.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  fetchIdentitySuggestions,
  listRecognitionClusters,
  type IdentitySuggestionsResponse,
} from '../../../api/recognition';
import type { ComboboxOption } from '../../../../components/ui/combobox';

interface UseClusterSuggestionsOptions {
  /** Identity ID to fetch suggestions for */
  identityId: string | undefined;
  /** Whether to enable the suggestions query */
  enabled: boolean;
}

interface UseClusterSuggestionsReturn {
  /** Formatted options for Combobox */
  options: ComboboxOption[];
  /** Whether suggestions are loading */
  isLoading: boolean;
  /** Find cluster ID by label (case-insensitive) */
  findClusterByLabel: (label: string, signal?: AbortSignal) => Promise<{ id: string; label: string } | null>;
}

/**
 * Hook for cluster label suggestions.
 *
 * Fetches:
 * 1. Similarity-based suggestions for the identity
 * 2. All existing cluster labels
 *
 * Returns formatted ComboboxOptions grouped by "Suggested" and "All Labels".
 */
export const useClusterSuggestions = ({
  identityId,
  enabled,
}: UseClusterSuggestionsOptions): UseClusterSuggestionsReturn => {
  const pageSize = 500;
  const maxPages = 20;

  // Fetch similarity suggestions when editing
  const { data: identitySuggestions, isLoading: suggestionsLoading } = useQuery<IdentitySuggestionsResponse>({
    queryKey: ['identity-suggestions', identityId],
    queryFn: () => fetchIdentitySuggestions(identityId!, 5),
    enabled: Boolean(identityId && enabled),
    staleTime: 30000,
  });

  // Format options for Combobox
  const options = React.useMemo<ComboboxOption[]>(() => {
    const result: ComboboxOption[] = [];
    const seen = new Set<string>();

    // Sort suggestions by similarity (descending)
    const sortedSuggestions = (identitySuggestions?.matches ?? []).sort((a, b) => b.similarity - a.similarity);

    // Add suggestions first (higher priority)
    sortedSuggestions.forEach((match) => {
      const normalizedLabel = match.label?.trim() ?? '';
      if (!normalizedLabel) {
        return;
      }

      const key = normalizedLabel.toLowerCase();
      if (seen.has(key)) {
        return;
      }

      seen.add(key);
      result.push({
        value: match.cluster_id,
        label: normalizedLabel,
        group: 'Suggested',
        similarity: match.similarity,
        identityCount: match.identity_count,
      });
    });

    return result;
  }, [identitySuggestions]);

  // Find cluster ID by label (case-insensitive) - checks suggestions first, then paged lookup
  const findClusterByLabel = React.useCallback(
    async (label: string, signal?: AbortSignal): Promise<{ id: string; label: string } | null> => {
      const normalizedLabel = label.toLowerCase();

      const fromOptions = options.find((opt) => opt.label.toLowerCase() === normalizedLabel);
      if (fromOptions?.value) {
        return { id: fromOptions.value, label: fromOptions.label };
      }

      for (let page = 0; page < maxPages; page += 1) {
        const offset = page * pageSize;
        const chunk = await listRecognitionClusters({ limit: pageSize, offset, labeled_only: true }, signal);
        if (!chunk.length) {
          return null;
        }

        const match = chunk.find((cluster) => cluster.label?.toLowerCase() === normalizedLabel);
        if (match?.id && match.label) {
          return { id: match.id, label: match.label };
        }

        if (chunk.length < pageSize) {
          return null;
        }
      }

      return null;
    },
    [maxPages, options, pageSize],
  );

  return {
    options,
    isLoading: suggestionsLoading,
    findClusterByLabel,
  };
};
