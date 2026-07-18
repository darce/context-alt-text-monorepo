import type { QueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import type { ClusterSuggestion, PendingSuggestion } from '../../../api/recognition';

/** Shared fetch depth for all identity-keyed reads (fetch K, filter client-side). */
export const PROJECTION_TOP_K = 5;

/** Canonical auto-label prefix; human-format labels must not start with this. */
export const AUTO_LABEL_PREFIX = 'cluster-' as const;

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
  identityThumbUrl?: PendingSuggestion['identity_thumb_url'];
  identityBbox?: PendingSuggestion['identity_bbox'];
  representativeMediaId?: PendingSuggestion['representative_media_id'];
  representativeMediaUrl?: PendingSuggestion['representative_media_url'];
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
  enrichment?: ProjectedSuggestionEnrichment;
}

/**
 * Single eligibility predicate for every leg: truthy trimmed label ∧ not auto-label-prefixed.
 */
export const isHumanLabeledTarget = (label: string | null | undefined): boolean => {
  const trimmed = label?.trim();
  if (!trimmed) {
    return false;
  }
  return !trimmed.startsWith(AUTO_LABEL_PREFIX);
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

/**
 * TOTAL adapter from a pending-list PendingSuggestion row.
 * Passes through null/undefined labels and enrichment fields without inventing defaults (rg-015).
 * identityCount is set only when cluster_identity_count is a finite number (null/undefined omitted).
 */
export const fromPendingRow = (row: PendingSuggestion): ProjectedSuggestion => {
  const projected: ProjectedSuggestion = {
    suggestionId: row.id,
    identityId: row.identity_id,
    clusterId: row.suggested_cluster_id,
    label: row.cluster_label,
    similarity: row.representative_similarity,
    enrichment: {
      identityMediaId: row.identity_media_id,
      identityMediaUrl: row.identity_media_url,
      identityThumbUrl: row.identity_thumb_url,
      identityBbox: row.identity_bbox,
      representativeMediaId: row.representative_media_id,
      representativeMediaUrl: row.representative_media_url,
      representativeThumbUrl: row.representative_thumb_url,
      representativeBbox: row.representative_bbox,
      suggestedLabel: row.suggested_label,
      suggestedLabelSource: row.suggested_label_source,
      suggestedLabelConfidence: row.suggested_label_confidence,
    },
  };
  if (typeof row.cluster_identity_count === 'number') {
    projected.identityCount = row.cluster_identity_count;
  }
  if (row.created_at !== undefined) {
    projected.createdAt = row.created_at;
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

export const invalidateSuggestionProjection = (queryClient: QueryClient): Promise<void> =>
  queryClient.invalidateQueries({
    queryKey: queryKeys.suggestions.projection.all,
  });

/**
 * Invalidation event map (D4) as data for UXP-5 wiring.
 * Each row records whether the assignment projection invalidates and which
 * cross-family targets live today and must be preserved.
 */
export const SUGGESTION_PROJECTION_INVALIDATION_EVENTS = {
  suggestionAcceptReject: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['clusters.all'] as const,
  },
  bulkAccept: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['mergePending', 'namePending'] as const,
  },
  clusterLabelSetClear: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['mergePending', 'clusters'] as const,
  },
  clusterMerge: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['mergePending', 'clusters'] as const,
  },
  clusterDismiss: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['mergePending'] as const,
  },
  scanRecomputeCompletion: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: ['mergePending', 'namePending'] as const,
  },
  syncTrigger: {
    invalidatesAssignmentProjection: true,
    keptCrossFamilyTargets: [] as const,
    viaSuggestionsAllRoot: true,
  },
} as const;

export type SuggestionProjectionInvalidationEvent = keyof typeof SUGGESTION_PROJECTION_INVALIDATION_EVENTS;
