/**
 * Loader hook for cluster label suggestions.
 *
 * Fetches identity-based similarity suggestions, at-rest labelled clusters,
 * typed label search results, and roster persons; builds the shared naming
 * union via buildNamingOptions.
 */

import React from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import { queryKeys } from '../../../api/queryKeys';
import {
  fetchIdentitiesSuggestions,
  listRecognitionClusters,
  type ClusterSummary,
  type IdentityBatchSuggestionsResponse,
} from '../../../api/recognition';
import {
  fetchClusterRosterCandidates,
  ROSTER_CANDIDATES_TOP_K,
  type RosterCandidate,
  type RosterCandidatesResponse,
} from '../../../api/recognition/rosterCandidatesApi';
import { useRosterEntries } from '../../../hooks/useRosterHooks';
import {
  buildNamingOptions,
  NAMING_GROUP_SUGGESTED,
  namingOptionValue,
  type NamingOption,
  type RosterNamingEntry,
} from './buildNamingOptions';
import { lookupClusterByLabel, unwrapClusterLabelLookup } from './clusterLabelLookup';
import {
  IDENTITY_BATCH_STALE_MS,
  PROJECTION_TOP_K,
  identityBatchIdsKey,
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
  /**
   * Find cluster ID by label (case-insensitive); remote search only; BR-17 gated.
   * `null` means the lookup ran and found nothing. A lookup that could not run throws
   * `ClusterLabelLookupError` so write callers fail CLOSED (FEBT1G-H-04). Callers that
   * want the outcome as a value import `lookupClusterByLabel` from `clusterLabelLookup`.
   */
  findClusterByLabel: (label: string, signal?: AbortSignal) => Promise<ClusterLabelMatch | null>;
  /** Envelope total from the at-rest labelled-cluster page (never derived from clusters.length). */
  atRestTotal: number;
  /** Envelope truncated flag from the at-rest labelled-cluster page. */
  atRestTruncated: boolean;
  /** True while the debounced input is below the typed-search minimum. */
  isAtRestMode: boolean;
  /** Closest roster people for an unnamed card: person-source, committable, one row per person. */
  rosterCandidateOptions?: ComboboxOption[];
  /** The identity batch or the closest-roster read failed. Never reported as an empty list. */
  isError?: boolean;
  /** Re-runs only the failed read(s). Optional so existing loader mocks stay type-valid. */
  retry?: () => void;
}

const DEFAULT_DEBOUNCE_MS = 300;
const EMPTY_COLLISIONS: ReadonlyMap<string, readonly NamingOption[]> = new Map();
/** Typed label search is disabled until the debounced input reaches this length. */
export const ACX_LABEL_SEARCH_MIN_CHARS = 2;
/** RES-05: at-rest labelled list is capped at 50. If response.total > 50 the dropdown is incomplete until the operator types 2+ chars (server-side search). */
const AT_REST_LABELED_LIMIT = 50;

/** Closest-roster rows offered on one unnamed card (the backend window is the same size). */
const ROSTER_CANDIDATE_OPTION_LIMIT = ROSTER_CANDIDATES_TOP_K;

/**
 * Closest roster people as person-source naming options. Only mapped rows (roster_entry_id
 * present) are committable; unmapped rows are dropped. One row per roster person keeps the
 * strongest similarity at its first payload position, so backend order is never re-sorted.
 * The canonical name is the roster entry linked by ID, falling back to the payload name.
 */
