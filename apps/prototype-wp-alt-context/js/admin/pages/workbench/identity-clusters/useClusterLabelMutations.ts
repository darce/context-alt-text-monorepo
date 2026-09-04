/**
 * Hook for label-focused cluster mutations (rename, merge, revert).
 */

import { __ } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  acceptMergeSuggestion,
  mergeCluster,
  revertMergeCluster,
  updateClusterLabel,
  type AcceptedMergeSuggestion,
  type MergeClusterResponse,
} from '../../../api/recognition';
import { getClusterMutationErrorMessage, isDeliberateCancelError } from './clusterMutationUtils';
import { useOptionalMergeSurvivors } from './MergeSurvivorContext';
import {
  dropClusterFromReviewCaches,
  invalidateReviewCachesWithoutRefetch,
  removePendingSuggestionFromCache,
  REVIEW_DROP_MODE,
} from './suggestionProjection';

/**
 * Project the atomic accept envelope onto the merge shape the UI already consumes.
 *
 * rg-015: every field here comes from the response itself. The labels are matched
 * against the authoritative source/target ids rather than assuming a side, and the
 * moved count is the length of the authoritative revert set — not a guess. A
 * response whose topology matches neither cluster is a contract violation and fails
 * loudly rather than silently picking a side.
 */
const toMergeClusterResponse = (accepted: AcceptedMergeSuggestion): MergeClusterResponse => {
  const labelFor = (clusterId: string): string | null => {
    if (clusterId === accepted.cluster_a_id) {
      return accepted.cluster_a_label ?? null;
    }
    if (clusterId === accepted.cluster_b_id) {
      return accepted.cluster_b_label ?? null;
    }
    throw new Error(
      `Merge accept response topology does not match the suggestion clusters: ${clusterId}`,
    );
  };

  return {
    source_id: accepted.source_cluster_id,
    source_label: labelFor(accepted.source_cluster_id),
    target_id: accepted.target_cluster_id,
    target_label: labelFor(accepted.target_cluster_id),
    identities_moved: accepted.moved_identity_ids.length,
    moved_identity_ids: accepted.moved_identity_ids,
    // The accept envelope carries no post-merge target size. 0 is the documented
    // absent-count fallback already used by clusterApiResponseMappers.ts:33-35, and
    // no consumer of MergeClusterResponse reads this field.
    target_identity_count: 0,
  };
};

interface UseClusterLabelMutationsOptions {
  clusterId: string | null;
  currentLabel: string | null;
  derivedLabel: string | null;
  onRenameSuccess?: (newLabel: string) => void;
  onMergeSuccess?: (result: MergeClusterResponse) => void;
  onRevertSuccess?: () => void;
  onError?: (error: string) => void;
  onAbort?: () => void;
  cancelIdentityQueries: () => Promise<void>;
  invalidateQueries: () => void;
  updateCachedClusterLabel: (targetClusterId: string, nextLabel: string) => void;
}

