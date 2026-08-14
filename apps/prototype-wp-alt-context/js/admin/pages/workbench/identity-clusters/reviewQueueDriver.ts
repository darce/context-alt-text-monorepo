/**
 * E21-5 Slice 1a — unified review-queue driver (pure, zero UI).
 *
 * Builds an ordered, filterable queue from the same sources as
 * useWorkbenchFindings. Assignment eligibility/ordering already live in
 * buildSuggestionReviewItems (isHumanLabeledTarget + compareSuggestions from
 * the UXP-3 contract); this module flattens groups and applies the fixed
 * KIND priority. No roster queue_memberships reads.
 */

import type { PendingMergeSuggestion, PendingNameSuggestion } from '../../../api/recognition/types';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';
import type { SuggestionReviewItem } from './suggestionReviewItems';

/** Cluster evidence gate (E21-18 S2 / sr-007). Zero-evidence rows never enter the queue. */
export const CLUSTER_EVIDENCE = {
  ZERO: 'zero',
  PRESENT: 'present',
} as const;

export type ClusterEvidence = (typeof CLUSTER_EVIDENCE)[keyof typeof CLUSTER_EVIDENCE];

type ClusterEvidenceInput = Pick<TopUnlabeledCluster, 'identity_count'> & {
  representatives?: readonly unknown[] | null;
};

/**
 * A cluster is zero-evidence iff identity_count === 0 OR representatives is empty/absent.
 * Either alone already breaks the card: no meta count or no thumbs.
 */
export const isZeroEvidenceCluster = (cluster: ClusterEvidenceInput): boolean =>
  cluster.identity_count === 0 ||
  !Array.isArray(cluster.representatives) ||
  cluster.representatives.length === 0;

export const clusterEvidence = (cluster: ClusterEvidenceInput): ClusterEvidence =>
  isZeroEvidenceCluster(cluster) ? CLUSTER_EVIDENCE.ZERO : CLUSTER_EVIDENCE.PRESENT;

export const NEXT_ACTION_KIND = {
  ASSIGNMENT: 'assignment',
  MERGE: 'merge',
  NAME: 'name',
  CLUSTER: 'cluster',
  NONE: 'none',
} as const;

export type NextActionKind = (typeof NEXT_ACTION_KIND)[keyof typeof NEXT_ACTION_KIND];

export const NONE_REASON = {
  LOADING: 'loading',
  ERROR: 'error',
  UNAVAILABLE: 'unavailable',
  EMPTY: 'empty',
} as const;

export type NoneReason = (typeof NONE_REASON)[keyof typeof NONE_REASON];

export type WorkbenchNextAction =
  | {
      kind: typeof NEXT_ACTION_KIND.ASSIGNMENT;
      suggestionId: string;
      clusterId: string | null;
      label: string | null;
    }
  | { kind: typeof NEXT_ACTION_KIND.MERGE; suggestionId: string }
  | { kind: typeof NEXT_ACTION_KIND.NAME; suggestionId: string; clusterId: string }
  | { kind: typeof NEXT_ACTION_KIND.CLUSTER; clusterId: string }
  | { kind: typeof NEXT_ACTION_KIND.NONE; reason: NoneReason };

/**
 * Drain / empty-queue copy (plan §7 matrix). Shared by the role=status
 * announcement and the empty-state region so unit + e2e assert one string.
 * Empty-on-mount stays unannounced (live region only fires after a prior card).
 */
export const REVIEW_QUEUE_DRAIN_MESSAGE = 'All caught up — no items need review';

/**
 * Tray/announce copy when the selection extends beyond the active KIND ∩ band
 * view (BR-63). Single swept constant — render and live region share it.
 * sprintf args: 1 = total selected, 2 = selected within current filters.
 */
export const SELECTION_SPLIT_MESSAGE = '%1$d selected — %2$d in current filter';

/** Filter chip kinds for the pre-commit review queue (KIND-derived). */
export const REVIEW_QUEUE_FILTER = {
  ALL: 'all',
  ASSIGNMENT: NEXT_ACTION_KIND.ASSIGNMENT,
  MERGE: NEXT_ACTION_KIND.MERGE,
} as const;

export type ReviewQueueFilter = (typeof REVIEW_QUEUE_FILTER)[keyof typeof REVIEW_QUEUE_FILTER];

/**
 * Preset similarity band filter (④). Mirrors `rq=` band enum
 * ({all, strong, weaker}) — never a continuous/slider control (FBT-1 criterion 3).
 */
