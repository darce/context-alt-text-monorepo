/**
 * Hook for fetching and formatting cluster label suggestions.
 *
 * Combines identity-based similarity suggestions with existing labels.
 */

import React from 'react';

import type { ClusterSummary, IdentitySuggestionsResponse } from '../../../api/recognition';
import type { ComboboxOption } from '../../../../components/ui/combobox';
import { useClusterSuggestionsLoader, type ClusterSuggestionsLoaderOptions } from './useClusterSuggestionsLoader';

type UseClusterSuggestionsOptions = ClusterSuggestionsLoaderOptions;

interface UseClusterSuggestionsReturn {
  /** Formatted options for Combobox */
  options: ComboboxOption[];
  /** Whether suggestions are loading */
  isLoading: boolean;
  /** Find cluster ID by label (case-insensitive) */
  findClusterByLabel: (label: string, signal?: AbortSignal) => Promise<{ id: string; label: string } | null>;
}

export const selectClusterSuggestions = ({
  identitySuggestions,
  labelMatches,
  labelInput = '',
}: {
  identitySuggestions?: IdentitySuggestionsResponse;
  labelMatches?: ClusterSummary[];
  labelInput?: string;
}): ComboboxOption[] => {
  const result: ComboboxOption[] = [];
  const seen = new Set<string>();
  const searchLower = labelInput.toLowerCase().trim();

  // 1. Identity-based suggestions (filtered by current input)
  (identitySuggestions?.matches ?? [])
    .sort((a, b) => b.similarity - a.similarity)
    .forEach((match) => {
      const normalizedLabel = match.label?.trim() ?? '';
      if (!normalizedLabel) {
        return;
      }
      const key = normalizedLabel.toLowerCase();

      // Filter: label must match input if any provided
      if (searchLower && !key.includes(searchLower)) {
        return;
      }
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

  // 2. Label search matches (already filtered by API)
  (labelMatches ?? []).forEach((cluster) => {
    if (!cluster.label?.trim()) {
      return;
    }
    const normalizedLabel = cluster.label.trim();
    const key = normalizedLabel.toLowerCase();
    if (seen.has(key)) {
      return;
    }

    // Try to find similarity from identitySuggestions if this cluster label is also suggested for identity
    const identityMatch = identitySuggestions?.matches?.find(
      (match) => match.cluster_id === cluster.id || (match.label && match.label.toLowerCase() === key),
    );

    seen.add(key);
    result.push({
      value: cluster.id,
      label: normalizedLabel,
      group: 'All Labels',
      similarity: identityMatch?.similarity,
      identityCount: cluster.identity_count,
    });
  });

  return result;
};

/**
 * Hook for cluster label suggestions.
 *
 * Fetches:
 * 1. Similarity-based suggestions for the identity
 * 2. Label-based search results for existing clusters (debounced)
 *
 * Returns formatted ComboboxOptions grouped by "Suggested" and "All Labels".
 */
export const useClusterSuggestions = ({
  identityId,
  enabled,
  labelInput = '',
  debounceMs,
}: UseClusterSuggestionsOptions): UseClusterSuggestionsReturn => {
  const {
    identitySuggestions,
    labelMatches,
    isLoading,
    findClusterByLabel: findClusterByLabelRemote,
  } = useClusterSuggestionsLoader({
    identityId,
    enabled,
    labelInput,
    debounceMs,
  });

  const options = React.useMemo(
    () => selectClusterSuggestions({ identitySuggestions, labelMatches, labelInput }),
    [identitySuggestions, labelMatches, labelInput],
  );

  const findClusterByLabel = React.useCallback(
    async (label: string, signal?: AbortSignal): Promise<{ id: string; label: string } | null> => {
      const normalizedLabel = label.toLowerCase().trim();
      if (!normalizedLabel) {
        return null;
      }

      const fromOptions = options.find((opt) => opt.label.toLowerCase() === normalizedLabel);
      if (fromOptions?.value) {
        return { id: fromOptions.value, label: fromOptions.label };
      }

      return findClusterByLabelRemote(label, signal);
    },
    [options, findClusterByLabelRemote],
  );

  return {
    options,
    isLoading,
    findClusterByLabel,
  };
};
