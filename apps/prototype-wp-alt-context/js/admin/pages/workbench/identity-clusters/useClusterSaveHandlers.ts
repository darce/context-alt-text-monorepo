/**
 * Composed hook for save/confirm handlers in the cluster edit flow.
 */

import type { MutableRefObject } from 'react';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import type { ClusterGroup } from './types';
import type { SaveDialogAction } from './useClusterConfirmDialog';
import type { ClusterLabelMatch } from './useClusterMatchAction';
import type { SaveStatus } from './useClusterSaveStatus';
import { useClusterConfirmSuggestion } from './useClusterConfirmSuggestion';
import { useClusterSaveAction } from './useClusterSaveAction';

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
  createClusterForIdentity: (
    identityId: string,
    label: string,
    signal?: AbortSignal,
    rosterEntryId?: number,
  ) => void;
  bindToRosterEntry?: (rosterEntryId: number, label: string, signal?: AbortSignal) => void;
}

interface UseClusterSaveHandlersOptions {
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
  saveAbortRef: MutableRefObject<AbortController | null>;
}

export const useClusterSaveHandlers = (options: UseClusterSaveHandlersOptions) => {
  const { handleConfirmSuggestion } = useClusterConfirmSuggestion(options);
  const { handleSave, handleCancel, handlePersonSelect } = useClusterSaveAction(options);

  return {
    handleCancel,
    handleConfirmSuggestion,
    handleSave,
    handlePersonSelect,
  };
};
