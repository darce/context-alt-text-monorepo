/**
 * Loader hook for cluster label suggestions.
 *
 * Fetches identity-based similarity suggestions, at-rest labelled clusters,
 * typed label search results, and roster persons; builds the shared naming
 * union via buildNamingOptions.
 */

import React from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  fetchIdentitiesSuggestions,
  listRecognitionClusters,
  type ClusterSummary,
  type IdentityBatchSuggestionsResponse,
} from '../../../api/recognition';
import { useRosterEntries } from '../../../hooks/useRosterHooks';
import { buildNamingOptions, type NamingOption } from './buildNamingOptions';
import {
  IDENTITY_BATCH_STALE_MS,
  PROJECTION_TOP_K,
  identityBatchIdsKey,
  isHumanLabeledTarget,
  projectIdentityWindow,
  readIdentityBatchUpdatedAt,
  readIdentityFromBatchCache,
  type ProjectedSuggestion,
} from './suggestionProjection';
import type { ClusterLabelMatch } from './useClusterMatchAction';

export interface ClusterSuggestionsLoaderOptions {
  /** Identity ID to fetch suggestions for */
  identityId: string | undefined;
  /** Whether to enable the suggestions query */
  enabled: boolean;
  /** Current editable cluster that must not be returned as a merge target */
  editableClusterId?: string | null;
  /** Current typed label for searching existing clusters */
  labelInput?: string;
  /** Debounce delay for searching (ms) */
  debounceMs?: number;
}

export interface ClusterSuggestionsLoaderResult {
  /** Projected identity-keyed suggestions (server order; isHumanLabeledTarget filtered) */
  identityProjection?: ProjectedSuggestion[];
  /** Shared naming-union options (persons ∪ human-labeled clusters) */
  namingOptions: readonly NamingOption[];
  /** Pre-dedupe collision set for the duplicate guard */
  collisionsByLabel: ReadonlyMap<string, readonly NamingOption[]>;
  /** Raw label search matches (pre-builder) */
  labelMatches?: ClusterSummary[];
  /** Whether suggestion / roster queries are loading */
  isLoading: boolean;
  /** Roster query failed — consumers degrade to cluster-only options */
  rosterError: boolean;
  /** Find cluster ID by label (case-insensitive); remote search only; BR-17 gated */
  findClusterByLabel: (label: string, signal?: AbortSignal) => Promise<ClusterLabelMatch | null>;
  /** Envelope total from the at-rest labelled-cluster page (never derived from clusters.length). */
  atRestTotal: number;
  /** Envelope truncated flag from the at-rest labelled-cluster page. */
  atRestTruncated: boolean;
  /** Filtered at-rest page size after excluding the editable cluster. */
  atRestShown: number;
}

const DEFAULT_DEBOUNCE_MS = 300;
const EMPTY_COLLISIONS: ReadonlyMap<string, readonly NamingOption[]> = new Map();
/** RES-05: at-rest labelled list is capped at 50. If response.total > 50 the dropdown is incomplete until the operator types 2+ chars (server-side search). */
const AT_REST_LABELED_LIMIT = 50;