export const REVIEW_QUEUE_BAND = {
  ALL: 'all',
  STRONG: 'strong',
  WEAKER: 'weaker',
} as const;

export type ReviewQueueBand = (typeof REVIEW_QUEUE_BAND)[keyof typeof REVIEW_QUEUE_BAND];

/**
 * Strong-match floor for preset band chips.
 *
 * WHY 0.45: midpoint of the live pending band. The recognition pipeline
 * (`recognition/application/settings/clustering.py`) defaults `suggestion_floor`
 * to 0.35 and `suggestion_ceiling` to 0.55 — matches ≥ ceiling auto-accept, so
 * pending suggestions live in [floor, ceiling) and this preset splits that
 * PENDING range in half (strong = upper half). It is a fixed preset, not synced
 * to backend settings (the frontend cannot read them), so drift is possible if
 * the backend band moves. These chips are fixed presets over
 * ProjectedSuggestion.similarity (post isHumanLabeledTarget), never a
 * user-tunable threshold control.
 */
export const STRONG_SIMILARITY_MIN = 0.45;

/**
 * KIND → human chip copy (sr-007). Only the two live demo chips.
 * Do not map NAME/CLUSTER until a chip ships with them.
 */
export const NEXT_ACTION_CHIP_LABEL = {
  [NEXT_ACTION_KIND.ASSIGNMENT]: 'Close matches',
  [NEXT_ACTION_KIND.MERGE]: 'Possible duplicates',
} as const satisfies Partial<Record<NextActionKind, string>>;

/**
 * Band → human chip copy (sr-007). Banned-vocab-clean; no "projection"/threshold jargon.
 */
export const REVIEW_QUEUE_BAND_CHIP_LABEL = {
  [REVIEW_QUEUE_BAND.STRONG]: 'Strong matches',
  [REVIEW_QUEUE_BAND.WEAKER]: 'Weaker matches',
} as const satisfies Record<
  Exclude<ReviewQueueBand, typeof REVIEW_QUEUE_BAND.ALL>,
  string
>;

export type ReviewQueueItem =
  | {
      kind: typeof NEXT_ACTION_KIND.ASSIGNMENT;
      suggestionId: string;
      clusterId: string | null;
      label: string | null;
      /** ProjectedSuggestion.similarity (band filter input; post-eligibility). */
      similarity: number;
      /** Same-cluster run size (flattened group length, or 1 for singles). */
      runSize: number;
      /** 0-based index within the same-cluster run. */
      runIndex: number;
    }
  | {
      kind: typeof NEXT_ACTION_KIND.MERGE;
      suggestionId: string;
      /**
       * Merge payload similarity (cluster-pair domain — NOT the assignment
       * ProjectedSuggestion.similarity domain). Carried for card display only;
       * band filtering excludes MERGE (BR-60).
       */
      similarity: number;
    }
  | { kind: typeof NEXT_ACTION_KIND.NAME; suggestionId: string; clusterId: string }
  | { kind: typeof NEXT_ACTION_KIND.CLUSTER; clusterId: string };

/**
 * Band-filter similarity: ASSIGNMENT only (ProjectedSuggestion.similarity).
 * MERGE similarity is a different domain (cluster-pair), so merges are excluded
 * from strong/weaker exactly like NAME/CLUSTER — visible under band=all only (BR-60).
 */
export const queueItemSimilarity = (item: ReviewQueueItem): number | undefined => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
      return item.similarity;
    case NEXT_ACTION_KIND.MERGE:
    case NEXT_ACTION_KIND.NAME:
    case NEXT_ACTION_KIND.CLUSTER:
      return undefined;
  }
};

/**
 * Pure band predicate over ASSIGNMENT items' ProjectedSuggestion.similarity.
 * Applied AFTER isHumanLabeledTarget eligibility (queue is already eligibility-filtered).
 * Items without a band similarity (merge/name/cluster) only pass when band is `all`.
 */
export const matchesSimilarityBand = (
  similarity: number | undefined,
  band: ReviewQueueBand,
): boolean => {
  if (band === REVIEW_QUEUE_BAND.ALL) {
    return true;
  }
  if (similarity === undefined) {
    return false;
  }
  if (band === REVIEW_QUEUE_BAND.STRONG) {
    return similarity >= STRONG_SIMILARITY_MIN;
  }
  return similarity < STRONG_SIMILARITY_MIN;
};

