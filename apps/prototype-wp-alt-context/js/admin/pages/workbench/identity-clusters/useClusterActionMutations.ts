/**
 * Hook for cluster action mutations (assign, create, reassign, split, reject).
 */

import { __ } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  acceptSuggestion,
  createClusterForIdentity,
  fetchScanStatus,
  pinRepresentative,
  reassignClusterIdentity,
  rejectSuggestion,
  splitCluster,
} from '../../../api/recognition';
import { offlineActionReason, useRemoteActionGate } from '../../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../../hooks/useSyncOffline';
import { isScanSuccessStatus } from '../../../hooks/jobStateMachineUtils';
import { delay, isAbortError } from './clusterMutationUtils';
import { removePendingSuggestionFromCache } from './suggestionProjection';

interface UseClusterActionMutationsOptions {
  clusterId: string | null;
  identityCount?: number;
  onRenameSuccess?: (newLabel: string) => void;
  onError?: (error: string) => void;
  onAbort?: () => void;
  invalidateQueries: () => void;
}

const SPLIT_ASYNC_THRESHOLD = 50;
const SPLIT_POLL_INTERVAL_MS = 1500;
const SPLIT_TIMEOUT_MS = 120_000;

const pollSplitJob = async (jobId: string): Promise<void> => {
  const startedAt = Date.now();
  while (Date.now() - startedAt < SPLIT_TIMEOUT_MS) {
    const status = await fetchScanStatus(jobId);
    // BND-1: completed_with_errors is a terminal partial-success — resolve the poll, else it spins
    // until SPLIT_TIMEOUT_MS and throws a spurious timeout. 'failed' remains the only hard failure.
    if (isScanSuccessStatus(status.status)) {
      return;
    }
    if (status.status === 'failed') {
      throw new Error(status.message ?? __('Split job failed.', 'alt-context'));
    }
    await delay(SPLIT_POLL_INTERVAL_MS);
  }
  throw new Error(__('Split job timed out. Please retry.', 'alt-context'));
};

