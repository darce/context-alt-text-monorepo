/**
 * Hook for cluster action mutations (assign, create, reassign, split, reject).
 */

import { __ } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

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
import {
  delay,
  getClusterErrorCode,
  getClusterMutationErrorMessage,
  isDeliberateCancelError,
} from './clusterMutationUtils';
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

/**
 * Route a failed cluster-action write to exactly one outcome: silence, or copy.
 *
 * FEBT2-LD2-NEW-01 / RLSE-05 (lexicons/engineering.md:82 - "silent failure is the worst
 * failure"). Every handler below used to gate on `isAbortError`, which is abort-*like*:
 * `isAbortOrTimeoutName` answers true for `name === 'TimeoutError'`, and that is exactly what
 * `fetchApi`'s own deadline carries (`RequestTimeoutError`, utils/errorTaxonomy.ts).
 * An elapsed write therefore took the `onAbort` branch, and `onAbort` is
 * `resetSaveStatus` (IdentityClusterItem.tsx) - the operator saw nothing at all on a
 * write path. Only a *deliberate* cancel (the operator's own action) may be silent, and
 * `isDeliberateCancelError` is the predicate that answers that question
 * (clusterMutationUtils.ts).
 *
 * Copy for everything else comes from `getClusterMutationErrorMessage`, the single owner
 * of error -> operator copy for this feature area (REF-19 lexicons/engineering.md:338;
 * DOM-03 :528 - one meaning per term per context). This hook does not mint a second
 * timeout sentinel or a second timeout string.
 */
const routeMutationFailure = (
  error: unknown,
  handlers: { readonly onAbort?: () => void; readonly onError?: (message: string) => void },
  label = '',
): void => {
  if (isDeliberateCancelError(error)) {
    handlers.onAbort?.();
    return;
  }
  // Everything that is not a deliberate cancel — including the abort-like
  // deadline and the branded interactive-budget sentinel — gets its copy from
  // the single owner. Never `error.message`: FEBT1-W2A-04, an HTTPError message
  // embeds the response body preview, so the verbatim text is not operator copy.
  handlers.onError?.(getClusterMutationErrorMessage(error, label));
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
  const splitAbortRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      // Stop waiting on a write whose UI owner is gone. This does not claim the
      // split did not land: after a network interruption the outcome is unknown
      // (literature/extracted/refactoring/distilled/
      // designing-data-intensive-applications.md:305). `splitCluster`
      // already threads this signal through to fetchApi; this hook supplies the
      // lifecycle owner it lacked (RES-13,
      // docs/reviews/uxp-2/lexicons/engineering.md:47).
      splitAbortRef.current?.abort();
      splitAbortRef.current = null;
    },
    [],
  );

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
      routeMutationFailure(err, { onAbort, onError });
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
      routeMutationFailure(err, { onAbort, onError });
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
    onError: (err: unknown, variables) => {
      // Read the structured WP error code, not a substring of the message
      // (main FEBT1-W2A-04). The cache still has to be invalidated on a partial
      // create-then-bind failure before the copy is routed.
      if (getClusterErrorCode(err) === 'acx_cluster_created_bind_failed') {
        invalidateQueries();
      }
      routeMutationFailure(err, { onAbort, onError }, variables.label);
    },
  });

  const splitMutation = useMutation({
    mutationKey: ['split-cluster', clusterId],
    mutationFn: async ({
      clusterId,
      nClusters = 2,
      anchorIdentityId,
      signal,
    }: {
      clusterId: string;
      nClusters?: number;
      anchorIdentityId?: string;
      signal: AbortSignal;
    }) => {
      if (offline) {
        throw new Error(offlineActionReason());
      }
      const mode = (identityCount ?? 0) > SPLIT_ASYNC_THRESHOLD ? 'async' : 'sync';
      const result = await splitCluster(
        clusterId,
        { nClusters, anchorIdentityId, splitMode: 'forced', mode },
        signal,
      );
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
      routeMutationFailure(err, { onAbort, onError });
    },
    onSettled: (_data, _error, variables) => {
      if (splitAbortRef.current?.signal === variables.signal) {
        splitAbortRef.current = null;
      }
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
      routeMutationFailure(err, { onAbort, onError });
    },
  });

  return {
    reassign: reassignMutation.mutate,
    assignToCluster: (identityId: string, targetClusterId: string, signal?: AbortSignal, suggestionId?: string) =>
      assignToClusterMutation.mutate({ identityId, targetClusterId, signal, suggestionId }),
    createClusterForIdentity: (identityId: string, label: string, signal?: AbortSignal, rosterEntryId?: number) =>
      createClusterMutation.mutate({ identityId, label, signal, rosterEntryId }),
    // RES-03: no offline short-circuit here — the mutationFn throws so onError surfaces the reason.
    split: (clusterId: string, nClusters = 2, anchorIdentityId?: string) => {
      splitAbortRef.current?.abort();
      const controller = new AbortController();
      splitAbortRef.current = controller;
      splitMutation.mutate({ clusterId, nClusters, anchorIdentityId, signal: controller.signal });
    },
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
