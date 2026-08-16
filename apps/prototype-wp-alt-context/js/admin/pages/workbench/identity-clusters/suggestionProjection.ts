import type { QueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import type {
  ClusterSuggestion,
  IdentityBatchSuggestionsResponse,
  PendingSuggestion,
} from '../../../api/recognition';

/** Shared fetch depth for all identity-keyed reads (fetch K, filter client-side). */
export const PROJECTION_TOP_K = 5;

/**
 * Shared staleTime for every identityBatch query (inline multi-id + single-id loader).
 * BR-10: divergent TTLs let two cache entries for the same identity disagree mid-window.
 */
export const IDENTITY_BATCH_STALE_MS = 60_000;

/** Canonical auto-label prefix; human-format labels must not start with this. */
export const AUTO_LABEL_PREFIX = 'cluster-' as const;

/**
 * Two machine-label shapes (reject if either matches the full trimmed string):
 * - HEX: PHP-parity long hex (`{8,}`) any case — trait-detects-system-defined-labels.
 * - MACHINE: lowercase-only `cluster[-_][a-z0-9_-]+` — short/non-hex auto ids.
 * Any uppercase letter in a short suffix fails MACHINE and (if <8 hex) HEX, so
 * names like `Cluster-Dad` / `Cluster-ace` stay human. Display-honesty only —
 * survivor ranking uses a separate predicate.
 */
const AUTO_LABEL_HEX_RE = /^cluster[-_][0-9a-f-]{8,}$/i;
const AUTO_LABEL_MACHINE_RE = /^cluster[-_][a-z0-9_-]+$/;

/**
 * Canonical resolution values for assignment suggestions.
 * Identity-keyed legs treat only pending/undefined as active; review may surface resolved rows.
 */
export const SUGGESTION_RESOLUTION = {
  PENDING: 'pending',
  ACCEPTED: 'accepted',
  REJECTED: 'rejected',
} as const;

export type SuggestionResolution = (typeof SUGGESTION_RESOLUTION)[keyof typeof SUGGESTION_RESOLUTION];

/**
 * Review-leg enrichment only — media URLs / bboxes / suggested_label*.
 * Field types mirror PendingSuggestion honestly (rg-015: no fabricated defaults).
 */
export interface ProjectedSuggestionEnrichment {
  identityMediaId?: PendingSuggestion['identity_media_id'];
  identityMediaUrl?: PendingSuggestion['identity_media_url'];
  identityAttachmentUrl?: PendingSuggestion['identity_attachment_url'];
  identityThumbUrl?: PendingSuggestion['identity_thumb_url'];
  identityBbox?: PendingSuggestion['identity_bbox'];
  representativeMediaId?: PendingSuggestion['representative_media_id'];
  representativeMediaUrl?: PendingSuggestion['representative_media_url'];
  representativeAttachmentUrl?: PendingSuggestion['representative_attachment_url'];
  representativeThumbUrl?: PendingSuggestion['representative_thumb_url'];
  representativeBbox?: PendingSuggestion['representative_bbox'];
  suggestedLabel?: PendingSuggestion['suggested_label'];
  suggestedLabelSource?: PendingSuggestion['suggested_label_source'];
  suggestedLabelConfidence?: PendingSuggestion['suggested_label_confidence'];
}

/**
 * Unified projected suggestion shared by identity-keyed and review surfaces.
 *
 * - `suggestionId` optional: ClusterSuggestion.suggestion_id is optional; PendingSuggestion.id is required.
 * - `label` optional/nullable: PendingSuggestion.cluster_label is `string | null | undefined`;
 *   identity matches always supply a string label.
 * - `identityCount` optional: always present on identity matches; review rows may omit/null it.
 * - `createdAt` optional: identity payload has none; pending rows may include created_at.
 * - `resolution` optional: review rows carry it; without it the review UI cannot tell a
 *   stale-accepted repair row from a pending one (double-accept risk). Identity payload has none.
 * - `enrichment` review-leg only.
 */
export interface ProjectedSuggestion {
  suggestionId?: string;
  identityId: string;
  clusterId: string;
  label?: string | null;
  similarity: number;
  identityCount?: number;
  createdAt?: string;
  resolution?: PendingSuggestion['resolution'];
  enrichment?: ProjectedSuggestionEnrichment;
}

/**
 * Single eligibility predicate for every leg: truthy trimmed label ∧ not machine-shaped.
 * Rejects when the trimmed label matches either AUTO_LABEL_HEX_RE (PHP-parity ≥8 hex,
 * any case) or AUTO_LABEL_MACHINE_RE (all-lowercase machine forms). Short hex-word
 * names with any uppercase (`Cluster-Dad`) pass; `CLUSTER_HQ` / `Cluster Nine` pass.
 */
export const isHumanLabeledTarget = (label: string | null | undefined): boolean => {
  const trimmed = label?.trim();
  if (!trimmed) {
    return false;
  }
  return !(AUTO_LABEL_HEX_RE.test(trimmed) || AUTO_LABEL_MACHINE_RE.test(trimmed));
};

/**
 * Identity-keyed surfaces exclude resolved rows; undefined or `pending` remain eligible.
 * Review may still show accepted/rejected rows as repair affordances.
 */
export const isIdentityLegResolution = (resolution: string | undefined): boolean =>
  resolution === undefined || resolution === SUGGESTION_RESOLUTION.PENDING;

/**
 * Review-leg presentation comparator only: similarity desc, then createdAt desc.
 * Missing createdAt sorts last under the desc tie-break (treated as older than any ISO timestamp).
 * Identity-keyed legs must not call this — they preserve server arrival order.
 */
export const compareSuggestions = (a: ProjectedSuggestion, b: ProjectedSuggestion): number => {
  if (b.similarity !== a.similarity) {
    return b.similarity - a.similarity;
  }
  const aCreated = a.createdAt ?? '';
  const bCreated = b.createdAt ?? '';
  if (aCreated === bCreated) {
    return 0;
  }
  return aCreated < bCreated ? 1 : -1;
};

/**
 * TOTAL adapter from an identity-keyed ClusterSuggestion match.
 * Omits suggestionId when the source lacks suggestion_id (rg-015).
 * Does not attach enrichment or createdAt (not on the identity payload).
 */
export const fromIdentityMatch = (identityId: string, match: ClusterSuggestion): ProjectedSuggestion => {
  const projected: ProjectedSuggestion = {
    identityId,
    clusterId: match.cluster_id,
    label: match.label,
    similarity: match.similarity,
    identityCount: match.identity_count,
  };
  if (match.suggestion_id !== undefined) {
    projected.suggestionId = match.suggestion_id;
  }
  return projected;
};

const ENRICHMENT_SOURCE_FIELDS = [
  ['identityMediaId', 'identity_media_id'],
  ['identityMediaUrl', 'identity_media_url'],
  ['identityAttachmentUrl', 'identity_attachment_url'],
  ['identityThumbUrl', 'identity_thumb_url'],
  ['identityBbox', 'identity_bbox'],
  ['representativeMediaId', 'representative_media_id'],
  ['representativeMediaUrl', 'representative_media_url'],
  ['representativeAttachmentUrl', 'representative_attachment_url'],
  ['representativeThumbUrl', 'representative_thumb_url'],
  ['representativeBbox', 'representative_bbox'],
  ['suggestedLabel', 'suggested_label'],
  ['suggestedLabelSource', 'suggested_label_source'],
  ['suggestedLabelConfidence', 'suggested_label_confidence'],
] as const satisfies readonly (readonly [keyof ProjectedSuggestionEnrichment, keyof PendingSuggestion])[];

/**
 * Honest absence (rg-015): only fields the payload actually carries become keys;
 * `enrichment` itself is omitted when the row has none, so `if (p.enrichment)` means
 * "the payload had enrichment data", never "the adapter ran".
 */
const buildEnrichment = (row: PendingSuggestion): ProjectedSuggestionEnrichment | undefined => {
  let enrichment: ProjectedSuggestionEnrichment | undefined;
  for (const [projectedField, sourceField] of ENRICHMENT_SOURCE_FIELDS) {
    const value = row[sourceField];
    if (value !== undefined) {
      enrichment ??= {};
      (enrichment as Record<string, unknown>)[projectedField] = value;
    }
  }
  return enrichment;
};

/**
 * TOTAL adapter from a pending-list PendingSuggestion row.
 * Passes through null labels and enrichment fields without inventing defaults (rg-015).
 * identityCount is set only when cluster_identity_count is a finite number (null/undefined/NaN omitted).
 */
export const fromPendingRow = (row: PendingSuggestion): ProjectedSuggestion => {
  const projected: ProjectedSuggestion = {
    suggestionId: row.id,
    identityId: row.identity_id,
    clusterId: row.suggested_cluster_id,
    label: row.cluster_label,
    similarity: row.representative_similarity,
  };
  const identityCount = row.cluster_identity_count;
  if (typeof identityCount === 'number' && Number.isFinite(identityCount)) {
    projected.identityCount = identityCount;
  }
  if (row.created_at !== undefined) {
    projected.createdAt = row.created_at;
  }
  if (row.resolution !== undefined) {
    projected.resolution = row.resolution;
  }
  const enrichment = buildEnrichment(row);
  if (enrichment !== undefined) {
    projected.enrichment = enrichment;
  }
  return projected;
};

/**
 * Identity-keyed projection over a server-ordered match list:
 * take PROJECTION_TOP_K, adapt, filter human-labeled; preserve arrival order (no re-sort).
 */
export const projectIdentityWindow = (
  identityId: string,
  matches: readonly ClusterSuggestion[],
): ProjectedSuggestion[] =>
  matches
    .slice(0, PROJECTION_TOP_K)
    .map((match) => fromIdentityMatch(identityId, match))
    .filter((projected) => isHumanLabeledTarget(projected.label));

/**
 * Identity-leg filter over pending rows: drop non-pending resolutions, adapt, human-label filter.
 * Arrival order preserved (no client re-sort).
 */
export const projectIdentityLegFromPending = (rows: readonly PendingSuggestion[]): ProjectedSuggestion[] =>
  rows
    .filter((row) => isIdentityLegResolution(row.resolution))
    .map(fromPendingRow)
    .filter((projected) => isHumanLabeledTarget(projected.label));

/**
 * Review-leg projection: adapt all rows, apply human-label predicate, sort via compareSuggestions.
 * Resolved (e.g. accepted) rows remain if human-labeled — review-only repair affordance.
 */
export const projectReviewQueue = (rows: readonly PendingSuggestion[]): ProjectedSuggestion[] =>
  rows
    .map(fromPendingRow)
    .filter((projected) => isHumanLabeledTarget(projected.label))
    .slice()
    .sort(compareSuggestions);

/**
 * Canonical serializer for `queryKeys.suggestions.projection.identityBatch`.
 * Every consumer must build idsKey through this (dedupe + sort + ','-join) or the
 * co-shipped inline/dropdown legs cache under divergent keys and double-fetch.
 */
export const identityBatchIdsKey = (identityIds: readonly string[]): string =>
  [...new Set(identityIds)].sort().join(',');

/**
 * Seed per-identity projection entries from a multi-id batch response (BR-10).
 * Single-id loaders (`useClusterSuggestionsLoader`) read these keys so one
 * invalidation/stale window covers inline batch + dropdown without dual fetches.
 *
 * Only seeds ids the server actually returned in `matches` (L1R-04 / rg-015).
 * Omitted keys are not written as authoritative empty results.
 */
export const seedIdentityBatchSingles = (
  queryClient: QueryClient,
  response: IdentityBatchSuggestionsResponse,
  identityIds: readonly string[],
): void => {
  for (const id of identityIds) {
    if (!Object.prototype.hasOwnProperty.call(response.matches, id)) {
      continue;
    }
    const singleResponse: IdentityBatchSuggestionsResponse = {
      matches: { [id]: response.matches[id] ?? [] },
    };
    queryClient.setQueryData(
      queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey([id])),
      singleResponse,
    );
  }
};

