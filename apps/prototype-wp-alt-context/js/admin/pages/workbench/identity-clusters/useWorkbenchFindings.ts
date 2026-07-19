/**
 * Typed view model for the Workbench live findings panel (E15-23).
 *
 * Combines assignment, merge, and name suggestions plus top unlabeled
 * clusters into one summary with a deterministic primary next action.
 * E21-5 Slice 1a: nextAction is the head of the ordered review queue.
 */

import { DATA_SOURCE, type DataSource } from '../../../api/recognition/types/dataSource';
import type { PendingMergeSuggestion, PendingNameSuggestion } from '../../../api/recognition/types';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';
import type { SuggestionReviewItem } from './SuggestionCards';
import {
  buildReviewQueue,
  emptyNextAction,
  NEXT_ACTION_CHIP_LABEL,
  NEXT_ACTION_KIND,
  NONE_REASON,
  queueItemToNextAction,
  type NextActionKind,
  type NoneReason,
  type ReviewQueueBand,
  type ReviewQueueFilter,
  type ReviewQueueItem,
  type WorkbenchNextAction,
} from './reviewQueueDriver';
import { useSuggestionReviewQueries } from './useSuggestionReviewQueries';

export {
  NEXT_ACTION_CHIP_LABEL,
  NEXT_ACTION_KIND,
  NONE_REASON,
  type NextActionKind,
  type NoneReason,
  type ReviewQueueBand,
  type ReviewQueueFilter,
  type ReviewQueueItem,
  type WorkbenchNextAction,
};

// Re-export pure driver surface for consumers that already import from this module.
export {
  buildReviewQueue,
  bulkSelectableIdsInFilters,
  clampQueueIndex,
  filterReviewQueue,
  filterReviewQueueByBand,
  filterReviewQueueComposite,
  intersectSelectionWithFilters,
  matchesSimilarityBand,
  nextQueueIndex,
  prevQueueIndex,
  queueItemSimilarity,
  REVIEW_QUEUE_BAND,
  REVIEW_QUEUE_BAND_CHIP_LABEL,
  REVIEW_QUEUE_DRAIN_MESSAGE,
  REVIEW_QUEUE_FILTER,
  STRONG_SIMILARITY_MIN,
  queueItemToNextAction,
} from './reviewQueueDriver';

export interface WorkbenchFindingsCounts {
  assignments: number;
  merges: number;
  names: number;
  unlabeledClusters: number;
  total: number;
}

export interface WorkbenchFindingPreview {
  key: string;
  thumbUrl: string | null;
  mediaUrl: string | null;
  label: string | null;
}

export interface WorkbenchFindingsQueues {
  reviewItems: SuggestionReviewItem[];
  assignmentTotal: number;
  mergeSuggestions: PendingMergeSuggestion[];
  mergeTotal: number;
  nameSuggestions: PendingNameSuggestion[];
  nameTotal: number;
  topUnlabeledClusters: TopUnlabeledCluster[];
  topUnlabeledTotal: number;
}

export interface WorkbenchFindingsSourceState {
  assignmentDataSource: DataSource | undefined;
  nameDataSource: DataSource | undefined;
  topUnlabeledDataSource: DataSource | undefined;
  isLoading: boolean;
  isError: boolean;
  /** All four queue-source queries finished initial load (data or error). */
  queueSettled: boolean;
}

export interface WorkbenchFindingsViewModel {
  counts: WorkbenchFindingsCounts;
  previews: WorkbenchFindingPreview[];
  hasFindings: boolean;
  isLoading: boolean;
  isError: boolean;
  isUnavailable: boolean;
  isReadOnly: boolean;
  /**
   * True only when every queue source query has finished its initial load
   * (has data or errored). Partial resolve must not look settled — clamp/index
   * restore depends on the full queue (BR-06).
   */
  queueSettled: boolean;
  /** Head of the ordered review queue (same as queue[0] when non-empty). */
  nextAction: WorkbenchNextAction;
  /**
   * Full ordered, unfiltered review queue (groups flattened per-suggestion).
   * Filter with `filterReviewQueue(queue, filter)` — not applied here so existing
   * consumers of nextAction keep default priority semantics.
   */
  queue: ReviewQueueItem[];
}

const PREVIEW_LIMIT = 6;

const sortClustersBySize = (clusters: TopUnlabeledCluster[]): TopUnlabeledCluster[] =>
  [...clusters].sort((a, b) => b.identity_count - a.identity_count);

const selectNextAction = (
  queue: readonly ReviewQueueItem[],
  state: { isLoading: boolean; isError: boolean; isUnavailable: boolean },
): WorkbenchNextAction => {
  if (queue.length > 0) {
    return queueItemToNextAction(queue[0]);
  }
  if (state.isLoading) {
    return emptyNextAction(NONE_REASON.LOADING);
  }
  if (state.isError) {
    return emptyNextAction(NONE_REASON.ERROR);
  }
  if (state.isUnavailable) {
    return emptyNextAction(NONE_REASON.UNAVAILABLE);
  }
  return emptyNextAction(NONE_REASON.EMPTY);
};

