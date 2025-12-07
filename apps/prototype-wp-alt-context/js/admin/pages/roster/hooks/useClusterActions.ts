import { useMemo } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import type { AnalyzeResponse } from '../../../api/recognition';
import { commitClusterToRosterEntry } from '../../../api/rosterApi';
import { reassignClusterIdentity, scanFaces } from '../../../api/recognition';

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
      void queryClient.invalidateQueries({ queryKey: ['recognition-clusters'] });
    },
    onSettled: onReassignSettled,
  });

  const rescanMutation = useMutation<
    AnalyzeResponse,
    Error,
    { cluster: { id: string; sample_identities: { media_id: number }[] }; mediaIds: number[] }
  >({
    mutationFn: ({ cluster, mediaIds }) => scanFaces({ mediaIds, sensitivity: 'high', clusterId: cluster.id }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['recognition-clusters'] });
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
        void queryClient.invalidateQueries({ queryKey: ['recognition-clusters'] });
        void queryClient.invalidateQueries({ queryKey: ['roster-entries'] });
      },
      onSettled: onCommitSettled,
    },
  );

  const statusMessage = useMemo(() => {
    if (rescanMutation.isSuccess && rescanMutation.data) {
      return rescanMutation.data.id
        ? `Started sensitive rescan (job ${rescanMutation.data.id}).`
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