export const useClusterLabelMutations = ({
  clusterId,
  currentLabel,
  derivedLabel,
  onRenameSuccess,
  onMergeSuccess,
  onRevertSuccess,
  onError,
  onAbort,
  cancelIdentityQueries,
  invalidateQueries,
  updateCachedClusterLabel,
}: UseClusterLabelMutationsOptions) => {
  const queryClient = useQueryClient();
  const mergeSurvivors = useOptionalMergeSurvivors();
  const renameMutation = useMutation({
    mutationKey: ['rename-cluster', clusterId],
    mutationFn: ({ label, signal }: { label: string; signal?: AbortSignal }) =>
      updateClusterLabel(clusterId!, label, signal),
    // Don't retry on client errors like 409 Conflict (duplicate label)
    retry: false,
    onMutate: async ({ label }) => {
      if (!clusterId) {
        return;
      }
      await cancelIdentityQueries();
      updateCachedClusterLabel(clusterId, label);
    },
    onSuccess: (_data, variables) => {
      const updatedLabel = variables.label;
      if (clusterId) {
        updateCachedClusterLabel(clusterId, updatedLabel);
        dropClusterFromReviewCaches(queryClient, clusterId, { mode: REVIEW_DROP_MODE.LABEL });
      }
      invalidateReviewCachesWithoutRefetch(queryClient);
      invalidateQueries();
      onRenameSuccess?.(updatedLabel);
    },
    onError: (err: unknown) => {
      // FEBT2 X-LANE-02: gate the silent path on a *deliberate* cancel, not on
      // abort-*like*. The abort-like predicate also answers true for
      // `TimeoutError` — the name utils/http.createTimeoutSignal aborts an
      // elapsed request with — so a rename that hit the transport deadline reset
      // the save status and told the operator nothing (RLSE-05; DOM-03: two
      // meanings bound to one predicate).
      if (isDeliberateCancelError(err)) {
        invalidateQueries();
        onAbort?.();
        return;
      }
      invalidateQueries();
      onError?.(getClusterMutationErrorMessage(err, currentLabel ?? derivedLabel ?? 'that label'));
    },
  });

  // Hop-1 (structural merge) state, applied on both the clean and the
  // partial-failure path — the merge itself is committed in either case.
  const applyCommittedMerge = (result: MergeClusterResponse): void => {
    // Authoritative survivor from MergeClusterResponse (source retired → target survives).
    if (result.source_id && result.target_id) {
      mergeSurvivors?.recordMergeSurvivor(result.source_id, result.target_id);
    }
    if (clusterId) {
      updateCachedClusterLabel(clusterId, result.target_label ?? '');
    }
    if (typeof result.source_id === 'string' && result.source_id !== '') {
      dropClusterFromReviewCaches(queryClient, result.source_id, { mode: REVIEW_DROP_MODE.MERGE });
    }
    invalidateReviewCachesWithoutRefetch(queryClient);
  };

  const mergeMutation = useMutation({
    mutationKey: ['merge-cluster', clusterId],
    mutationFn: async ({
      targetClusterId,
      targetLabel,
      signal,
      suggestionId,
    }: {
      targetClusterId: string;
      targetLabel?: string;
      signal?: AbortSignal;
      suggestionId?: string;
    }) => {
      if (!clusterId) {
        return Promise.reject(new Error(__('Cannot merge: no cluster ID', 'alt-context')));
      }
      // rg-002: when the merge originates from a suggestion, the server commits the
      // merge and the ACCEPTED stamp in one transaction. One request, one outcome —
      // there is no half-applied state for the client to compensate for, so the
      // former two-hop sequence and its compensation error are deleted, not disabled.
      // FEBT2 LD2-NEW-02: the signal is threaded on BOTH branches. The
      // caller aborts the previous save when a new one starts, so a
      // signal-deaf accept keeps writing and its onSuccess rewrites caches for
      // a save the operator already superseded (RLSE-05,
      // lexicons/engineering.md:696).
      if (suggestionId) {
        return toMergeClusterResponse(
          await acceptMergeSuggestion({ suggestionId, targetClusterId, signal }),
        );
      }
      return mergeCluster(clusterId, targetClusterId, targetLabel, signal);
    },
    // Don't retry on client errors
    retry: false,
    onSuccess: (result, variables) => {
      applyCommittedMerge(result);
      // L1V-03: drop accepted pending row before invalidate so review queue is not stale until refetch.
      if (variables.suggestionId) {
        removePendingSuggestionFromCache(queryClient, variables.suggestionId);
      }
      invalidateQueries();
      onMergeSuccess?.(result);
    },
    onError: (err: unknown, variables) => {
      // L1V-02 rationale, retained for the manual (dropdown) path: a plain
      // mergeCluster failure can still race a merge that committed server-side.
      // The atomic accept path cannot half-apply, so it needs no compensation.
      invalidateQueries();
      // FEBT2 X-LANE-02: see the rename gate — an elapsed transport deadline is
      // not an operator cancel and must reach the operator as copy.
      if (isDeliberateCancelError(err)) {
        onAbort?.();
        return;
      }
      onError?.(getClusterMutationErrorMessage(err, variables.targetLabel ?? 'that label'));
    },
  });

  const revertMergeMutation = useMutation({
    // FEBT2-W2-R-01: `signal` is carried in the mutation variables, exactly as rename and
    // merge already do. The risk this closes is not a hang — utils/http bounds every call
    // with DEFAULT_FETCH_TIMEOUT_MS — it is a superseded write landing: an undo the operator
    // has already moved past could still commit and its onSuccess still invalidate caches
    // for an outcome nobody asked for (RES-10).
    mutationFn: ({ payload, signal }: { payload: MergeClusterResponse; signal?: AbortSignal }) =>
      revertMergeCluster(
        {
          targetClusterId: payload.target_id,
          movedIdentityIds: payload.moved_identity_ids,
          sourceLabel: payload.source_label ?? currentLabel ?? derivedLabel ?? null,
        },
        signal,
      ),
    // Don't retry on client errors
    retry: false,
    onSuccess: () => {
      invalidateQueries();
      onRevertSuccess?.();
    },
    // FEBT1-LD-04: the react-query callback receives `unknown`. Annotating it
    // `Error` was both a type lie and an information leak — an HTTPError message
    // embeds the response body preview, so `err.message` is never user copy.
    onError: (err: unknown) => {
      // FEBT2 X-LANE-02: see the rename gate — an elapsed transport deadline is
      // not an operator cancel and must reach the operator as copy.
      if (isDeliberateCancelError(err)) {
        onAbort?.();
        return;
      }
      onError?.(getClusterMutationErrorMessage(err, currentLabel ?? derivedLabel ?? 'that label'));
    },
  });

  return {
    rename: (label: string, signal?: AbortSignal) => renameMutation.mutate({ label, signal }),
    merge: (
      targetClusterId: string,
      targetLabel?: string,
      signal?: AbortSignal,
      suggestionId?: string,
    ) => mergeMutation.mutate({ targetClusterId, targetLabel, signal, suggestionId }),
    revertMerge: (payload: MergeClusterResponse, signal?: AbortSignal) =>
      revertMergeMutation.mutate({ payload, signal }),
    isRenaming: renameMutation.isPending,
    isMerging: mergeMutation.isPending,
    isReverting: revertMergeMutation.isPending,
  };
};
