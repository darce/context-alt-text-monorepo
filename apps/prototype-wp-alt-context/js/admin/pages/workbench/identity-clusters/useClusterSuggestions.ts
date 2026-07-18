/**
 * Hook for fetching and formatting cluster label suggestions.
 *
 * Combines identity-based similarity suggestions with the shared naming union
 * (roster persons ∪ human-labeled clusters).
 */

import React from 'react';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import {
  isClusterNamingOption,
  type NamingOption,
  unwrapClusterOptionId,
  namingOptionValue,
} from './buildNamingOptions';
import { useClusterSuggestionsLoader, type ClusterSuggestionsLoaderOptions } from './useClusterSuggestionsLoader';
import type { ProjectedSuggestion } from './suggestionProjection';

type UseClusterSuggestionsOptions = ClusterSuggestionsLoaderOptions;

interface UseClusterSuggestionsReturn {
  /** Formatted options for Combobox / edit form */
  options: ComboboxOption[];
  /** Whether suggestions are loading */
  isLoading: boolean;
  /** Pre-dedupe collisions for the duplicate guard */
  collisionsByLabel: ReadonlyMap<string, readonly NamingOption[]>;
  /** Find cluster ID by label (case-insensitive); cluster-source options only (PR-16) */
  findClusterByLabel: (label: string, signal?: AbortSignal) => Promise<{ id: string; label: string } | null>;
}

export const selectClusterSuggestions = ({
  identityProjection,
  namingOptions,
  editableClusterId,
  labelInput = '',
}: {
  identityProjection?: readonly ProjectedSuggestion[];
  namingOptions?: readonly NamingOption[];
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

    if (searchLower && !key.includes(searchLower)) {
      return;
    }
    if (seen.has(key)) {
      return;
    }

    seen.add(key);
    result.push({
      value: namingOptionValue('cluster', projected.clusterId),
      label: normalizedLabel,
      group: 'Suggested',
      source: 'cluster',
      similarity: projected.similarity,
      identityCount: projected.identityCount,
      suggestion_id: projected.suggestionId,
    });
  });

  // 2. Union naming options (persons badged, then labeled clusters) — seen-dedupe across groups.
  (namingOptions ?? []).forEach((option) => {
    const key = option.label.toLowerCase();
    if (seen.has(key)) {
      return;
    }
    if (searchLower && !key.includes(searchLower)) {
      return;
    }

    seen.add(key);
    result.push({
      value: option.value,
      label: option.label,
      group: 'All Labels',
      source: option.source,
      identityCount: option.identityCount,
    });
  });

  return result;
};

/**
 * Resolve a merge/assign target from options: cluster-source only (PR-16).
 * Person hits return null so the save path renames instead of merging.
 */
export const resolveClusterMatchFromOptions = (
  options: readonly ComboboxOption[],
  label: string,
): { id: string; label: string } | null => {
  const normalizedLabel = label.toLowerCase().trim();
  if (!normalizedLabel) {
    return null;
  }

  const fromOptions = options.find((opt) => opt.label.toLowerCase() === normalizedLabel && isClusterNamingOption(opt));
  if (!fromOptions?.value) {
    return null;
  }

  const id = unwrapClusterOptionId(String(fromOptions.value));
  if (!id) {
    return null;
  }

  return { id, label: fromOptions.label };
};

/**
 * Hook for cluster label suggestions.
 *
 * Fetches:
 * 1. Similarity-based suggestions for the identity
 * 2. Label-based search results for existing clusters (debounced)
 * 3. Roster persons via the shared buildNamingOptions union
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
    namingOptions,
    collisionsByLabel,
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
    () => selectClusterSuggestions({ identityProjection, namingOptions, editableClusterId, labelInput }),
    [identityProjection, namingOptions, editableClusterId, labelInput],
  );

  const findClusterByLabel = React.useCallback(
    async (label: string, signal?: AbortSignal): Promise<{ id: string; label: string } | null> => {
      const fromOptions = resolveClusterMatchFromOptions(options, label);
      if (fromOptions) {
        return fromOptions;
      }

      return findClusterByLabelRemote(label, signal);
    },
    [options, findClusterByLabelRemote],
  );

  return {
    options,
    isLoading,
    collisionsByLabel,
    findClusterByLabel,
  };
};
