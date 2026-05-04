/**
 * Hook for save and cancel actions in the cluster edit flow.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import type { ClusterGroup } from './types';
import type { SaveDialogAction } from './useClusterConfirmDialog';
import type { SaveStatus } from './useClusterSaveStatus';
import { useClusterMatchAction } from './useClusterMatchAction';
import { filterEditableClusterMatch } from './utils';

interface ClusterSaveMutations {
  isPending: boolean;
  merge: (targetClusterId: string, targetLabel?: string, signal?: AbortSignal) => void;
  assignToCluster: (identityId: string, targetClusterId: string, signal?: AbortSignal) => void;
  rename: (label: string, signal?: AbortSignal) => void;
  createClusterForIdentity: (identityId: string, label: string, signal?: AbortSignal) => void;
}

interface UseClusterSaveActionOptions {
  clusterLabel: string | null;
  members: ClusterGroup['members'];
  editableClusterId: string | null;
  anchorIdentityId?: string;
  canEdit: boolean;
  canSearchForMatch: boolean;
  labelInput: string;
  matchedCluster: { id: string; label: string } | null;
  options: ComboboxOption[];
  saveStatus: SaveStatus;
  mutations: ClusterSaveMutations;
  findClusterByLabel: (label: string, signal?: AbortSignal) => Promise<{ id: string; label: string } | null>;
  requestConfirm: (action: SaveDialogAction, label: string) => Promise<boolean>;
  cancelEditing: () => void;
  setError: (message: string) => void;
  queueSaveStatus: () => void;
  resetSaveStatus: () => void;
  saveAbortRef: React.MutableRefObject<AbortController | null>;
}

export const useClusterSaveAction = ({
  clusterLabel,
  members,
  editableClusterId,
  anchorIdentityId,
  canEdit,
  canSearchForMatch,
  labelInput,
  matchedCluster,
  options,
  saveStatus,
  mutations,
  findClusterByLabel,
  requestConfirm,
  cancelEditing,
  setError,
  queueSaveStatus,
  resetSaveStatus,
  saveAbortRef,
}: UseClusterSaveActionOptions) => {
  const { runMatchedAction } = useClusterMatchAction({
    members,
    editableClusterId,
    canSearchForMatch,
    options,
    mutations,
    requestConfirm,
  });

  const handleSave = React.useCallback(
    async (labelOverride?: string) => {
      if (saveStatus !== 'idle' || mutations.isPending) {
        return;
      }
      if (!canEdit && !canSearchForMatch) {
        return;
      }

      const nextLabel = typeof labelOverride === 'string' ? labelOverride : labelInput;
      const trimmed = nextLabel.trim();
      if (!trimmed) {
        setError(__('Provide a label before saving.', 'alt-context'));
        return;
      }

      const currentLabel = clusterLabel ?? '';
      if (currentLabel?.toLowerCase() === trimmed.toLowerCase()) {
        cancelEditing();
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
        let match = filterEditableClusterMatch(matchedCluster, editableClusterId);
        if (match?.label.toLowerCase() !== trimmed.toLowerCase()) {
          match = filterEditableClusterMatch(
            await findClusterByLabel(trimmed, abortController.signal),
            editableClusterId,
          );
        }

        if (abortController.signal.aborted) {
          return;
        }

        if (match?.label.toLowerCase() === currentLabel.toLowerCase()) {
          cancelEditing();
          resetSaveStatus();
          return;
        }

        if (match) {
          mutationStarted = await runMatchedAction(match, abortController);
          if (!mutationStarted) {
            resetSaveStatus();
            return;
          }
        } else {
          if (editableClusterId) {
            mutationStarted = true;
            mutations.rename(trimmed, abortController.signal);
          } else if (anchorIdentityId) {
            mutationStarted = true;
            mutations.createClusterForIdentity(anchorIdentityId, trimmed, abortController.signal);
          } else {
            const message = __('Cannot create cluster: no identity ID', 'alt-context');
            setError(message);
            resetSaveStatus();
          }
        }
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
      anchorIdentityId,
      canEdit,
      canSearchForMatch,
      cancelEditing,
      clusterLabel,
      editableClusterId,
      findClusterByLabel,
      labelInput,
      matchedCluster,
      mutations,
      queueSaveStatus,
      resetSaveStatus,
      saveAbortRef,
      saveStatus,
      setError,
      runMatchedAction,
    ],
  );

  const handleCancel = React.useCallback(() => {
    if (saveAbortRef.current) {
      saveAbortRef.current.abort();
      saveAbortRef.current = null;
    }
    resetSaveStatus();
    cancelEditing();
  }, [cancelEditing, resetSaveStatus, saveAbortRef]);

  return { handleSave, handleCancel };
};