/**
 * Read a single identity's matches + the matching entry's dataUpdatedAt (BR-10 / L1R-03).
 * Prefers the canonical single-id key, then the first multi-id batch that includes the id.
 * Data and timestamp always come from the same cache entry so stale data cannot be
 * stamped with a fresher sibling batch's updatedAt.
 */
export const readIdentityBatchCacheEntry = (
  queryClient: QueryClient,
  identityId: string,
): { data: IdentityBatchSuggestionsResponse; dataUpdatedAt: number | undefined } | undefined => {
  const singleKey = queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey([identityId]));
  const single = queryClient.getQueryData<IdentityBatchSuggestionsResponse>(singleKey);
  if (single?.matches && Object.prototype.hasOwnProperty.call(single.matches, identityId)) {
    return {
      data: { matches: { [identityId]: single.matches[identityId] ?? [] } },
      dataUpdatedAt: queryClient.getQueryState(singleKey)?.dataUpdatedAt,
    };
  }

  const batches = queryClient.getQueriesData<IdentityBatchSuggestionsResponse>({
    queryKey: [...queryKeys.suggestions.projection.all, 'identity-batch'],
  });
  for (const [key, data] of batches) {
    if (!data?.matches || !Object.prototype.hasOwnProperty.call(data.matches, identityId)) {
      continue;
    }
    return {
      data: { matches: { [identityId]: data.matches[identityId] ?? [] } },
      dataUpdatedAt: queryClient.getQueryState(key)?.dataUpdatedAt,
    };
  }
  return undefined;
};