export interface ReviewQueueSources {
  reviewItems: readonly SuggestionReviewItem[];
  mergeSuggestions: readonly PendingMergeSuggestion[];
  nameSuggestions: readonly PendingNameSuggestion[];
  /** Pre-sorted by identity_count desc (caller responsibility). */
  sortedClusters: readonly TopUnlabeledCluster[];
}

const flattenAssignments = (reviewItems: readonly SuggestionReviewItem[]): ReviewQueueItem[] => {
  const items: ReviewQueueItem[] = [];

  for (const item of reviewItems) {
    if (item.type === 'group') {
      const runSize = item.suggestions.length;
      for (let runIndex = 0; runIndex < runSize; runIndex += 1) {
        const suggestion = item.suggestions[runIndex];
        items.push({
          kind: NEXT_ACTION_KIND.ASSIGNMENT,
          suggestionId: suggestion.suggestionId,
          clusterId: item.clusterId,
          label: item.label,
          similarity: suggestion.similarity,
          runSize,
          runIndex,
        });
      }
      continue;
    }

    const { suggestion } = item;
    items.push({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: suggestion.suggestionId,
      clusterId: suggestion.clusterId,
      label: suggestion.label ?? suggestion.enrichment?.suggestedLabel ?? null,
      similarity: suggestion.similarity,
      runSize: 1,
      runIndex: 0,
    });
  }

  return items;
};

/**
 * Filter an already-built queue by KIND. Consumers of `WorkbenchFindingsViewModel.queue`
 * hold items (not sources) — use this instead of re-calling `buildReviewQueue`.
 */
export const filterReviewQueue = (
  items: readonly ReviewQueueItem[],
  filter: ReviewQueueFilter,
): ReviewQueueItem[] => {
  if (filter === REVIEW_QUEUE_FILTER.ALL) {
    return [...items];
  }
  return items.filter((item) => item.kind === filter);
};

/**
 * Filter an already-built queue by similarity band (④).
 * Composition with KIND is intersection: call after `filterReviewQueue`.
 */
export const filterReviewQueueByBand = (
  items: readonly ReviewQueueItem[],
  band: ReviewQueueBand,
): ReviewQueueItem[] => {
  if (band === REVIEW_QUEUE_BAND.ALL) {
    return [...items];
  }
  return items.filter((item) => matchesSimilarityBand(queueItemSimilarity(item), band));
};

/**
 * KIND ∩ band filter. Bulk preview/commit id sets use this composition (matrix M2).
 */
export const filterReviewQueueComposite = (
  items: readonly ReviewQueueItem[],
  filter: ReviewQueueFilter,
  band: ReviewQueueBand = REVIEW_QUEUE_BAND.ALL,
): ReviewQueueItem[] => filterReviewQueueByBand(filterReviewQueue(items, filter), band);

/**
 * Exact id set of bulk-selectable items under active KIND ∩ band filters (M2 / TEST-08).
 * CLUSTER items have no suggestion id and never enter the bulk set.
 */
export const bulkSelectableIdsInFilters = (
  items: readonly ReviewQueueItem[],
  filter: ReviewQueueFilter,
  band: ReviewQueueBand,
): string[] => {
  const ids: string[] = [];
  for (const item of filterReviewQueueComposite(items, filter, band)) {
    if (item.kind === NEXT_ACTION_KIND.CLUSTER) {
      continue;
    }
    if ('suggestionId' in item) {
      ids.push(item.suggestionId);
    }
  }
  return ids;
};

/**
 * Bulk preview/commit set = selection ∩ (KIND ∩ band). Exact-id intersection (M2).
 */
export const intersectSelectionWithFilters = (
  selectedIds: ReadonlySet<string> | readonly string[],
  items: readonly ReviewQueueItem[],
  filter: ReviewQueueFilter,
  band: ReviewQueueBand,
): string[] => {
  const allowed = new Set(bulkSelectableIdsInFilters(items, filter, band));
  const ordered: string[] = [];
  for (const id of selectedIds) {
    if (allowed.has(id)) {
      ordered.push(id);
    }
  }
  return ordered;
};

/**
 * Full ordered queue: assignments (flattened) → merges → names → largest unlabeled clusters.
 * Default (unfiltered) order preserves the historical selectNextAction priority.
 * Optional KIND + band filters compose by intersection (④ / M2).
 */
