/**
 * Hook for fetching and formatting cluster label suggestions.
 *
 * Combines identity-based similarity suggestions with existing labels.
 */

import React from 'react';

import type { ClusterSummary } from '../../../api/recognition';
import type { ComboboxOption } from '../../../../components/ui/combobox';
import { useClusterSuggestionsLoader, type ClusterSuggestionsLoaderOptions } from './useClusterSuggestionsLoader';
import type { ProjectedSuggestion } from './suggestionProjection';

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
  identityProjection,
  labelMatches,
  editableClusterId,
  labelInput = '',
}: {
  identityProjection?: readonly ProjectedSuggestion[];
  labelMatches?: ClusterSummary[];
  editableClusterId?: string | null;
  labelInput?: string;
}): ComboboxOption[] => {
  const result: ComboboxOption[] = [];
  const seen = new Set<string>();
  const searchLower = labelInput.toLowerCase().trim();

  // 1. Identity-based suggestions (filtered by current input) — server order, no re-sort.
  (identityProjection ?? []).forEach((projected) => {
    const normalizedLabel = projected.label?.trim() ?? '';
    if (!normalizedLabel) {
      return;
    }
    if (projected.clusterId === editableClusterId) {
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
      value: projected.clusterId,
      label: normalizedLabel,
      group: 'Suggested',
      similarity: projected.similarity,
      identityCount: projected.identityCount,
    });
  });

  // 2. Label search matches (already filtered by API)
  (labelMatches ?? []).forEach((cluster) => {
    if (!cluster.label?.trim()) {
      return;
    }
    if (cluster.id === editableClusterId) {
      return;
    }
    const normalizedLabel = cluster.label.trim();
    const key = normalizedLabel.toLowerCase();
    if (seen.has(key)) {
      return;
    }

    // Enrich All Labels with similarity when the same cluster appears in the identity projection.
    const identityMatch = identityProjection?.find(
      (projected) => projected.clusterId === cluster.id || projected.label?.toLowerCase() === key,
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
  editableClusterId,
  labelInput = '',
  debounceMs,
}: UseClusterSuggestionsOptions): UseClusterSuggestionsReturn => {
  const {
    identityProjection,
    labelMatches,
    isLoading,
    findClusterByLabel: findClusterByLabelRemote,
  } = useClusterSuggestionsLoader({
    identityId,
    enabled,
    editableClusterId,
    labelInput,
    debounceMs,
  });

  const options = React.useMemo(
    () => selectClusterSuggestions({ identityProjection, labelMatches, editableClusterId, labelInput }),
    [identityProjection, labelMatches, editableClusterId, labelInput],
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
