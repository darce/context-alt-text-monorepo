/**
 * Typed view model for the Workbench live findings panel (E15-23).
 *
 * Combines assignment, merge, and name suggestions plus top unlabeled
 * clusters into one summary with a deterministic primary next action.
 */

import { useMemo } from 'react';

import { DATA_SOURCE, type DataSource } from '../../../api/recognition/types/dataSource';
import type { PendingMergeSuggestion, PendingNameSuggestion } from '../../../api/recognition/types';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';
import type { SuggestionReviewItem } from './SuggestionCards';
import { useSuggestionReviewQueries } from './useSuggestionReviewQueries';

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
}

export interface WorkbenchFindingsSourceState {
  assignmentDataSource: DataSource | undefined;
  nameDataSource: DataSource | undefined;
  topUnlabeledDataSource: DataSource | undefined;
  isLoading: boolean;
  isError: boolean;
}

export interface WorkbenchFindingsViewModel {
  counts: WorkbenchFindingsCounts;
  previews: WorkbenchFindingPreview[];
  hasFindings: boolean;
  isLoading: boolean;
  isError: boolean;
  isUnavailable: boolean;
  isReadOnly: boolean;
  nextAction: WorkbenchNextAction;
}

const PREVIEW_LIMIT = 6;

const sortClustersBySize = (clusters: TopUnlabeledCluster[]): TopUnlabeledCluster[] =>
  [...clusters].sort((a, b) => b.identity_count - a.identity_count);

const assignmentAction = (item: SuggestionReviewItem): WorkbenchNextAction => {
  if (item.type === 'group') {
    return {
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: item.suggestions[0].id,
      clusterId: item.clusterId,
      label: item.label,
    };
  }
  return {
    kind: NEXT_ACTION_KIND.ASSIGNMENT,
    suggestionId: item.suggestion.id,
    clusterId: item.suggestion.suggested_cluster_id,
    label: item.suggestion.cluster_label ?? item.suggestion.suggested_label ?? null,
  };
};

const selectNextAction = (
  queues: WorkbenchFindingsQueues,
  state: { isLoading: boolean; isError: boolean; isUnavailable: boolean },
  sortedClusters: TopUnlabeledCluster[],
): WorkbenchNextAction => {
  // reviewItems are pre-sorted by descending score in buildSuggestionReviewItems.
  if (queues.reviewItems.length > 0) {
    return assignmentAction(queues.reviewItems[0]);
  }
  if (queues.mergeSuggestions.length > 0) {
    return { kind: NEXT_ACTION_KIND.MERGE, suggestionId: queues.mergeSuggestions[0].id };
  }
  if (queues.nameSuggestions.length > 0) {
    return {
      kind: NEXT_ACTION_KIND.NAME,
      suggestionId: queues.nameSuggestions[0].id,
      clusterId: queues.nameSuggestions[0].cluster_id,
    };
  }
  if (sortedClusters.length > 0) {
    return { kind: NEXT_ACTION_KIND.CLUSTER, clusterId: sortedClusters[0].id };
  }
  if (state.isLoading) {
    return { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.LOADING };
  }
  if (state.isError) {
    return { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR };
  }
  if (state.isUnavailable) {
    return { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.UNAVAILABLE };
  }
  return { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY };
};

const collectPreviews = (
  queues: WorkbenchFindingsQueues,
  sortedClusters: TopUnlabeledCluster[],
): WorkbenchFindingPreview[] => {
  const previews: WorkbenchFindingPreview[] = [];

  for (const item of queues.reviewItems) {
    const suggestion = item.type === 'group' ? item.suggestions[0] : item.suggestion;
    previews.push({
      key: `assignment-${suggestion.id}`,
      thumbUrl: suggestion.identity_thumb_url ?? null,
      mediaUrl: suggestion.identity_media_url ?? null,
      label: item.type === 'group' ? item.label : (suggestion.cluster_label ?? suggestion.suggested_label ?? null),
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
    unlabeledClusters: queues.topUnlabeledClusters.length,
    total: queues.assignmentTotal + queues.mergeTotal + queues.nameTotal + queues.topUnlabeledClusters.length,
  };

  const isUnavailable =
    state.assignmentDataSource === DATA_SOURCE.UNAVAILABLE || state.topUnlabeledDataSource === DATA_SOURCE.UNAVAILABLE;
  const isReadOnly =
    state.assignmentDataSource === DATA_SOURCE.BACKEND_PROXY ||
    state.nameDataSource === DATA_SOURCE.BACKEND_PROXY ||
    state.topUnlabeledDataSource === DATA_SOURCE.BACKEND_PROXY;

  const sortedClusters = sortClustersBySize(queues.topUnlabeledClusters);

  return {
    counts,
    previews: collectPreviews(queues, sortedClusters),
    hasFindings: counts.total > 0,
    isLoading: state.isLoading,
    isError: state.isError,
    isUnavailable,
    isReadOnly,
    nextAction: selectNextAction(
      queues,
      { isLoading: state.isLoading, isError: state.isError, isUnavailable },
      sortedClusters,
    ),
  };
};

export const useWorkbenchFindings = (): WorkbenchFindingsViewModel => {
  const {
    assignmentQuery,
    mergeQuery,
    nameQuery,
    topUnlabeledQuery,
    assignmentDataSource,
    mergeSuggestions,
    nameSuggestions,
    nameDataSource,
    topUnlabeledClusters,
    topUnlabeledDataSource,
    reviewItems,
  } = useSuggestionReviewQueries();

  const hasAnyData = Boolean(assignmentQuery.data ?? mergeQuery.data ?? nameQuery.data ?? topUnlabeledQuery.data);
  const isLoading =
    !hasAnyData &&
    (assignmentQuery.isLoading || mergeQuery.isLoading || nameQuery.isLoading || topUnlabeledQuery.isLoading);
  const isError = !hasAnyData && assignmentQuery.isError && mergeQuery.isError;

  const assignmentTotal = assignmentQuery.data?.total ?? 0;
  const mergeTotal = mergeQuery.data?.total ?? mergeSuggestions.length;
  const nameTotal = nameQuery.data?.total ?? nameSuggestions.length;

  return useMemo(
    () =>
      buildWorkbenchFindings(
        {
          reviewItems,
          assignmentTotal,
          mergeSuggestions,
          mergeTotal,
          nameSuggestions,
          nameTotal,
          topUnlabeledClusters,
        },
        {
          assignmentDataSource,
          nameDataSource,
          topUnlabeledDataSource,
          isLoading,
          isError,
        },
      ),
    [
      reviewItems,
      assignmentTotal,
      mergeSuggestions,
      mergeTotal,
      nameSuggestions,
      nameTotal,
      topUnlabeledClusters,
      assignmentDataSource,
      nameDataSource,
      topUnlabeledDataSource,
      isLoading,
      isError,
    ],
  );
};