export const buildRosterCandidateOptions = (
  candidates: readonly RosterCandidate[],
  rosterEntries: readonly RosterNamingEntry[],
): ComboboxOption[] => {
  const canonicalNameById = new Map<number, string>();
  for (const entry of rosterEntries) {
    const entryId = Number(entry.id);
    const name = entry.name?.trim() ?? '';
    if (Number.isFinite(entryId) && name) {
      canonicalNameById.set(entryId, name);
    }
  }

  const strongestByPerson = new Map<number, RosterCandidate>();
  for (const candidate of candidates) {
    const rosterEntryId = candidate.roster_entry_id;
    if (typeof rosterEntryId !== 'number' || !Number.isFinite(rosterEntryId)) {
      continue;
    }
    const current = strongestByPerson.get(rosterEntryId);
    if (!current || candidate.similarity > current.similarity) {
      strongestByPerson.set(rosterEntryId, candidate);
    }
  }

  return Array.from(strongestByPerson.entries())
    .slice(0, ROSTER_CANDIDATE_OPTION_LIMIT)
    .flatMap(([rosterEntryId, candidate]): ComboboxOption[] => {
      const label = canonicalNameById.get(rosterEntryId) ?? candidate.name.trim();
      if (!label) {
        return [];
      }
      return [
        {
          value: namingOptionValue('person', rosterEntryId),
          label,
          group: NAMING_GROUP_SUGGESTED,
          source: 'person',
          similarity: candidate.similarity,
          band: candidate.band,
          cluster_id: candidate.cluster_id,
          roster_entry_id: rosterEntryId,
        },
      ];
    });
};