export const readIdentityFromBatchCache = (
  queryClient: QueryClient,
  identityId: string,
): IdentityBatchSuggestionsResponse | undefined => readIdentityBatchCacheEntry(queryClient, identityId)?.data;

export const readIdentityBatchUpdatedAt = (queryClient: QueryClient, identityId: string): number | undefined =>
  readIdentityBatchCacheEntry(queryClient, identityId)?.dataUpdatedAt;

export const invalidateSuggestionProjection = (queryClient: QueryClient): Promise<void> =>
  queryClient.invalidateQueries({
    queryKey: queryKeys.suggestions.projection.all,
  });

/**
 * Optimistically drop an accepted/rejected assignment suggestion from the review-page cache
 * so the pending list updates before projection invalidation refetches (L1V-03).
 * Shape matches SuggestionReviewPage without importing the query module (cycle-safe).
 */
export const removePendingSuggestionFromCache = (queryClient: QueryClient, suggestionId: string): void => {
  const reviewPageKey = queryKeys.suggestions.projection.reviewPage(0);
  queryClient.setQueryData<{ items: ProjectedSuggestion[]; dataSource?: unknown } | undefined>(
    reviewPageKey,
    (current) => {
      if (!current) {
        return current;
      }
      const filtered = current.items.filter((item) => item.suggestionId !== suggestionId);
      if (filtered.length === current.items.length) {
        return current;
      }
      // COR-3 (rg-015): no envelope total to decrement; loaded count follows items.
      return { ...current, items: filtered };
    },
  );
};

