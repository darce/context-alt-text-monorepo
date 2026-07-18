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
 * WHY 0.80: historical recognition pipeline boundary — the suggestion band was
 * [~0.65, 0.80) and ≥0.80 was treated as a strong auto-accept-class match.
 * These chips are fixed presets over ProjectedSuggestion.similarity (post
 * isHumanLabeledTarget), never a user-tunable threshold control.
 */
export const STRONG_SIMILARITY_MIN = 0.8;

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
      /** Merge payload similarity (same band predicate domain as assignment). */
      similarity: number;
    }
  | { kind: typeof NEXT_ACTION_KIND.NAME; suggestionId: string; clusterId: string }
  | { kind: typeof NEXT_ACTION_KIND.CLUSTER; clusterId: string };

/** Similarity for band filtering when the item carries one; undefined for name/cluster. */
export const queueItemSimilarity = (item: ReviewQueueItem): number | undefined => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
    case NEXT_ACTION_KIND.MERGE:
      return item.similarity;
    case NEXT_ACTION_KIND.NAME:
    case NEXT_ACTION_KIND.CLUSTER:
      return undefined;
  }
};

/**
 * Pure band predicate over ProjectedSuggestion.similarity (and merge similarity).
 * Applied AFTER isHumanLabeledTarget eligibility (queue is already eligibility-filtered).
 * Items without a similarity (name/cluster) only pass when band is `all`.
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
  // Iterate Set or array without Array.from (eslint-safe string narrowing).
  if (selectedIds instanceof Set) {
    for (const id of selectedIds) {
      if (allowed.has(id)) {
        ordered.push(id);
      }
    }
    return ordered;
  }
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
  const clusters: ReviewQueueItem[] = sources.sortedClusters.map((cluster) => ({
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
 * - Successful commit does **not** increment the index: removal advances the
 *   queue. Use `removeAtQueueCursor` — it returns the post-removal items and a
 *   range-safe cursor (same slot when a later item slides in; clamped when the
 *   removed item was the tail).
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
 * Successful commit/removal: drop the item at `index` and return a cursor-safe
 * result. The returned `index` is `clampQueueIndex(index, items.length)` after
 * removal:
 * - head/mid removal: same index now points at the former next item
 * - last-item removal: cursor lands on the new last item
 * - emptied queue: index is 0 (empty-state handling remains a caller obligation)
 * - out-of-bounds index: no-op copy of items; cursor clamped to the current length
 */
export const removeAtQueueCursor = <T>(
  items: readonly T[],
  index: number,
): { items: T[]; index: number } => {
  if (index < 0 || index >= items.length) {
    return {
      items: [...items],
      index: clampQueueIndex(index, items.length),
    };
  }
  const nextItems = items.filter((_, i) => i !== index);
  return {
    items: nextItems,
    index: clampQueueIndex(index, nextItems.length),
  };
};

/**
 * Items-only removal helper. Prefer `removeAtQueueCursor` when the caller also
 * holds a cursor — this path does not return a post-removal index.
 */
export const removeAtQueueIndex = <T>(items: readonly T[], index: number): T[] =>
  removeAtQueueCursor(items, index).items;
