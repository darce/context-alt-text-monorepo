/**
 * Hook for save and cancel actions in the cluster edit flow.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import type { ClusterGroup } from './types';
import type { SaveDialogAction } from './useClusterConfirmDialog';
import type { SaveStatus } from './useClusterSaveStatus';
import { isHumanLabeledTarget } from './suggestionProjection';
import { useClusterMatchAction, type ClusterLabelMatch } from './useClusterMatchAction';
import { filterEditableClusterMatch } from './utils';

export type { ClusterLabelMatch };

interface ClusterSaveMutations {
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
  matchedCluster: ClusterLabelMatch | null;
  options: ComboboxOption[];
  saveStatus: SaveStatus;
  mutations: ClusterSaveMutations;
  findClusterByLabel: (label: string, signal?: AbortSignal) => Promise<ClusterLabelMatch | null>;
  requestConfirm: (action: SaveDialogAction, label: string) => Promise<boolean>;
  cancelEditing: () => void;
  setError: (message: string) => void;
  queueSaveStatus: () => void;
  resetSaveStatus: () => void;
  saveAbortRef: React.MutableRefObject<AbortController | null>;
}

/**
 * Resolve a person-source option matching the typed label (case-insensitive).
 * Person rows win over same-named clusters so free-text never silent-merges.
 * Returns the trimmed roster label so padded options normalize at one point (UXP-3-BR-46).
 */
export const findPersonOptionLabel = (options: readonly ComboboxOption[], label: string): string | null => {
  const normalized = label.toLowerCase().trim();
  if (!normalized) {
    return null;
  }
  const person = options.find(
    (option) => option.source === 'person' && option.label.toLowerCase().trim() === normalized,
  );
  return person ? person.label.trim() : null;
};

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

  /**
   * Rename/create only — never findClusterByLabel / merge / assign.
   * Used by the person-source path and by free-type rename arms (exact-dupe BR-40, unmatched label).
   */
  const applyPersonLabel = React.useCallback(
    (label: string, abortController: AbortController): boolean => {
      const trimmed = label.trim();
      if (!trimmed) {
        setError(__('Provide a label before saving.', 'alt-context'));
        return false;
      }
      // BR-55: shared sink rejects reserved machine labels (defense-in-depth).
      if (!isHumanLabeledTarget(trimmed)) {
        setError(
          __('This label format is reserved for automatic cluster IDs. Choose a descriptive name.', 'alt-context'),
        );
        return false;
      }
      if (editableClusterId) {
        mutations.rename(trimmed, abortController.signal);
        return true;
      }
      if (anchorIdentityId) {
        mutations.createClusterForIdentity(anchorIdentityId, trimmed, abortController.signal);
        return true;
      }
      setError(__('Cannot create cluster: no identity ID', 'alt-context'));
      return false;
    },
    [anchorIdentityId, editableClusterId, mutations, setError],
  );

  const handlePersonSelect = React.useCallback(
    (label: string) => {
      if (saveStatus !== 'idle' || mutations.isPending) {
        return;
      }
      if (!canEdit && !canSearchForMatch) {
        return;
      }

      const canonical = label.trim();
      if (!canonical) {
        setError(__('Provide a label before saving.', 'alt-context'));
        return;
      }

      const currentLabel = clusterLabel ?? '';
      // Exact dirty check (B6): "bob"→"Bob" proceeds; "Bob"→"Bob" still no-ops.
      if (currentLabel === canonical) {
        cancelEditing();
        return;
      }

      // BR-55: reject machine-shaped / reserved auto-ID labels (same early reject as empty label).
      if (!isHumanLabeledTarget(canonical)) {
        setError(
          __('This label format is reserved for automatic cluster IDs. Choose a descriptive name.', 'alt-context'),
        );
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
        mutationStarted = applyPersonLabel(canonical, abortController);
        if (!mutationStarted) {
          resetSaveStatus();
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
      applyPersonLabel,
      canEdit,
      canSearchForMatch,
      cancelEditing,
      clusterLabel,
      mutations.isPending,
      queueSaveStatus,
      resetSaveStatus,
      saveAbortRef,
      saveStatus,
      setError,
    ],
  );

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
      // Exact dirty check (B6): case-only rename ("bob"→"Bob") must mutate.
      if (currentLabel === trimmed) {
        cancelEditing();
        return;
      }

      // BR-49: reject machine-shaped / reserved auto-ID labels (same early reject as empty label).
      if (!isHumanLabeledTarget(trimmed)) {
        setError(
          __('This label format is reserved for automatic cluster IDs. Choose a descriptive name.', 'alt-context'),
        );
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
        // Free-typed text that case-insensitively matches a person option → rename/create
        // with canonical person casing (never merge into a same-named cluster).
        const personCanonical = findPersonOptionLabel(options, trimmed);
        if (personCanonical) {
          // personCanonical is already trimmed (findPersonOptionLabel). Already at that
          // label → no-op; differing casing still renames (UXP-3-BR-43 / BR-46).
          if (personCanonical === currentLabel) {
            cancelEditing();
            resetSaveStatus();
            return;
          }
          mutationStarted = applyPersonLabel(personCanonical, abortController);
          if (!mutationStarted) {
            resetSaveStatus();
          }
          return;
        }

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

        // match is already self-filtered (filterEditableClusterMatch). When a DIFFERENT
        // cluster's label exactly equals currentLabel (remote exact-dupe, FIX-8), a case-only
        // edit of OUR cluster must rename — never silent cancelEditing and never surprise-merge
        // into the duplicate (UXP-3-BR-40). Reuses applyPersonLabel for the rename arm.
        // Case-variant labels still merge below.
        if (match?.label === currentLabel) {
          mutationStarted = applyPersonLabel(trimmed, abortController);
          if (!mutationStarted) {
            resetSaveStatus();
          }
          return;
        }

        if (match) {
          mutationStarted = await runMatchedAction(match, abortController);
          if (!mutationStarted) {
            resetSaveStatus();
            return;
          }
        } else {
          mutationStarted = applyPersonLabel(trimmed, abortController);
          if (!mutationStarted) {
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
      applyPersonLabel,
      canEdit,
      canSearchForMatch,
      cancelEditing,
      clusterLabel,
      editableClusterId,
      findClusterByLabel,
      labelInput,
      matchedCluster,
      mutations,
      options,
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

  return { handleSave, handleCancel, handlePersonSelect };
};