/**
 * Invalidation event map (D4) as data for UXP-5 wiring.
 * `keptCrossFamilyTargets` is the verified live inventory (2026-07-17 code audit), not a
 * copy of the plan table — 0b-4/UXP-5 must preserve these calls; tests assert presence,
 * never forbid extras. Divergence from the plan's D4 table: dismiss sites invalidate
 * clusters.topUnlabeled (card) / clusters.all (roster bulk), not mergePending; accept,
 * label, merge, and scan also touch media.identities (UXP-3 finding, recorded in handoff).
 */
export const SUGGESTION_PROJECTION_INVALIDATION_EVENTS = {
  suggestionAccept: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['clusters.all', 'media.identities'] as const,
  },
  /**
   * Reject changes no media/identity assignment, so it deliberately does NOT
   * invalidate media.identities — split from accept so the map stays honest.
   */
  suggestionReject: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['clusters.all'] as const,
  },
  bulkAccept: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['mergePending', 'namePending', 'clusters.all'] as const,
  },
  clusterLabelSetClear: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['mergePending', 'clusters.all', 'clusters.labels', 'media.identities'] as const,
  },
  clusterMerge: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['mergePending', 'clusters.all', 'clusters.labels', 'media.identities'] as const,
  },
  clusterDismiss: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['clusters.topUnlabeled', 'clusters.all'] as const,
  },
  scanRecomputeCompletion: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['mergePending', 'namePending', 'media.identities', 'clusters.topUnlabeled'] as const,
  },
  syncTrigger: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: [] as const,
    viaSuggestionsAllRoot: true,
  },
} as const;

export type SuggestionProjectionInvalidationEvent = keyof typeof SUGGESTION_PROJECTION_INVALIDATION_EVENTS;
