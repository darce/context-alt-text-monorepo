import { useMemo } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import type { AnalyzeResponse } from '../../../api/recognition';
import { commitClusterToRosterEntry } from '../../../api/rosterApi';
import { reassignClusterIdentity, scanFacesBatched } from '../../../api/recognition';

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

  const reassignMutation = useMutation<void, Error, { faceId: string; targetClusterId: string | null }>({
    mutationFn: (variables) =>
      reassignClusterIdentity({ identityId: variables.faceId, targetClusterId: variables.targetClusterId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
    onSettled: onReassignSettled,
  });

  const rescanMutation = useMutation<
    AnalyzeResponse[],
    Error,
    { cluster: { id: string; sample_identities: { media_id: number }[] }; mediaIds: number[] }
  >({
    mutationFn: ({ cluster, mediaIds }) => scanFacesBatched({ mediaIds, sensitivity: 'high', clusterId: cluster.id }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
    onSettled: onRescanSettled,
  });

  const commitMutation = useMutation<void, Error, { clusterId: string; rosterEntryId?: number; newEntryName?: string }>(
    {
      mutationFn: (variables) =>
        commitClusterToRosterEntry({
          clusterId: variables.clusterId,
          rosterEntryId: variables.rosterEntryId,
          newEntryName: variables.newEntryName,
        }),
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
        void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
      },
      onSettled: onCommitSettled,
    },
  );

  const statusMessage = useMemo(() => {
    if (rescanMutation.isSuccess && rescanMutation.data) {
      const firstJob = rescanMutation.data[0];
      return firstJob?.id
        ? rescanMutation.data.length > 1
          ? `Started sensitive rescan (${rescanMutation.data.length} batches, first job ${firstJob.id}).`
          : `Started sensitive rescan (job ${firstJob.id}).`
        : 'Started sensitive rescan.';
    }
    if (commitMutation.isSuccess) {
      return 'Cluster committed to roster entry.';
    }
    if (reassignMutation.isSuccess) {
      return 'Identity assignment updated.';
    }
    return null;
  }, [rescanMutation.data, rescanMutation.isSuccess, commitMutation.isSuccess, reassignMutation.isSuccess]);

  const error = reassignMutation.error ?? rescanMutation.error ?? commitMutation.error ?? null;

  const resetAll = () => {
    reassignMutation.reset();
    rescanMutation.reset();
    commitMutation.reset();
  };

  return {
    reassignMutation,
    rescanMutation,
    commitMutation,
    statusMessage,
    errorMessage: error ? error.message : null,
    resetAll,
  };
};
