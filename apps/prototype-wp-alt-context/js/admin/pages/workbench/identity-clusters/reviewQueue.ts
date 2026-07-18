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

/** Filter chip kinds for the pre-commit review queue (KIND-derived). */
export const REVIEW_QUEUE_FILTER = {
  ALL: 'all',
  ASSIGNMENT: NEXT_ACTION_KIND.ASSIGNMENT,
  MERGE: NEXT_ACTION_KIND.MERGE,
} as const;

export type ReviewQueueFilter = (typeof REVIEW_QUEUE_FILTER)[keyof typeof REVIEW_QUEUE_FILTER];

/**
 * KIND → human chip copy (sr-007). Only the two live demo chips.
 * Do not map NAME/CLUSTER until a chip ships with them.
 */
export const NEXT_ACTION_CHIP_LABEL = {
  [NEXT_ACTION_KIND.ASSIGNMENT]: 'Close matches',
  [NEXT_ACTION_KIND.MERGE]: 'Possible duplicates',
} as const satisfies Partial<Record<NextActionKind, string>>;

export type ReviewQueueItem =
  | {
      kind: typeof NEXT_ACTION_KIND.ASSIGNMENT;
      suggestionId: string;
      clusterId: string | null;
      label: string | null;
      /** Same-cluster run size (flattened group length, or 1 for singles). */
      runSize: number;
      /** 0-based index within the same-cluster run. */
      runIndex: number;
    }
  | { kind: typeof NEXT_ACTION_KIND.MERGE; suggestionId: string }
  | { kind: typeof NEXT_ACTION_KIND.NAME; suggestionId: string; clusterId: string }
  | { kind: typeof NEXT_ACTION_KIND.CLUSTER; clusterId: string };

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
      runSize: 1,
      runIndex: 0,
    });
  }

  return items;
};

/**
 * Full ordered queue: assignments (flattened) → merges → names → largest unlabeled clusters.
 * Default (unfiltered) order preserves the historical selectNextAction priority.
 */
export const buildReviewQueue = (
  sources: ReviewQueueSources,
  filter: ReviewQueueFilter = REVIEW_QUEUE_FILTER.ALL,
): ReviewQueueItem[] => {
  const assignments = flattenAssignments(sources.reviewItems);
  const merges: ReviewQueueItem[] = sources.mergeSuggestions.map((merge) => ({
    kind: NEXT_ACTION_KIND.MERGE,
    suggestionId: merge.id,
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

  const ordered: ReviewQueueItem[] = [...assignments, ...merges, ...names, ...clusters];

  if (filter === REVIEW_QUEUE_FILTER.ALL) {
    return ordered;
  }

  return ordered.filter((item) => item.kind === filter);
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
 *   queue (the item at the head slot changes). Use `removeAtQueueIndex`.
 * - prev/next are the **only** index mutations.
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

/** Prev is an index mutation (only when index > 0). */
export const prevQueueIndex = (index: number): number => Math.max(0, index - 1);

/** Next is an index mutation (clamped to last item). */
export const nextQueueIndex = (index: number, length: number): number => {
  if (length <= 0) {
    return 0;
  }
  return Math.min(index + 1, length - 1);
};

/**
 * Successful commit/removal: drop the item at `index` without changing the
 * caller's index. The same index then points at the former next item (or empty).
 */
export const removeAtQueueIndex = <T>(items: readonly T[], index: number): T[] => {
  if (index < 0 || index >= items.length) {
    return [...items];
  }
  return items.filter((_, i) => i !== index);
};
