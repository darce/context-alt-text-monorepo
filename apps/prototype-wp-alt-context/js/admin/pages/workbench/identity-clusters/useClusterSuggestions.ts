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
  NAMING_GROUP_ALL_LABELS,
  NAMING_GROUP_SUGGESTED,
  type NamingOption,
  unwrapClusterOptionId,
  namingOptionValue,
} from './buildNamingOptions';
import { useClusterSuggestionsLoader, type ClusterSuggestionsLoaderOptions } from './useClusterSuggestionsLoader';
import type { ProjectedSuggestion } from './suggestionProjection';
import type { ClusterLabelMatch } from './useClusterMatchAction';

type UseClusterSuggestionsOptions = ClusterSuggestionsLoaderOptions;

interface UseClusterSuggestionsReturn {
  /** Formatted options for Combobox / edit form */
  options: ComboboxOption[];
  /** Whether suggestions are loading */
  isLoading: boolean;
  /** Pre-dedupe collisions for the duplicate guard */
  collisionsByLabel: ReadonlyMap<string, readonly NamingOption[]>;
  /** Find cluster ID by label (case-insensitive); cluster-source options only (PR-16) */
  findClusterByLabel: (label: string, signal?: AbortSignal) => Promise<ClusterLabelMatch | null>;
  /** Envelope total from the at-rest labelled-cluster page. */
  atRestTotal: number;
  /** Envelope truncated flag from the at-rest labelled-cluster page. */
  atRestTruncated: boolean;
  /** Filtered at-rest page size after excluding the editable cluster. */
  atRestShown: number;
  /** True while the debounced input is below the typed-search minimum. */
  isAtRestMode: boolean;
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
  /** Cluster labels only — persons never suppress a same-named cluster (FIX-5). */
  const seenClusterLabels = new Set<string>();
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
    if (seenClusterLabels.has(key)) {
      return;
    }

    seenClusterLabels.add(key);
    result.push({
      value: namingOptionValue('cluster', projected.clusterId),
      label: normalizedLabel,
      group: NAMING_GROUP_SUGGESTED,
      source: 'cluster',
      similarity: projected.similarity,
      identityCount: projected.identityCount,
      suggestion_id: projected.suggestionId,
    });
  });

  // 2. Union naming options: person rows always render; cluster rows dedupe vs Suggested (FIX-5).
  (namingOptions ?? []).forEach((option) => {
    const key = option.label.toLowerCase();
    if (searchLower && !key.includes(searchLower)) {
      return;
    }

    if (option.source === 'person') {
      result.push({
        value: option.value,
        label: option.label,
        group: NAMING_GROUP_ALL_LABELS,
        source: option.source,
        identityCount: option.identityCount,
      });
      return;
    }

    if (seenClusterLabels.has(key)) {
      return;
    }
    seenClusterLabels.add(key);
    result.push({
      value: option.value,
      label: option.label,
      group: NAMING_GROUP_ALL_LABELS,
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
): ClusterLabelMatch | null => {
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

  const identityCount = typeof fromOptions.identityCount === 'number' ? fromOptions.identityCount : undefined;
  // L1V-01: free-type Save uses this resolver; map option.suggestion_id so accept-by-id
  // threads the same way as the click/confirm path (BR-16 residual).
  const suggestionId =
    typeof fromOptions.suggestion_id === 'string' && fromOptions.suggestion_id.length > 0
      ? fromOptions.suggestion_id
      : undefined;

  return { id, label: fromOptions.label, identityCount, suggestionId };
};

/**
 * Hook for cluster label suggestions.
 *
 * Fetches:
 * 1. Similarity-based suggestions for the identity
 * 2. At-rest labelled clusters (empty input) plus typed label search (2+ chars)
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
    atRestTotal,
    atRestTruncated,
    atRestShown,
    isAtRestMode,
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
    async (label: string, signal?: AbortSignal): Promise<ClusterLabelMatch | null> => {
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
    atRestTotal,
    atRestTruncated,
    atRestShown,
    isAtRestMode,
  };
};