export const buildReviewQueue = (
  sources: ReviewQueueSources,
  filter: ReviewQueueFilter = REVIEW_QUEUE_FILTER.ALL,
  band: ReviewQueueBand = REVIEW_QUEUE_BAND.ALL,
): ReviewQueueItem[] => {
  const assignments = flattenAssignments(sources.reviewItems);
  const merges: ReviewQueueItem[] = sources.mergeSuggestions.map((merge) => ({
    kind: NEXT_ACTION_KIND.MERGE,
    suggestionId: merge.id,
    similarity: merge.similarity,
  }));
  const names: ReviewQueueItem[] = sources.nameSuggestions.map((name) => ({
    kind: NEXT_ACTION_KIND.NAME,
    suggestionId: name.id,
    clusterId: name.cluster_id,
  }));
  const clusters: ReviewQueueItem[] = sources.sortedClusters
    .filter((cluster) => clusterEvidence(cluster) === CLUSTER_EVIDENCE.PRESENT)
    .map((cluster) => ({
      kind: NEXT_ACTION_KIND.CLUSTER,
      clusterId: cluster.id,
    }));

  return filterReviewQueueComposite(
    [...assignments, ...merges, ...names, ...clusters],
    filter,
    band,
  );
};

/** Map a queue head item to the WorkbenchNextAction shape consumers already use. */
export const queueItemToNextAction = (item: ReviewQueueItem): WorkbenchNextAction => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
      return {
        kind: NEXT_ACTION_KIND.ASSIGNMENT,
        suggestionId: item.suggestionId,
        clusterId: item.clusterId,
        label: item.label,
      };
    case NEXT_ACTION_KIND.MERGE:
      return { kind: NEXT_ACTION_KIND.MERGE, suggestionId: item.suggestionId };
    case NEXT_ACTION_KIND.NAME:
      return {
        kind: NEXT_ACTION_KIND.NAME,
        suggestionId: item.suggestionId,
        clusterId: item.clusterId,
      };
    case NEXT_ACTION_KIND.CLUSTER:
      return { kind: NEXT_ACTION_KIND.CLUSTER, clusterId: item.clusterId };
  }
};

export const emptyNextAction = (reason: NoneReason): WorkbenchNextAction => ({
  kind: NEXT_ACTION_KIND.NONE,
  reason,
});

/**
 * PR-54 index semantics (driver-level, pure).
 *
 * - Successful commit does **not** increment the index: the item leaves the
 *   review queue by cache removal (removePendingSuggestionFromCache in
 *   useSuggestionReviewMutations), which advances the queue; the former next item
 *   slides into the same slot. The driver only clamps a restored index (see
 *   clampQueueIndex) — it does not own the removal.
 * - prev/next are the **only** intentional index steppers; both are range-safe.
 * - A restored index clamps to `min(index, length - 1)`; empty → 0 (empty state).
 */

/** Clamp a restored index into [0, length-1]; empty queue → 0 (never negative). */
export const clampQueueIndex = (index: number, length: number): number => {
  if (length <= 0) {
    return 0;
  }
  if (index < 0) {
    return 0;
  }
  return Math.min(index, length - 1);
};

/**
 * Prev is an index mutation. Incoming index is clamped into
 * `[0, max(0, length-1)]` before stepping back (so oversized/negative stay in range).
 */
export const prevQueueIndex = (index: number, length: number): number => {
  if (length <= 0) {
    return 0;
  }
  const clamped = clampQueueIndex(index, length);
  return Math.max(0, clamped - 1);
};

/**
 * Next is an index mutation. Incoming index is clamped into
 * `[0, max(0, length-1)]` before stepping forward (so negative floors at 0, then +1).
 */
export const nextQueueIndex = (index: number, length: number): number => {
  if (length <= 0) {
    return 0;
  }
  const clamped = clampQueueIndex(index, length);
  return Math.min(clamped + 1, length - 1);
};

/**
 * BR-35/BR-40/BR-41: queue ordinal props are integers >= 1 only.
 * Rejects 0, negative, NaN, Infinity, and floats so sprintf cannot coerce junk into accnames.
 */
export const isValidQueueOrdinal = (value: number | undefined): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 1;

/**
 * E21-17-R1-TS41-1: pair-level gate — both singles valid and position <= total.
 * Accname consumers must use this (not independent single checks) so "4 of 3" cannot render.
 * Type predicate narrows `position`; pair it with `isValidQueueOrdinal(total)` at the call site
 * so control-flow narrowing covers both sprintf args (same pattern as the old dual single-guards).
 */
export const isValidQueueOrdinalPair = (
  position: number | undefined,
  total: number | undefined,
): position is number =>
  isValidQueueOrdinal(position) && isValidQueueOrdinal(total) && position <= total;
