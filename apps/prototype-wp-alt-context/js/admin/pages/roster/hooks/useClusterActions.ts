import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../../../api/queryKeys';
import type { BatchAnalyzeResponse } from '../../../api/recognition';
import { commitClusterToRosterEntry, type RosterClusterCommitResponse } from '../../../api/rosterApi';
import { dismissCluster, mergeCluster, reassignClusterIdentity, scanFacesBatched } from '../../../api/recognition';
import { invalidateSuggestionProjection } from '../../workbench/identity-clusters/suggestionProjection';
import { useToast } from '../../../context/ToastContext';
import { offlineActionReason, useRemoteActionGate } from '../../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../../hooks/useSyncOffline';

/** Per-step stall bound for progressive bulk merge (rg-007 analog). */
export const BULK_MERGE_STEP_TIMEOUT_MS = 30_000;

export interface BulkMergeProgress {
  current: number;
  total: number;
}

export interface BulkMergeFailure {
  failedClusterId: string;
  message: string;
  /** Target + failed source + unprocessed sources — remainder stays selected. */
  remainingClusterIds: string[];
}

interface ClusterActionOptions {
  onReassignSettled?: () => void;
  onRescanSettled?: () => void;
  onCommitSettled?: () => void;
  /** Full-success only — do not clear selection on mid-sequence failure. */
  onBulkMergeSettled?: () => void;
  /** Prune selection to failed + unprocessed remainder after stop-on-failure. */
  onBulkMergeFailure?: (remainingClusterIds: string[]) => void;
  onBulkDismissSettled?: () => void;
}

const isAbortError = (err: unknown, signal: AbortSignal): boolean => {
  if (signal.aborted) {
    return true;
  }
  if (err instanceof DOMException && err.name === 'AbortError') {
    return true;
  }
  return err instanceof Error && (err.name === 'AbortError' || /aborted|abort/i.test(err.message));
};

