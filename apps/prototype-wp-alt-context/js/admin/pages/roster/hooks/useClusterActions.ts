import { __, sprintf } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../../../api/queryKeys';
import type { BatchAnalyzeResponse } from '../../../api/recognition';
import { commitClusterToRosterEntry, type RosterClusterCommitResponse } from '../../../api/rosterApi';
import { reassignClusterIdentity, scanFacesBatched } from '../../../api/recognition';
import { invalidateSuggestionProjection } from '../../workbench/identity-clusters/suggestionProjection';
import { useToast } from '../../../context/ToastContext';
import { offlineActionReason, useRemoteActionGate } from '../../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../../hooks/useSyncOffline';

interface ClusterActionOptions {
  onReassignSettled?: () => void;
  onRescanSettled?: () => void;
  onCommitSettled?: () => void;
}

export const useClusterActions = ({
  onReassignSettled,
  onRescanSettled,
  onCommitSettled,
}: ClusterActionOptions = {}) => {
  const queryClient = useQueryClient();
  const { success, error: showToastError } = useToast();
  // RES-15: gate sensitive rescan only — curation (reassign/commit) stays live offline.
  const offline = useSyncOffline();
  const rescanGate = useRemoteActionGate(offline);

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

  const resetAll = () => {
    reassignMutation.reset();
    rescanMutation.reset();
    commitMutation.reset();
  };

  return {
    reassignMutation,
    rescanMutation,
    commitMutation,
    rescanGate,
    errorMessage:
      reassignMutation.error?.message ??
      rescanMutation.error?.message ??
      commitMutation.error?.message ??
      null,
    resetAll,
  };
};