export const useClusterActionMutations = ({
  clusterId,
  identityCount,
  onRenameSuccess,
  onError,
  onAbort,
  invalidateQueries,
}: UseClusterActionMutationsOptions) => {
  const queryClient = useQueryClient();
  // RES-15: gate split only — reassign/pin/reject stay live offline (outbox curation).
  const offline = useSyncOffline();
  const splitGate = useRemoteActionGate(offline);

  const reassignMutation = useMutation({
    mutationKey: ['reassign-identities', clusterId],
    mutationFn: async (identityIds: string[]) => {
      for (const id of identityIds) {
        await reassignClusterIdentity({ identityId: id, targetClusterId: null, blockFromCluster: true });
      }
    },
    retry: false,
    onSuccess: () => {
      invalidateQueries();
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        onAbort?.();
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  const assignToClusterMutation = useMutation({
    mutationKey: ['assign-to-cluster', clusterId],
    mutationFn: async ({
      identityId,
      targetClusterId,
      signal,
      suggestionId,
    }: {
      identityId: string;
      targetClusterId: string;
      signal?: AbortSignal;
      suggestionId?: string;
    }) => {
      // BR-16: confirm with a suggestion id resolves by id (accept assigns + marks accepted).
      if (suggestionId) {
        await acceptSuggestion(suggestionId);
        return;
      }
      await reassignClusterIdentity({ identityId, targetClusterId }, signal);
    },
    retry: false,
    onSuccess: (_data, variables) => {
      // L1V-03: optimistically remove accepted suggestion before invalidate/refetch.
      if (variables.suggestionId) {
        removePendingSuggestionFromCache(queryClient, variables.suggestionId);
      }
      invalidateQueries();
      onRenameSuccess?.('');
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        onAbort?.();
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  const createClusterMutation = useMutation({
    mutationKey: ['create-cluster-for-identity'],
    mutationFn: async ({
      identityId,
      label,
      signal,
      rosterEntryId,
    }: {
      identityId: string;
      label: string;
      signal?: AbortSignal;
      rosterEntryId?: number;
    }) => {
      return createClusterForIdentity({ identityId, label, rosterEntryId }, signal);
    },
    retry: false,
    onSuccess: (result) => {
      invalidateQueries();
      onRenameSuccess?.(result.label);
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        onAbort?.();
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes('acx_cluster_created_bind_failed')) {
        invalidateQueries();
        onError?.(__('The group was created but the person was not bound.', 'alt-context'));
        return;
      }
      if (message.includes('409')) {
        onError?.(__('Label already exists. Select it from the dropdown to assign.', 'alt-context'));
      } else {
        onError?.(message);
      }
    },
  });

  const splitMutation = useMutation({
    mutationKey: ['split-cluster', clusterId],
    mutationFn: async ({
      clusterId,
      nClusters = 2,
      anchorIdentityId,
    }: {
      clusterId: string;
      nClusters?: number;
      anchorIdentityId?: string;
    }) => {
      if (offline) {
        throw new Error(offlineActionReason());
      }
      const mode = (identityCount ?? 0) > SPLIT_ASYNC_THRESHOLD ? 'async' : 'sync';
      const result = await splitCluster(clusterId, { nClusters, anchorIdentityId, splitMode: 'forced', mode });
      if ('job_id' in result) {
        await pollSplitJob(result.job_id);
      }
      return result;
    },
    retry: false,
    onSuccess: () => {
      invalidateQueries();
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        onAbort?.();
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  const rejectSuggestionMutation = useMutation({
    mutationKey: ['reject-suggestion'],
    mutationFn: (suggestionId: string) => rejectSuggestion(suggestionId),
    retry: false,
    onSuccess: () => {
      invalidateQueries();
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  const pinRepresentativeMutation = useMutation({
    mutationKey: ['pin-representative', clusterId],
    mutationFn: async ({
      representativeId,
      isPinned,
      signal,
    }: {
      representativeId: string;
      isPinned: boolean;
      signal?: AbortSignal;
    }) => {
      if (!clusterId) {
        throw new Error(__('Cannot pin representative: no cluster ID', 'alt-context'));
      }
      await pinRepresentative(clusterId, representativeId, isPinned, signal);
    },
    retry: false,
    onSuccess: () => {
      invalidateQueries();
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        onAbort?.();
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  return {
    reassign: reassignMutation.mutate,
    assignToCluster: (
      identityId: string,
      targetClusterId: string,
      signal?: AbortSignal,
      suggestionId?: string,
    ) => assignToClusterMutation.mutate({ identityId, targetClusterId, signal, suggestionId }),
    createClusterForIdentity: (
      identityId: string,
      label: string,
      signal?: AbortSignal,
      rosterEntryId?: number,
    ) => createClusterMutation.mutate({ identityId, label, signal, rosterEntryId }),
    // RES-03: no offline short-circuit here — the mutationFn throws so onError surfaces the reason.
    split: (clusterId: string, nClusters = 2, anchorIdentityId?: string) =>
      splitMutation.mutate({ clusterId, nClusters, anchorIdentityId }),
    rejectSuggestion: (suggestionId: string) => rejectSuggestionMutation.mutate(suggestionId),
    pinRepresentative: (representativeId: string, isPinned: boolean, signal?: AbortSignal) =>
      pinRepresentativeMutation.mutate({ representativeId, isPinned, signal }),
    isReassigning: reassignMutation.isPending,
    isAssigning: assignToClusterMutation.isPending,
    isCreatingCluster: createClusterMutation.isPending,
    isSplitting: splitMutation.isPending,
    isRejectingSuggestion: rejectSuggestionMutation.isPending,
    isPinningRepresentative: pinRepresentativeMutation.isPending,
    splitGate,
  };
};