export const useClusterActions = ({
  onReassignSettled,
  onRescanSettled,
  onCommitSettled,
  onBulkMergeSettled,
  onBulkMergeFailure,
  onBulkDismissSettled,
}: ClusterActionOptions = {}) => {
  const queryClient = useQueryClient();
  const { success, error: showToastError } = useToast();
  const [bulkMergeProgress, setBulkMergeProgress] = React.useState<BulkMergeProgress | null>(null);
  const [bulkMergeFailure, setBulkMergeFailure] = React.useState<BulkMergeFailure | null>(null);
  const bulkMergeFailureRef = React.useRef<BulkMergeFailure | null>(null);
  // RES-15: gate sensitive rescan only — curation (merge/reassign/commit/dismiss) stays live offline.
  const offline = useSyncOffline();
  const rescanGate = useRemoteActionGate(offline);

  const clearBulkMergeFailure = React.useCallback(() => {
    bulkMergeFailureRef.current = null;
    setBulkMergeFailure(null);
  }, []);

  const reassignMutation = useMutation<void, Error, { faceId: string; targetClusterId: string | null }>({
    mutationFn: (variables) =>
      reassignClusterIdentity({ identityId: variables.faceId, targetClusterId: variables.targetClusterId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      success(__('Face moved.', 'alt-context'));
    },
    onError: (err) => showToastError(err.message),
    onSettled: onReassignSettled,
  });

  const rescanMutation = useMutation<
    BatchAnalyzeResponse,
    Error,
    { cluster: { id: string; sample_identities: { media_id: number }[] }; mediaIds: number[] }
  >({
    mutationFn: ({ cluster, mediaIds }) => {
      if (offline) {
        throw new Error(offlineActionReason());
      }
      return scanFacesBatched({ mediaIds, sensitivity: 'high', clusterId: cluster.id });
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      const firstJob = data.jobs[0];
      const msg = firstJob?.id
        ? data.jobs.length > 1
          ? sprintf(
              __('Started sensitive rescan (%d batches, first job %s).', 'alt-context'),
              data.jobs.length,
              firstJob.id,
            )
          : sprintf(__('Started sensitive rescan (job %s).', 'alt-context'), firstJob.id)
        : __('Started sensitive rescan.', 'alt-context');
      success(msg);
    },
    onError: (err) => showToastError(err.message),
    onSettled: onRescanSettled,
  });

  const commitMutation = useMutation<
    RosterClusterCommitResponse,
    Error,
    { clusterId: string; rosterEntryId?: number; newEntryName?: string }
  >({
    mutationFn: (variables) =>
      commitClusterToRosterEntry({
        clusterId: variables.clusterId,
        rosterEntryId: variables.rosterEntryId,
        newEntryName: variables.newEntryName,
      }),
    onSuccess: () => {
      // clusterLabelSetClear event (SUGGESTION_PROJECTION_INVALIDATION_EVENTS):
      // committing labels a cluster, changing its suggestion eligibility everywhere.
      void invalidateSuggestionProjection(queryClient);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
      success(__('Face group assigned to person.', 'alt-context'));
    },
    onError: (err) => showToastError(err.message),
    onSettled: onCommitSettled,
  });

  const bulkMergeMutation = useMutation<void, Error, { clusterIds: string[] }>({
    mutationFn: async ({ clusterIds }) => {
      if (clusterIds.length < 2) {
        setBulkMergeProgress(null);
        return;
      }
      bulkMergeFailureRef.current = null;
      setBulkMergeFailure(null);

      const targetId = clusterIds[0];
      const sourceIds = clusterIds.slice(1);
      const total = sourceIds.length;
      setBulkMergeProgress({ current: 1, total });

      for (const [index, sourceId] of sourceIds.entries()) {
        setBulkMergeProgress({ current: index + 1, total });
        const controller = new AbortController();
        const timer = window.setTimeout(() => {
          controller.abort();
        }, BULK_MERGE_STEP_TIMEOUT_MS);
        try {
          await mergeCluster(sourceId, targetId, undefined, controller.signal);
        } catch (err) {
          const remainingClusterIds = [targetId, sourceId, ...sourceIds.slice(index + 1)];
          const timedOut = isAbortError(err, controller.signal);
          const message = timedOut
            ? sprintf(
                // translators: %s: short cluster id
                __('Merge timed out for cluster %s.', 'alt-context'),
                sourceId.slice(0, 8),
              )
            : sprintf(
                // translators: %s: short cluster id
                __('Merge failed for cluster %s.', 'alt-context'),
                sourceId.slice(0, 8),
              );
          const failure: BulkMergeFailure = {
            failedClusterId: sourceId,
            message,
            remainingClusterIds,
          };
          bulkMergeFailureRef.current = failure;
          setBulkMergeFailure(failure);
          throw err instanceof Error ? err : new Error(String(err));
        } finally {
          window.clearTimeout(timer);
        }
      }
    },
    onSuccess: () => {
      bulkMergeFailureRef.current = null;
      setBulkMergeFailure(null);
      // clusterMerge event (SUGGESTION_PROJECTION_INVALIDATION_EVENTS): absorbed source
      // clusters may back pending assignment suggestions on any surface.
      void invalidateSuggestionProjection(queryClient);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      success(__('Clusters merged successfully.', 'alt-context'));
      onBulkMergeSettled?.();
    },
    onError: (err) => {
      const failure = bulkMergeFailureRef.current;
      if (failure) {
        onBulkMergeFailure?.(failure.remainingClusterIds);
      } else {
        showToastError(err.message);
      }
      // Refresh so successfully merged sources disappear; remainder stays selected.
      void invalidateSuggestionProjection(queryClient);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
    onSettled: () => {
      setBulkMergeProgress(null);
    },
  });

  const bulkDismissMutation = useMutation<void, Error, { clusterIds: string[] }>({
    mutationFn: async ({ clusterIds }) => {
      await Promise.all(clusterIds.map((id) => dismissCluster(id)));
    },
    onSuccess: () => {
      // clusterDismiss event (SUGGESTION_PROJECTION_INVALIDATION_EVENTS): dismissed
      // clusters may back pending assignment suggestions on any surface.
      void invalidateSuggestionProjection(queryClient);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      success(__('Clusters dismissed.', 'alt-context'));
    },
    onError: (err) => showToastError(err.message),
    onSettled: onBulkDismissSettled,
  });

  const resetAll = () => {
    reassignMutation.reset();
    rescanMutation.reset();
    commitMutation.reset();
    bulkMergeMutation.reset();
    bulkDismissMutation.reset();
    clearBulkMergeFailure();
    setBulkMergeProgress(null);
  };

  return {
    reassignMutation,
    rescanMutation,
    commitMutation,
    bulkMergeMutation,
    bulkDismissMutation,
    bulkMergeProgress,
    bulkMergeFailure,
    clearBulkMergeFailure,
    rescanGate,
    errorMessage:
      reassignMutation.error?.message ??
      rescanMutation.error?.message ??
      commitMutation.error?.message ??
      (bulkMergeFailure ? null : bulkMergeMutation.error?.message) ??
      bulkDismissMutation.error?.message ??
      null,
    resetAll,
  };
};