const collectPreviews = (
  queues: WorkbenchFindingsQueues,
  sortedClusters: TopUnlabeledCluster[],
): WorkbenchFindingPreview[] => {
  const previews: WorkbenchFindingPreview[] = [];

  for (const item of queues.reviewItems) {
    const suggestion = item.type === 'group' ? item.suggestions[0] : item.suggestion;
    previews.push({
      key: `assignment-${suggestion.suggestionId}`,
      thumbUrl: suggestion.enrichment?.identityThumbUrl ?? null,
      mediaUrl: suggestion.enrichment?.identityMediaUrl ?? null,
      label:
        item.type === 'group'
          ? item.label
          : (suggestion.label ?? suggestion.enrichment?.suggestedLabel ?? null),
    });
  }

  for (const merge of queues.mergeSuggestions) {
    previews.push({
      key: `merge-${merge.id}`,
      thumbUrl: merge.cluster_a_representative_thumb_url ?? null,
      mediaUrl: merge.cluster_a_representative_media_url ?? null,
      label: merge.cluster_a_label ?? null,
    });
  }

  for (const name of queues.nameSuggestions) {
    const representative = name.representatives?.[0];
    previews.push({
      key: `name-${name.id}`,
      thumbUrl: representative?.thumb_url ?? null,
      mediaUrl: representative?.media_url ?? null,
      label: name.suggested_name,
    });
  }

  for (const cluster of sortedClusters) {
    const representative = cluster.representatives[0];
    previews.push({
      key: `cluster-${cluster.id}`,
      thumbUrl: representative?.thumb_url ?? null,
      mediaUrl: representative?.media_url ?? null,
      label: cluster.label ?? cluster.suggested_label ?? null,
    });
  }

  return previews.filter((preview) => preview.thumbUrl !== null || preview.mediaUrl !== null).slice(0, PREVIEW_LIMIT);
};

export const buildWorkbenchFindings = (
  queues: WorkbenchFindingsQueues,
  state: WorkbenchFindingsSourceState,
): WorkbenchFindingsViewModel => {
  const counts: WorkbenchFindingsCounts = {
    assignments: queues.assignmentTotal,
    merges: queues.mergeTotal,
    names: queues.nameTotal,
    unlabeledClusters: queues.topUnlabeledTotal,
    total: queues.assignmentTotal + queues.mergeTotal + queues.nameTotal + queues.topUnlabeledTotal,
  };

  // WHY: assignment + top-unlabeled are the canonical availability signals; merge/name
  // outages degrade gracefully to a partial summary instead of hiding the panel.
  const isUnavailable =
    state.assignmentDataSource === DATA_SOURCE.UNAVAILABLE || state.topUnlabeledDataSource === DATA_SOURCE.UNAVAILABLE;
  const isReadOnly =
    state.assignmentDataSource === DATA_SOURCE.BACKEND_PROXY ||
    state.nameDataSource === DATA_SOURCE.BACKEND_PROXY ||
    state.topUnlabeledDataSource === DATA_SOURCE.BACKEND_PROXY;

  const sortedClusters = sortClustersBySize(queues.topUnlabeledClusters);
  const queue = buildReviewQueue({
    reviewItems: queues.reviewItems,
    mergeSuggestions: queues.mergeSuggestions,
    nameSuggestions: queues.nameSuggestions,
    sortedClusters,
  });

  return {
    counts,
    previews: collectPreviews(queues, sortedClusters),
    hasFindings: counts.total > 0,
    isLoading: state.isLoading,
    isError: state.isError,
    isUnavailable,
    isReadOnly,
    queueSettled: state.queueSettled,
    queue,
    nextAction: selectNextAction(queue, {
      isLoading: state.isLoading,
      isError: state.isError,
      isUnavailable,
    }),
  };
};

/** Settled = finished initial load (data present, empty success, error, or disabled). */
const isQuerySettled = (query: { isLoading: boolean; isError: boolean; data: unknown }): boolean =>
  Boolean(query.data) || query.isError || !query.isLoading;

export const useWorkbenchFindings = (): WorkbenchFindingsViewModel => {
  const {
    assignmentQuery,
    mergeQuery,
    nameQuery,
    topUnlabeledQuery,
    assignmentDataSource,
    assignmentSuggestions,
    mergeSuggestions,
    nameSuggestions,
    nameDataSource,
    topUnlabeledClusters,
    topUnlabeledTotal,
    topUnlabeledDataSource,
    reviewItems,
  } = useSuggestionReviewQueries();

  const hasAnyData = Boolean(assignmentQuery.data ?? mergeQuery.data ?? nameQuery.data ?? topUnlabeledQuery.data);
  const isLoading =
    !hasAnyData &&
    (assignmentQuery.isLoading || mergeQuery.isLoading || nameQuery.isLoading || topUnlabeledQuery.isLoading);
  // WHY: surface a hard error only when nothing rendered at all; partial query
  // failures degrade gracefully to whatever findings did load.
  const isError = !hasAnyData && assignmentQuery.isError && mergeQuery.isError;
  // BR-06: every source must settle before clamp/index restore — partial
  // assignment+merge data must not look like a complete empty/short queue.
  const queueSettled =
    isQuerySettled(assignmentQuery) &&
    isQuerySettled(mergeQuery) &&
    isQuerySettled(nameQuery) &&
    isQuerySettled(topUnlabeledQuery);

  // COR-3 (rg-015): no authoritative backlog total exists; count loaded items.
  const assignmentTotal = assignmentSuggestions?.length ?? 0;
  const mergeTotal = mergeSuggestions.length;
  const nameTotal = nameSuggestions.length;
  const resolvedTopUnlabeledTotal = topUnlabeledTotal ?? topUnlabeledClusters.length;

  return buildWorkbenchFindings(
    {
      reviewItems,
      assignmentTotal,
      mergeSuggestions,
      mergeTotal,
      nameSuggestions,
      nameTotal,
      topUnlabeledClusters,
      topUnlabeledTotal: resolvedTopUnlabeledTotal,
    },
    {
      assignmentDataSource,
      nameDataSource,
      topUnlabeledDataSource,
      isLoading,
      isError,
      queueSettled,
    },
  );
};