export const useClusterSuggestionsLoader = ({
  identityId,
  enabled,
  editableClusterId,
  labelInput = '',
  debounceMs = DEFAULT_DEBOUNCE_MS,
}: ClusterSuggestionsLoaderOptions): ClusterSuggestionsLoaderResult => {
  const queryClient = useQueryClient();
  const [debouncedLabel, setDebouncedLabel] = React.useState(labelInput);
  const debouncedValue = debounceMs <= 0 ? labelInput : debouncedLabel;

  React.useEffect(() => {
    if (!enabled || debounceMs <= 0) {
      return;
    }

    const timer = window.setTimeout(() => setDebouncedLabel(labelInput), debounceMs);
    return () => window.clearTimeout(timer);
  }, [labelInput, debounceMs, enabled]);

  // BR-10: single-id key is canonical for the dropdown; seed/read from multi-id batch
  // cache so inline batch + loader share one stale window instead of dual entries.
  const { data: identityBatch, isLoading: suggestionsLoading } = useQuery<IdentityBatchSuggestionsResponse>({
    queryKey: queryKeys.suggestions.projection.identityBatch(
      identityBatchIdsKey(identityId !== undefined ? [identityId] : []),
    ),
    queryFn: () => {
      // enabled requires identityId; guard here so we never need a non-null assertion.
      if (!identityId) {
        return Promise.resolve({ matches: {} });
      }
      return fetchIdentitiesSuggestions([identityId], PROJECTION_TOP_K);
    },
    enabled: Boolean(identityId && enabled),
    staleTime: IDENTITY_BATCH_STALE_MS,
    initialData: () => (identityId ? readIdentityFromBatchCache(queryClient, identityId) : undefined),
    initialDataUpdatedAt: () => (identityId ? readIdentityBatchUpdatedAt(queryClient, identityId) : undefined),
  });

  const identityProjection = React.useMemo((): ProjectedSuggestion[] | undefined => {
    if (!identityId || identityBatch === undefined) {
      return undefined;
    }
    const rows = identityBatch.matches[identityId] ?? [];
    return projectIdentityWindow(identityId, rows);
  }, [identityId, identityBatch]);

  const { data: labelMatches, isLoading: labelMatchesLoading } = useQuery({
    queryKey: queryKeys.clusters.labelSearch(debouncedValue),
    queryFn: () =>
      listRecognitionClusters({
        limit: 20,
        offset: 0,
        labeled_only: true,
        search: debouncedValue,
      }),
    select: (response) => response.clusters.filter((cluster) => cluster.id !== editableClusterId),
    enabled: Boolean(enabled && debouncedValue.length >= 2),
    staleTime: 30000,
  });

  // Empty search is omitted: listRecognitionClusters only sets `search` when truthy.
  const { data: atRestLabeledClusters, isLoading: atRestLabeledLoading } = useQuery({
    queryKey: queryKeys.clusters.list({
      limit: AT_REST_LABELED_LIMIT,
      offset: 0,
      labeled_only: true,
    }),
    queryFn: () =>
      listRecognitionClusters({
        limit: AT_REST_LABELED_LIMIT,
        offset: 0,
        labeled_only: true,
      }),
    select: (response) => ({
      clusters: response.clusters.filter((cluster) => cluster.id !== editableClusterId),
      total: response.total,
      truncated: response.truncated,
    }),
    enabled: Boolean(enabled && debouncedValue.length < 2),
    staleTime: 30000,
  });

  const { data: rosterEntries = [], isLoading: rosterLoading, isError: rosterError } = useRosterEntries();

  const { options: namingOptions, collisionsByLabel } = React.useMemo(() => {
    // A11Y-24: roster error/empty degrade to cluster-only options.
    const roster = rosterError ? [] : rosterEntries;
    const labeledClusters =
      debouncedValue.length >= 2 ? (labelMatches ?? []) : (atRestLabeledClusters?.clusters ?? []);
    // ClusterSummary.label is runtime-nullable (BR-46); naming entries require a string.
    const namedMatches = labeledClusters.filter(
      (c): c is ClusterSummary & { label: string } => typeof c.label === 'string' && c.label !== '',
    );
    return buildNamingOptions({
      rosterEntries: roster,
      labelMatches: namedMatches,
      filter: debouncedValue,
      excludeClusterId: editableClusterId,
      // At-rest page is already capped at AT_REST_LABELED_LIMIT; do not re-slice to 20.
      limit: debouncedValue.length < 2 ? null : undefined,
    });
  }, [rosterEntries, rosterError, labelMatches, atRestLabeledClusters, debouncedValue, editableClusterId]);

  const findClusterByLabel = React.useCallback(
    async (label: string, signal?: AbortSignal): Promise<ClusterLabelMatch | null> => {
      const normalizedLabel = label.toLowerCase().trim();
      if (!normalizedLabel) {
        return null;
      }

      try {
        const results = await listRecognitionClusters({ search: label, limit: 10, labeled_only: true }, signal);
        const match = results.clusters.find(
          (cluster) =>
            cluster.id !== editableClusterId &&
            typeof cluster.label === 'string' &&
            cluster.label.toLowerCase() === normalizedLabel &&
            // BR-17: auto cluster-* labels are never merge/assign targets (FIX-2).
            isHumanLabeledTarget(cluster.label),
        );
        if (match?.id && match.label) {
          return {
            id: match.id,
            label: match.label,
            identityCount: typeof match.identity_count === 'number' ? match.identity_count : undefined,
          };
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
    [editableClusterId],
  );

  return {
    identityProjection,
    namingOptions,
    collisionsByLabel: collisionsByLabel ?? EMPTY_COLLISIONS,
    labelMatches,
    isLoading: suggestionsLoading || labelMatchesLoading || atRestLabeledLoading || (enabled && rosterLoading),
    rosterError,
    findClusterByLabel,
    atRestTotal: atRestLabeledClusters?.total ?? 0,
    atRestTruncated: atRestLabeledClusters?.truncated ?? false,
    atRestShown: atRestLabeledClusters?.clusters.length ?? 0,
  };
};
