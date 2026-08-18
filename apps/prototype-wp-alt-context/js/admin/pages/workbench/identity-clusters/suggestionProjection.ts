import type { QueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import type {
  ClusterSuggestion,
  IdentityBatchSuggestionsResponse,
  PendingMergeSuggestionsResponse,
  PendingNameSuggestionsResponse,
  PendingSuggestion,
} from '../../../api/recognition';
import type { TopUnlabeledClustersResponse } from '../../../api/recognition/types/cluster';

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
  /**
   * Identity's current/source group when the payload supplies it. Distinct from
   * `clusterId` (suggested target). Used so label-drops do not hide unfinished
   * identity→target assignment work (UXW2-2-R1-26).
   */
  sourceClusterId?: string;
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
  const sourceClusterId = row.identity_cluster_id;
  if (typeof sourceClusterId === 'string' && sourceClusterId !== '') {
    projected.sourceClusterId = sourceClusterId;
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

export const REVIEW_DROP_SCOPE = {
  ASSIGNMENT: 'assignment',
  NAME: 'name',
  MERGE: 'merge',
  TOP_UNLABELED: 'topUnlabeled',
} as const;

export type ReviewDropScope = (typeof REVIEW_DROP_SCOPE)[keyof typeof REVIEW_DROP_SCOPE];

export const REVIEW_DROP_MODE = {
  LABEL: 'label',
  MERGE: 'merge',
} as const;

export type ReviewDropMode = (typeof REVIEW_DROP_MODE)[keyof typeof REVIEW_DROP_MODE];

const LABEL_DROP_SCOPES = [
  REVIEW_DROP_SCOPE.ASSIGNMENT,
  REVIEW_DROP_SCOPE.NAME,
  REVIEW_DROP_SCOPE.TOP_UNLABELED,
] as const;

const MERGE_DROP_SCOPES = [
  REVIEW_DROP_SCOPE.ASSIGNMENT,
  REVIEW_DROP_SCOPE.NAME,
  REVIEW_DROP_SCOPE.MERGE,
  REVIEW_DROP_SCOPE.TOP_UNLABELED,
] as const;

const reviewDropTombstones = new WeakMap<QueryClient, Map<ReviewDropScope, Set<string>>>();

const tombstoneSetFor = (queryClient: QueryClient, scope: ReviewDropScope): Set<string> => {
  let byScope = reviewDropTombstones.get(queryClient);
  if (!byScope) {
    byScope = new Map();
    reviewDropTombstones.set(queryClient, byScope);
  }
  let ids = byScope.get(scope);
  if (!ids) {
    ids = new Set();
    byScope.set(scope, ids);
  }
  return ids;
};

export const tombstoneReviewGroup = (
  queryClient: QueryClient,
  clusterId: string,
  scopes: readonly ReviewDropScope[],
): void => {
  for (const scope of scopes) {
    tombstoneSetFor(queryClient, scope).add(clusterId);
  }
};

export const isReviewGroupTombstoned = (
  queryClient: QueryClient,
  scope: ReviewDropScope,
  clusterId: string,
): boolean => reviewDropTombstones.get(queryClient)?.get(scope)?.has(clusterId) === true;

/** Drop a tombstone once a post-curation refetch no longer returns that group. */
export const pruneReviewDropTombstones = (
  queryClient: QueryClient,
  scope: ReviewDropScope,
  presentIds: Iterable<string>,
): void => {
  const ids = reviewDropTombstones.get(queryClient)?.get(scope);
  if (!ids) {
    return;
  }
  const present = new Set(presentIds);
  for (const id of [...ids]) {
    if (!present.has(id)) {
      ids.delete(id);
    }
  }
};

export const assignmentRowTouchesDroppedGroup = (
  item: ProjectedSuggestion,
  clusterId: string,
  mode: ReviewDropMode,
): boolean => {
  if (mode === REVIEW_DROP_MODE.MERGE) {
    return item.clusterId === clusterId || item.sourceClusterId === clusterId;
  }
  // Label/commit: only the identity's current/source group is resolved.
  // item.clusterId is the suggested target (E21-5 3870) and stays reviewable.
  return item.sourceClusterId === clusterId;
};

export const applyAssignmentTombstones = <T extends { items: ProjectedSuggestion[] }>(
  queryClient: QueryClient,
  page: T,
): T => {
  const filtered = page.items.filter((item) => {
    if (
      item.sourceClusterId &&
      isReviewGroupTombstoned(queryClient, REVIEW_DROP_SCOPE.ASSIGNMENT, item.sourceClusterId)
    ) {
      return false;
    }
    // Merge-retired groups cannot remain as a suggested target.
    if (isReviewGroupTombstoned(queryClient, REVIEW_DROP_SCOPE.MERGE, item.clusterId)) {
      return false;
    }
    return true;
  });
  return filtered.length === page.items.length ? page : { ...page, items: filtered };
};

export const applyNameTombstones = (
  queryClient: QueryClient,
  page: PendingNameSuggestionsResponse,
): PendingNameSuggestionsResponse => {
  const filtered = page.suggestions.filter(
    (item) => !isReviewGroupTombstoned(queryClient, REVIEW_DROP_SCOPE.NAME, item.cluster_id),
  );
  return filtered.length === page.suggestions.length ? page : { ...page, suggestions: filtered };
};

export const applyMergeTombstones = (
  queryClient: QueryClient,
  page: PendingMergeSuggestionsResponse,
): PendingMergeSuggestionsResponse => {
  const filtered = page.suggestions.filter(
    (item) =>
      !isReviewGroupTombstoned(queryClient, REVIEW_DROP_SCOPE.MERGE, item.cluster_a_id) &&
      !isReviewGroupTombstoned(queryClient, REVIEW_DROP_SCOPE.MERGE, item.cluster_b_id),
  );
  return filtered.length === page.suggestions.length ? page : { ...page, suggestions: filtered };
};

export const applyTopUnlabeledTombstones = (
  queryClient: QueryClient,
  page: TopUnlabeledClustersResponse,
): TopUnlabeledClustersResponse => {
  const filtered = page.clusters.filter(
    (cluster) => !isReviewGroupTombstoned(queryClient, REVIEW_DROP_SCOPE.TOP_UNLABELED, cluster.id),
  );
  if (filtered.length === page.clusters.length) {
    return page;
  }
  const removed = page.clusters.length - filtered.length;
  return {
    ...page,
    clusters: filtered,
    total: Math.max(0, page.total - removed),
    has_clusters: filtered.length > 0,
  };
};

/**
 * UXW2-2 (B6) + R1-15/23/26: optimistically drop review rows for a resolved group
 * and tombstone the id so a remount refetch of still-uncurated rows cannot restore it.
 *
 * Label/commit (`mode: 'label'`): namePending + topUnlabeled + assignment rows whose
 * *source* group is the labelled id. Merge suggestions stay — naming does not
 * resolve a merge. Assignment rows keyed only as a suggested *target* stay.
 *
 * Merge (`mode: 'merge'`): also drops mergePending rows on either side and assignment
 * rows whose suggested target or source is the retired id.
 *
 * topUnlabeled `total` is decremented by the number of rows actually removed from
 * that same loaded envelope (never guessed).
 */
export const dropClusterFromReviewCaches = (
  queryClient: QueryClient,
  clusterId: string,
  options: { mode?: ReviewDropMode } = {},
): void => {
  const mode = options.mode ?? REVIEW_DROP_MODE.LABEL;
  const scopes = mode === REVIEW_DROP_MODE.MERGE ? MERGE_DROP_SCOPES : LABEL_DROP_SCOPES;
  tombstoneReviewGroup(queryClient, clusterId, scopes);

  queryClient.setQueryData<{ items: ProjectedSuggestion[]; dataSource?: unknown } | undefined>(
    queryKeys.suggestions.projection.reviewPage(0),
    (current) => {
      if (!current) {
        return current;
      }
      const filtered = current.items.filter((item) => !assignmentRowTouchesDroppedGroup(item, clusterId, mode));
      return filtered.length === current.items.length ? current : { ...current, items: filtered };
    },
  );

  queryClient.setQueryData<PendingNameSuggestionsResponse | undefined>(
    queryKeys.suggestions.namePending(),
    (current) => {
      if (!current) {
        return current;
      }
      const filtered = current.suggestions.filter((item) => item.cluster_id !== clusterId);
      return filtered.length === current.suggestions.length ? current : { ...current, suggestions: filtered };
    },
  );

  if (mode === REVIEW_DROP_MODE.MERGE) {
    queryClient.setQueryData<PendingMergeSuggestionsResponse | undefined>(
      queryKeys.suggestions.mergePending(),
      (current) => {
        if (!current) {
          return current;
        }
        const filtered = current.suggestions.filter(
          (item) => item.cluster_a_id !== clusterId && item.cluster_b_id !== clusterId,
        );
        return filtered.length === current.suggestions.length ? current : { ...current, suggestions: filtered };
      },
    );
  }

  queryClient.setQueriesData<TopUnlabeledClustersResponse | undefined>(
    { queryKey: [...queryKeys.clusters.all, 'top-unlabeled'] },
    (current) => {
      if (!current) {
        return current;
      }
      const filtered = current.clusters.filter((cluster) => cluster.id !== clusterId);
      if (filtered.length === current.clusters.length) {
        return current;
      }
      const removed = current.clusters.length - filtered.length;
      return {
        ...current,
        clusters: filtered,
        total: Math.max(0, current.total - removed),
        has_clusters: filtered.length > 0,
      };
    },
  );
};

/** S2-02: mark review feeds stale without refetching still-uncurated rows. */
export const invalidateReviewCachesWithoutRefetch = (queryClient: QueryClient): void => {
  void queryClient.invalidateQueries({
    queryKey: queryKeys.suggestions.projection.all,
    refetchType: 'none',
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.suggestions.mergePending(),
    refetchType: 'none',
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.suggestions.namePending(),
    refetchType: 'none',
  });
  void queryClient.invalidateQueries({
    queryKey: queryKeys.clusters.all,
    refetchType: 'none',
  });
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
