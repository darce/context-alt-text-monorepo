/**
 * Write orchestration for ClusterLabelingPanel (extracted for FEBT1G-M-14).
 *
 * Owns the four remote writes (rename, roster bind, merge, merge revert), their shared
 * interactive budget, and the cache reconciliation each success implies. Every request is
 * transport-cancellable: the budget's controller signal is threaded all the way to fetch
 * (FEBT1-LC-01 / RES-04 — a deadline that only abandons the caller still leaks the
 * server-side write).
 */

import React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { mergeCluster, revertMergeCluster, updateClusterLabel, type MergeClusterResponse } from '../../../api/recognition';
import { commitClusterToRosterEntry } from '../../../api/rosterApi';
import { queryKeys } from '../../../api/queryKeys';
import { CLUSTER_LABELING_OPERATION, SAVE_TIMEOUT_MS, withTimeout } from './clusterLabelingBudget';
import {
  dropClusterFromReviewCaches,
  invalidateReviewCachesWithoutRefetch,
  invalidateSuggestionProjection,
  REVIEW_DROP_MODE,
} from './suggestionProjection';

export interface ClusterLabelingMutationsOptions {
  readonly clusterId: string;
  /** Called after a successful label/bind write, with the label the operator ends up on. */
  readonly onLabel: (label: string) => void;
  /** Called before any success handler so the panel can clear transient UI state. */
  readonly onWriteSuccess: () => void;
  /** Raw error; the panel maps it through the canonical taxonomy. */
  readonly onError: (error: unknown) => void;
}

export interface ClusterLabelingMutations {
  readonly saveLabel: (label: string) => Promise<void>;
  readonly bindToRosterEntry: (variables: { rosterEntryId: number; name: string }) => Promise<void>;
  readonly merge: (variables: { targetClusterId: string; targetLabel: string }) => void;
  readonly revert: (payload: MergeClusterResponse) => void;
  readonly lastMerge: MergeClusterResponse | null;
  readonly clearLastMerge: () => void;
  readonly isMerging: boolean;
  readonly isReverting: boolean;
  readonly isBusy: boolean;
}

export const useClusterLabelingMutations = ({
  clusterId,
  onLabel,
  onWriteSuccess,
  onError,
}: ClusterLabelingMutationsOptions): ClusterLabelingMutations => {
  const queryClient = useQueryClient();
  const [lastMerge, setLastMerge] = React.useState<MergeClusterResponse | null>(null);

  const handleLabelSuccess = (label: string) => {
    onWriteSuccess();
    // UXW2-2 (B6): the labelled cluster's pending rows leave the review caches now —
    // backend suggestion curation lags the label write.
    dropClusterFromReviewCaches(queryClient, clusterId, { mode: REVIEW_DROP_MODE.LABEL });
    invalidateReviewCachesWithoutRefetch(queryClient);
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities(), refetchType: 'none' });
    void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
    onLabel(label);
  };

  const labelMutation = useMutation({
    mutationFn: (newLabel: string) =>
      withTimeout(
        (signal) => updateClusterLabel(clusterId, newLabel, signal),
        SAVE_TIMEOUT_MS,
        CLUSTER_LABELING_OPERATION.SAVE,
      ),
    retry: false,
    onSuccess: (_result, newLabel) => handleLabelSuccess(newLabel),
  });

  const bindMutation = useMutation({
    mutationFn: ({ rosterEntryId }: { rosterEntryId: number; name: string }) =>
      withTimeout(
        (signal) => commitClusterToRosterEntry({ clusterId, rosterEntryId }, signal),
        SAVE_TIMEOUT_MS,
        CLUSTER_LABELING_OPERATION.SAVE,
      ),
    retry: false,
    onSuccess: (result, variables) => handleLabelSuccess(result.person_name ?? variables.name),
  });

  const mergeMutation = useMutation({
    // FEBT1G-H-08: merge shares the save's interactive budget instead of falling through
    // to the global fetch timeout.
    mutationFn: ({ targetClusterId, targetLabel }: { targetClusterId: string; targetLabel: string }) =>
      withTimeout(
        (signal) => mergeCluster(clusterId, targetClusterId, targetLabel, signal),
        SAVE_TIMEOUT_MS,
        CLUSTER_LABELING_OPERATION.MERGE,
      ),
    retry: false,
    onSuccess: (result: MergeClusterResponse) => {
      onWriteSuccess();
      setLastMerge(result);
      // UXW2-2-R1-21: drop the authoritative retired source, not the local panel id.
      if (typeof result.source_id === 'string' && result.source_id !== '') {
        dropClusterFromReviewCaches(queryClient, result.source_id, { mode: REVIEW_DROP_MODE.MERGE });
      }
      invalidateReviewCachesWithoutRefetch(queryClient);
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities(), refetchType: 'none' });
    },
    onError,
  });

  const revertMutation = useMutation({
    // FEBT2-W2-R-01: the module docstring above claims a shared interactive budget for its
    // four writes; the undo was the one that fell through to the global fetch timeout, so
    // the claim was false for a quarter of the surface it described. It now shares the save
    // budget and threads the signal to fetch, like its three siblings (RES-02 "every
    // socket/pool/RPC/wait() needs a bounded timeout", lexicons/engineering.md:113; RES-04
    // — a deadline that only abandons the caller still leaks the server-side write,
    // lexicons/engineering.md:115).
    mutationFn: (payload: MergeClusterResponse) =>
      withTimeout(
        (signal) =>
          revertMergeCluster(
            {
              targetClusterId: payload.target_id,
              movedIdentityIds: payload.moved_identity_ids,
              sourceLabel: payload.source_label,
            },
            signal,
          ),
        SAVE_TIMEOUT_MS,
        CLUSTER_LABELING_OPERATION.REVERT_MERGE,
      ),
    retry: false,
    onSuccess: () => {
      setLastMerge(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void invalidateSuggestionProjection(queryClient);
    },
    onError,
  });

  const clearLastMerge = React.useCallback(() => setLastMerge(null), []);

  return {
    saveLabel: (label) => labelMutation.mutateAsync(label).then(() => undefined),
    bindToRosterEntry: (variables) => bindMutation.mutateAsync(variables).then(() => undefined),
    merge: (variables) => mergeMutation.mutate(variables),
    revert: (payload) => revertMutation.mutate(payload),
    lastMerge,
    clearLastMerge,
    isMerging: mergeMutation.isPending,
    isReverting: revertMutation.isPending,
    isBusy: labelMutation.isPending || mergeMutation.isPending || bindMutation.isPending,
  };
};