export const useClusterSuggestionsLoader = ({
  identityId,
  enabled,
  editableClusterId,
  labelInput = '',
  debounceMs = DEFAULT_DEBOUNCE_MS,
}: ClusterSuggestionsLoaderOptions): ClusterSuggestionsLoaderResult => {
  const queryClient = useQueryClient();
  const canQuerySuggestions = Boolean(identityId && enabled);
  const [debouncedLabel, setDebouncedLabel] = React.useState(labelInput);
  const debouncedValue = debounceMs <= 0 ? labelInput : debouncedLabel;
  const isAtRestMode = debouncedValue.length < ACX_LABEL_SEARCH_MIN_CHARS;

  React.useEffect(() => {
    if (!enabled || debounceMs <= 0) {
      return;
    }

    const timer = window.setTimeout(() => setDebouncedLabel(labelInput), debounceMs);
    return () => window.clearTimeout(timer);
  }, [labelInput, debounceMs, enabled]);

  // BR-10: single-id key is canonical for the dropdown; seed/read from multi-id batch
  // cache so inline batch + loader share one stale window instead of dual entries.
  const {
    data: identityBatch,
    isLoading: suggestionsLoading,
    isError: suggestionsError,
    refetch: refetchSuggestions,
  } = useQuery<IdentityBatchSuggestionsResponse>({
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
    enabled: canQuerySuggestions,
    staleTime: IDENTITY_BATCH_STALE_MS,
    initialData: () => (identityId ? readIdentityFromBatchCache(queryClient, identityId) : undefined),
    initialDataUpdatedAt: () => (identityId ? readIdentityBatchUpdatedAt(queryClient, identityId) : undefined),
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
    select: (response) => response.clusters.filter((cluster) => cluster.id !== editableClusterId),
    enabled: Boolean(enabled && !isAtRestMode),
    placeholderData: keepPreviousData,
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
    enabled: Boolean(enabled && isAtRestMode),
    placeholderData: keepPreviousData,
    staleTime: 30000,
  });

  // Canonical cluster name: a current label replaces the cached batch label only when the same
  // cluster ID is labelled now. The join is by cluster ID, never by display name.
  const currentLabelByClusterId = React.useMemo((): ReadonlyMap<string, string> => {
    const labels = new Map<string, string>();
    for (const cluster of [...(atRestLabeledClusters?.clusters ?? []), ...(labelMatches ?? [])]) {
      const label = typeof cluster.label === 'string' ? cluster.label.trim() : '';
      if (label) {
        labels.set(cluster.id, label);
      }
    }
    return labels;
  }, [atRestLabeledClusters, labelMatches]);

  const identityProjection = React.useMemo((): ProjectedSuggestion[] | undefined => {
    if (!identityId || identityBatch === undefined) {
      return undefined;
    }
    const rows = (identityBatch.matches[identityId] ?? []).map((row) => {
      const currentLabel = currentLabelByClusterId.get(row.cluster_id);
      return currentLabel ? { ...row, label: currentLabel } : row;
    });
    return projectIdentityWindow(identityId, rows);
  }, [identityId, identityBatch, currentLabelByClusterId]);

  // Closest roster people for an unnamed card (c82 FIR). Lazy: only when expanded, the editable
  // cluster is valid, the identity batch has resolved, and no eligible pending row exists.
  const rosterClusterId = editableClusterId?.trim() ?? '';
  const hasEligiblePending = (identityProjection?.length ?? 0) > 0;
  const canQueryRosterCandidates = Boolean(
    canQuerySuggestions && identityBatch !== undefined && rosterClusterId && !hasEligiblePending,
  );
  const {
    data: rosterCandidatesResponse,
    isError: rosterCandidatesError,
    refetch: refetchRosterCandidates,
  } = useQuery<RosterCandidatesResponse>({
    queryKey: queryKeys.clusters.rosterCandidates(rosterClusterId, ROSTER_CANDIDATES_TOP_K),
    queryFn: () => fetchClusterRosterCandidates(rosterClusterId, ROSTER_CANDIDATES_TOP_K),
    enabled: canQueryRosterCandidates,
    staleTime: 30000,
  });

  const { data: rosterEntries = [], isLoading: rosterLoading, isError: rosterError } = useRosterEntries();

  const rosterCandidateOptions = React.useMemo(
    () => canQueryRosterCandidates
      ? buildRosterCandidateOptions(rosterCandidatesResponse?.candidates ?? [], rosterEntries)
      : [],
    [canQueryRosterCandidates, rosterCandidatesResponse, rosterEntries],
  );

  const { options: namingOptions, collisionsByLabel } = React.useMemo(() => {
    // A11Y-24: roster error/empty degrade to cluster-only options.
    const roster = rosterError ? [] : rosterEntries;
    const labeledClusters = isAtRestMode ? (atRestLabeledClusters?.clusters ?? []) : (labelMatches ?? atRestLabeledClusters?.clusters ?? []);
    // ClusterSummary.label is runtime-nullable (BR-46); naming entries require a string.
    const namedMatches = labeledClusters.filter(
      (c): c is ClusterSummary & { label: string } => typeof c.label === 'string' && c.label !== '',
    );
    return buildNamingOptions({
      rosterEntries: roster,
      labelMatches: namedMatches,
      filter: debouncedValue,
      excludeClusterId: editableClusterId,
    });
  }, [rosterEntries, rosterError, labelMatches, atRestLabeledClusters, debouncedValue, editableClusterId, isAtRestMode]);

  const findClusterByLabel = React.useCallback(
    async (label: string, signal?: AbortSignal): Promise<ClusterLabelMatch | null> =>
      unwrapClusterLabelLookup(await lookupClusterByLabel({ label, editableClusterId, signal })),
    [editableClusterId],
  );

  // Retry only the read(s) that failed; a read that succeeded is not re-fetched here.
  const retry = React.useCallback(() => {
    if (canQuerySuggestions && suggestionsError) {
      void refetchSuggestions();
    }
    if (canQueryRosterCandidates && rosterCandidatesError) {
      void refetchRosterCandidates();
    }
  }, [canQuerySuggestions, canQueryRosterCandidates, suggestionsError, rosterCandidatesError, refetchSuggestions, refetchRosterCandidates]);

  return {
    identityProjection,
    namingOptions,
    collisionsByLabel: collisionsByLabel ?? EMPTY_COLLISIONS,
    labelMatches,
    isLoading:
      suggestionsLoading ||
      labelMatchesLoading ||
      atRestLabeledLoading ||
      (enabled && rosterLoading),
    rosterError,
    rosterCandidateOptions,
    isError: (canQuerySuggestions && suggestionsError) || (canQueryRosterCandidates && rosterCandidatesError),
    retry,
    findClusterByLabel,
    atRestTotal: atRestLabeledClusters?.total ?? 0,
    atRestTruncated: atRestLabeledClusters?.truncated ?? false,
    isAtRestMode,
  };
};
