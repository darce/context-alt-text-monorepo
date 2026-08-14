/**
 * Hook for handling confirmation of suggested cluster matches.
 */

import React from 'react';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import type { ClusterGroup } from './types';
import type { SaveDialogAction } from './useClusterConfirmDialog';
import type { SaveStatus } from './useClusterSaveStatus';
import { useClusterMatchAction } from './useClusterMatchAction';

interface ClusterConfirmMutations {
  isPending: boolean;
  merge: (
    targetClusterId: string,
    targetLabel?: string,
    signal?: AbortSignal,
    suggestionId?: string,
  ) => void;
  assignToCluster: (
    identityId: string,
    targetClusterId: string,
    signal?: AbortSignal,
    suggestionId?: string,
  ) => void;
}

interface UseClusterConfirmSuggestionOptions {
  members: ClusterGroup['members'];
  editableClusterId: string | null;
  canEdit: boolean;
  canSearchForMatch: boolean;
  options: ComboboxOption[];
  saveStatus: SaveStatus;
  mutations: ClusterConfirmMutations;
  requestConfirm: (action: SaveDialogAction, label: string) => Promise<boolean>;
  cancelEditing: () => void;
  setError: (message: string) => void;
  queueSaveStatus: () => void;
  resetSaveStatus: () => void;
  saveAbortRef: React.MutableRefObject<AbortController | null>;
}

export const useClusterConfirmSuggestion = ({
  members,
  editableClusterId,
  canEdit,
  canSearchForMatch,
  options,
  saveStatus,
  mutations,
  requestConfirm,
  cancelEditing,
  setError,
  queueSaveStatus,
  resetSaveStatus,
  saveAbortRef,
}: UseClusterConfirmSuggestionOptions) => {
  const { runMatchedAction } = useClusterMatchAction({
    members,
    editableClusterId,
    canSearchForMatch,
    options,
    mutations,
    requestConfirm,
  });

  const handleConfirmSuggestion = React.useCallback(
    async (clusterId: string, label: string, suggestionId?: string) => {
      if (saveStatus !== 'idle' || mutations.isPending) {
        return;
      }
      if (!canEdit && !canSearchForMatch) {
        return;
      }

      if (saveAbortRef.current) {
        saveAbortRef.current.abort();
      }
      const abortController = new AbortController();
      saveAbortRef.current = abortController;
      queueSaveStatus();
      let mutationStarted = false;

      try {
        // Exact no-op (BR-42): same target cluster id — not same label. Same-label
        // different-target (e.g. Bob→other-bob) must still merge/assign.
        if (clusterId === editableClusterId) {
          cancelEditing();
          resetSaveStatus();
          return;
        }

        mutationStarted = await runMatchedAction(
          { id: clusterId, label, suggestionId },
          abortController,
        );
      } catch (err) {
        if (err && typeof err === 'object' && 'name' in err && (err as { name: string }).name === 'AbortError') {
          resetSaveStatus();
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        resetSaveStatus();
      } finally {
        if (!mutationStarted) {
          saveAbortRef.current = null;
          resetSaveStatus();
        }
      }
    },
    [
      cancelEditing,
      canEdit,
      canSearchForMatch,
      editableClusterId,
      mutations,
      queueSaveStatus,
      resetSaveStatus,
      runMatchedAction,
      saveAbortRef,
      saveStatus,
      setError,
    ],
  );

  return { handleConfirmSuggestion };
};
