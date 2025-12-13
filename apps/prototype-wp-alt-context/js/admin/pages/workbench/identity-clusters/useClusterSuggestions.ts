/**
 * Hook for fetching and formatting cluster label suggestions.
 *
 * Combines identity-based similarity suggestions with existing labels.
 */

import React from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import {
  fetchIdentitySuggestions,
  listRecognitionClusters,
  type ClusterSummary,
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
  /** All existing labels (for merge detection) */
  existingLabels: string[];
  /** Fetch labels if not cached */
  ensureLabels: () => Promise<string[]>;
  /** Find cluster ID by label (case-insensitive) */
  findClusterIdByLabel: (label: string) => Promise<string | null>;
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
  const queryClient = useQueryClient();

  // Fetch existing clusters (cached for 30s) - includes IDs for proper assignment
  const { data: existingClusters } = useQuery({
    queryKey: ['clusters'],
    queryFn: () => listRecognitionClusters({ limit: 500 }),
    staleTime: 30000,
  });

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

    // Add existing clusters with their IDs (only user-labeled, not auto-labeled)
    (existingClusters ?? []).forEach((cluster: ClusterSummary) => {
      const label = cluster.label;
      // Skip clusters without labels or with auto-generated labels
      if (!label || cluster.is_auto_label) {
        return;
      }

      const key = label.toLowerCase();
      if (seen.has(key)) {
        return;
      }

      seen.add(key);
      result.push({
        value: cluster.id,
        label,
        group: 'All Labels',
        identityCount: cluster.identity_count,
      });
    });

    return result;
  }, [existingClusters, identitySuggestions]);

  // Compute existing labels from clusters (only user-labeled)
  const existingLabels = React.useMemo(
    () =>
      (existingClusters ?? [])
        .filter((c: ClusterSummary) => c.label && !c.is_auto_label)
        .map((c: ClusterSummary) => c.label),
    [existingClusters],
  );

  // Ensure labels are fetched (for merge detection) - only user-labeled
  const ensureLabels = React.useCallback(async (): Promise<string[]> => {
    if (existingClusters) {
      return existingClusters
        .filter((c: ClusterSummary) => c.label && !c.is_auto_label)
        .map((c: ClusterSummary) => c.label);
    }

    try {
      const clusters = await queryClient.fetchQuery({
        queryKey: ['clusters'],
        queryFn: () => listRecognitionClusters({ limit: 500 }),
      });
      return clusters.filter((c: ClusterSummary) => c.label && !c.is_auto_label).map((c: ClusterSummary) => c.label);
    } catch {
      return [];
    }
  }, [existingClusters, queryClient]);

  // Find cluster ID by label (case-insensitive) - checks options first, then fetches if needed
  const findClusterIdByLabel = React.useCallback(
    async (label: string): Promise<string | null> => {
      const normalizedLabel = label.toLowerCase();

      // First check the options array (includes suggestions and existing clusters)
      const fromOptions = options.find((opt) => opt.label.toLowerCase() === normalizedLabel);
      if (fromOptions?.value) {
        return fromOptions.value;
      }

      // If not in options, fetch clusters and search
      try {
        const clusters = await queryClient.fetchQuery({
          queryKey: ['clusters'],
          queryFn: () => listRecognitionClusters({ limit: 500 }),
        });
        const match = clusters.find((c: ClusterSummary) => c.label?.toLowerCase() === normalizedLabel);
        return match?.id ?? null;
      } catch {
        return null;
      }
    },
    [options, queryClient],
  );

  return {
    options,
    isLoading: suggestionsLoading,
    existingLabels: existingLabels ?? [],
    ensureLabels,
    findClusterIdByLabel,
  };
};
