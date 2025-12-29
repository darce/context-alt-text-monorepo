/**
 * Single identity cluster item with edit, merge, and action capabilities.
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { MergeClusterResponse } from '../../../api/recognition';
import type { ClusterGroup } from './types';
import { formatClusterLabel, getEditableClusterId } from './utils';
import { useClusterEditState } from './useClusterEditState';
import { useClusterMutations } from './useClusterMutations';
import { useClusterSuggestions } from './useClusterSuggestions';
import { ClusterPreview } from './ClusterPreview';
import { ClusterActions } from './ClusterActions';
import { ClusterEditForm } from './ClusterEditForm';
import { MergeUndoBanner } from './MergeUndoBanner';
import { DebugMetricsPanel } from './DebugMetricsPanel';
import { InlineSuggestionPrompt } from './InlineSuggestionPrompt';
import { AnchorSelectionModal } from './AnchorSelectionModal';
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../../components/ui/dialog';

const SAVE_SUCCESS_DELAY_MS = 1200;
const MATCH_DEBOUNCE_MS = 300;

interface IdentityClusterItemProps {
  cluster: ClusterGroup;
}

type SaveDialogAction = 'rename' | 'merge' | 'assign' | 'create';

type SaveStatus = 'idle' | 'queued' | 'saved';

interface ConfirmDialogState {
  open: boolean;
  action: SaveDialogAction;
  label: string;
}

/**
 * Renders a single cluster with its thumbnail, label, and actions.
 *
 * Handles:
 * - Display mode (label + action buttons)
 * - Edit mode (Combobox with suggestions)
 * - Merge undo banner
 * - Error display
 */
export const IdentityClusterItem = ({ cluster }: IdentityClusterItemProps): React.JSX.Element => {
  // Compute derived values
  const derivedLabel = React.useMemo(
    () => formatClusterLabel(cluster.clusterId, cluster.label, cluster.isAutoLabel),
    [cluster.clusterId, cluster.label, cluster.isAutoLabel],
  );

  const editableClusterId = React.useMemo(() => getEditableClusterId(cluster), [cluster]);

  // For singletons without a cluster, we still allow naming/merging via identity ID
  const isSingleton = !editableClusterId && cluster.members.length === 1;
  const canEdit = Boolean(editableClusterId);
  const canSearchForMatch = isSingleton;
  const labelText = derivedLabel ?? __('Unlabeled identity', 'alt-context');
  const representative = cluster.members[0];
  const anchorIdentityId = representative?.identity_id;
  const [isAnchorModalOpen, setIsAnchorModalOpen] = React.useState(false);
  const [saveStatus, setSaveStatus] = React.useState<SaveStatus>('idle');
  const [matchedCluster, setMatchedCluster] = React.useState<{ id: string; label: string } | null>(null);
  const confirmDialogRef = React.useRef<ConfirmDialogState | null>(null);
  const [confirmDialog, setConfirmDialog] = React.useState<ConfirmDialogState | null>(null);
  const confirmResolverRef = React.useRef<((confirmed: boolean) => void) | null>(null);
  const saveStatusTimerRef = React.useRef<number | null>(null);
  const saveAbortRef = React.useRef<AbortController | null>(null);
  const matchAbortRef = React.useRef<AbortController | null>(null);

  // State management
  const {
    state: editState,
    startEditing,
    cancelEditing,
    setLabel,
    setError,
    onSaveSuccess,
    onMergeSuccess,
    onRevertSuccess,
  } = useClusterEditState({ derivedLabel });

  const clearSaveStatusTimer = React.useCallback(() => {
    if (saveStatusTimerRef.current === null) {
      return;
    }
    window.clearTimeout(saveStatusTimerRef.current);
    saveStatusTimerRef.current = null;
  }, []);

  const resetSaveStatus = React.useCallback(() => {
    clearSaveStatusTimer();
    setSaveStatus('idle');
  }, [clearSaveStatusTimer]);

  const queueSaveStatus = React.useCallback(() => {
    clearSaveStatusTimer();
    setSaveStatus('queued');
  }, [clearSaveStatusTimer]);

  const resolveConfirmDialog = React.useCallback((confirmed: boolean) => {
    const resolver = confirmResolverRef.current;
    confirmResolverRef.current = null;
    setConfirmDialog(null);
    if (resolver) {
      resolver(confirmed);
    }
  }, []);

  const updateSaveDialog = React.useCallback((action: SaveDialogAction, label: string) => {
    return new Promise<boolean>((resolve) => {
      confirmResolverRef.current = resolve;
      setConfirmDialog({ open: true, action, label });
    });
  }, []);

  const handleConfirmDialogOpenChange = React.useCallback(
    (open: boolean) => {
      if (!open) {
        resolveConfirmDialog(false);
      }
    },
    [resolveConfirmDialog],
  );

  const handleConfirmAccept = React.useCallback(() => {
    resolveConfirmDialog(true);
  }, [resolveConfirmDialog]);

  const handleConfirmCancel = React.useCallback(() => {
    resolveConfirmDialog(false);
  }, [resolveConfirmDialog]);

  const markSaveSuccess = React.useCallback(
    (onSuccess: () => void) => {
      clearSaveStatusTimer();
      setSaveStatus('saved');
      saveStatusTimerRef.current = window.setTimeout(() => {
        onSuccess();
        setSaveStatus('idle');
        saveStatusTimerRef.current = null;
      }, SAVE_SUCCESS_DELAY_MS);
    },
    [clearSaveStatusTimer],
  );

  const handleSaveSuccess = React.useCallback(() => {
    saveAbortRef.current = null;
    markSaveSuccess(onSaveSuccess);
  }, [markSaveSuccess, onSaveSuccess]);

  const handleMergeSuccess = React.useCallback(
    (result: MergeClusterResponse) => {
      saveAbortRef.current = null;
      markSaveSuccess(() => onMergeSuccess(result));
    },
    [markSaveSuccess, onMergeSuccess],
  );

  const handleMutationError = React.useCallback(
    (message: string) => {
      saveAbortRef.current = null;
      setError(message);
      resetSaveStatus();
    },
    [resetSaveStatus, setError],
  );

  // Suggestions
  const {
    options,
    isLoading: suggestionsLoading,
    findClusterByLabel,
  } = useClusterSuggestions({
    identityId: anchorIdentityId,
    enabled: editState.isEditing,
    labelInput: editState.labelInput,
  });

  // Mutations
  const mutations = useClusterMutations({
    clusterId: editableClusterId,
    identityCount: cluster.members.length,
    currentLabel: cluster.label,
    derivedLabel,
    onRenameSuccess: handleSaveSuccess,
    onMergeSuccess: handleMergeSuccess,
    onRevertSuccess,
    onError: handleMutationError,
  });

  React.useEffect(() => {
    return () => {
      saveAbortRef.current?.abort();
      matchAbortRef.current?.abort();
      clearSaveStatusTimer();
      if (confirmResolverRef.current) {
        confirmResolverRef.current(false);
        confirmResolverRef.current = null;
      }
    };
  }, [clearSaveStatusTimer]);

  // Proactive matching while typing
  React.useEffect(() => {
    if (!editState.isEditing) {
      setMatchedCluster(null);
      return;
    }

    const trimmed = editState.labelInput.trim();
    const currentLabel = cluster.label ?? '';
    if (!trimmed || trimmed.toLowerCase() === currentLabel.toLowerCase()) {
      setMatchedCluster(null);
      return;
    }

    const runMatch = async () => {
      matchAbortRef.current?.abort();
      const abortController = new AbortController();
      matchAbortRef.current = abortController;

      try {
        const match = await findClusterByLabel(trimmed, abortController.signal);
        if (!abortController.signal.aborted) {
          setMatchedCluster(match);
        }
      } catch {
        // Ignore
      }
    };

    const timer = window.setTimeout(runMatch, MATCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [editState.isEditing, editState.labelInput, cluster.label, findClusterByLabel]);

  const handleCancel = React.useCallback(() => {
    if (saveAbortRef.current) {
      saveAbortRef.current.abort();
      saveAbortRef.current = null;
    }
    resetSaveStatus();
    cancelEditing();
  }, [cancelEditing, resetSaveStatus]);

  const isDangerousMerge = React.useCallback(
    (clusterId: string) => {
      const targetMemberCount = (options.find((option) => option.value === clusterId)?.identityCount ?? 0) as number;
      return targetMemberCount >= 5;
    },
    [options],
  );

  const runMatchedAction = React.useCallback(
    async (match: { id: string; label: string }, abortController: AbortController) => {
      const action: SaveDialogAction = canSearchForMatch ? 'assign' : 'merge';

      if (isDangerousMerge(match.id)) {
        const confirmed = await updateSaveDialog(action, match.label);
        if (!confirmed) {
          return false;
        }
      }

      if (abortController.signal.aborted) {
        return false;
      }

      if (editableClusterId) {
        mutations.merge(match.id, match.label, abortController.signal);
        return true;
      }

      for (const member of cluster.members) {
        mutations.assignToCluster(member.identity_id, match.id, abortController.signal);
      }
      return true;
    },
    [
      canSearchForMatch,
      cluster.members,
      editableClusterId,
      isDangerousMerge,
      mutations,
      updateSaveDialog,
    ],
  );

  const handleConfirmSuggestion = React.useCallback(
    async (clusterId: string, label: string) => {
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
        const currentLabel = cluster.label ?? '';
        if (label.toLowerCase() === currentLabel.toLowerCase()) {
          cancelEditing();
          resetSaveStatus();
          return;
        }

        mutationStarted = await runMatchedAction({ id: clusterId, label }, abortController);
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
      cluster.label,
      mutations.isPending,
      queueSaveStatus,
      resetSaveStatus,
      runMatchedAction,
      saveStatus,
      setError,
    ],
  );

  // Handle save (rename or merge)
  const handleSave = async (labelOverride?: string) => {
    if (saveStatus !== 'idle' || mutations.isPending) {
      return;
    }
    // Allow save for regular clusters with canEdit, or for singletons searching for matches
    if (!canEdit && !canSearchForMatch) {
      return;
    }

    const nextLabel = typeof labelOverride === 'string' ? labelOverride : editState.labelInput;
    const trimmed = nextLabel.trim();
    if (!trimmed) {
      setError(__('Provide a label before saving.', 'alt-context'));
      return;
    }

    const currentLabel = cluster.label ?? '';
    if (currentLabel && trimmed.toLowerCase() === currentLabel.toLowerCase()) {
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
      // Use cached match if available and still valid, otherwise fetch
      let match = matchedCluster;
      if (!match || match.label.toLowerCase() !== trimmed.toLowerCase()) {
        match = await findClusterByLabel(trimmed, abortController.signal);
      }
      
      if (abortController.signal.aborted) {
        return;
      }

      if (match && match.label.toLowerCase() === (cluster.label ?? '').toLowerCase()) {
        // No change
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
        // New label
        if (editableClusterId) {
          // Regular cluster with ID: rename
          mutationStarted = true;
          mutations.rename(trimmed, abortController.signal);
        } else if (anchorIdentityId) {
          // No cluster ID: create cluster for this identity
          // (handles both singletons and unclustered identities)
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
  };

  // Handle "Wrong person" action
  const handleWrongPerson = () => {
    if (
      window.confirm(
        __(
          'Are you sure this is not the correct person? This will remove these items from the cluster.',
          'alt-context',
        ),
      )
    ) {
      // Send only representative ID per requirements (backend will handle cluster implications)
      if (representative?.identity_id) {
        mutations.reassign([representative.identity_id]);
      }
    }
  };

  // Handle "Split cluster" action
  const handleSplit = () => {
    if (!cluster.clusterId) {
      return;
    }

    if (cluster.members.length < 2) {
      setError(__('Need at least two identities to split.', 'alt-context'));
      return;
    }
    setIsAnchorModalOpen(true);
  };

  const handleAnchorSelect = React.useCallback(
    (selectedIdentityId: string) => {
      if (!cluster.clusterId) {
        return;
      }
      mutations.split(cluster.clusterId, 2, selectedIdentityId);
    },
    [cluster.clusterId, mutations],
  );

  const confirmDialogCopy = React.useMemo(() => {
    if (!confirmDialog) {
      return null;
    }

    const fallbackLabel = __('this cluster', 'alt-context');
    const labelText = confirmDialog.label || fallbackLabel;
    const isAssign = confirmDialog.action === 'assign';
    return {
      title: isAssign ? __('Assign identity', 'alt-context') : __('Confirm merge', 'alt-context'),
      description: isAssign
        ? sprintf(__('Assign this identity to "%s"?', 'alt-context'), labelText)
        : sprintf(__('Merge this cluster into existing "%s"?', 'alt-context'), labelText),
      confirmLabel: isAssign ? __('Assign', 'alt-context') : __('Merge', 'alt-context'),
    };
  }, [confirmDialog]);

  const saveLabel = React.useMemo(() => {
    if (saveStatus === 'queued') return __('Saving…', 'alt-context');
    if (saveStatus === 'saved') return __('Saved!', 'alt-context');
    if (matchedCluster) {
      return canSearchForMatch
        ? sprintf(__('Assign to %s', 'alt-context'), matchedCluster.label)
        : sprintf(__('Merge with %s', 'alt-context'), matchedCluster.label);
    }
    return undefined;
  }, [saveStatus, matchedCluster, canSearchForMatch]);

  return (
    <div className={`acx-identity-cluster ${editState.isEditing ? 'acx-identity-cluster--editing' : ''}`}>
      <ClusterPreview representative={representative} memberCount={cluster.members.length} />

      <div className="acx-identity-cluster__info">
        {!editState.isEditing ? (
          <>
            {canEdit || canSearchForMatch ? (
              <button
                type="button"
                className="acx-identity-cluster__label acx-identity-cluster__label--action"
                onClick={startEditing}
              >
                {labelText}
              </button>
            ) : (
              <span className="acx-identity-cluster__label">{labelText}</span>
            )}
            <ClusterActions
              canEdit={canEdit}
              canSearchForMatch={canSearchForMatch}
              hasLabel={Boolean(cluster.label)}
              isAutoLabel={cluster.isAutoLabel}
              canSplit={Boolean(cluster.clusterId)}
              canReject={isSingleton || cluster.members.length === 1}
              isPending={mutations.isPending}
              onEdit={startEditing}
              onWrongPerson={handleWrongPerson}
              onSplit={handleSplit}
            />
            {/* Show inline "Is this X?" prompt for unlabeled items */}
            {!cluster.label && anchorIdentityId && (
              <InlineSuggestionPrompt
                identityId={anchorIdentityId}
                onConfirm={handleConfirmSuggestion}
                onReject={startEditing}
                isPending={mutations.isPending}
              />
            )}
          </>
        ) : (
          <ClusterEditForm
            labelInput={editState.labelInput}
            onLabelChange={setLabel}
            options={options}
            isLoading={suggestionsLoading}
            isPending={mutations.isPending || saveStatus !== 'idle'}
            onSave={(labelOverride) => void handleSave(labelOverride)}
            onConfirmSuggestion={(clusterId, label) => void handleConfirmSuggestion(clusterId, label)}
            onCancel={handleCancel}
            onRejectSuggestion={(suggestionId) => mutations.rejectSuggestion(suggestionId)}
            saveLabel={saveLabel}
          />
        )}
      </div>

      {editState.lastMerge && (
        <MergeUndoBanner
          mergeResult={editState.lastMerge}
          isReverting={mutations.isReverting}
          onUndo={() => mutations.revertMerge(editState.lastMerge!)}
        />
      )}

      {editState.error && <p className="acx-identity-cluster__error">{editState.error}</p>}

      <DebugMetricsPanel metrics={representative?.debug_metrics} />

      <AnchorSelectionModal
        isOpen={isAnchorModalOpen}
        label={cluster.label}
        members={cluster.members}
        onClose={() => setIsAnchorModalOpen(false)}
        onSelectAnchor={handleAnchorSelect}
      />

      {confirmDialog && confirmDialogCopy && (
        <DialogRoot open={confirmDialog.open} onOpenChange={handleConfirmDialogOpenChange}>
          <DialogPortal>
            <DialogOverlay />
            <DialogContent>
              <div className="acx-queue-modal">
                <DialogTitle>{confirmDialogCopy.title}</DialogTitle>
                <DialogDescription>{confirmDialogCopy.description}</DialogDescription>
                <div className="acx-queue-modal__actions">
                  <button type="button" className="button" onClick={handleConfirmCancel}>
                    {__('Cancel', 'alt-context')}
                  </button>
                  <button type="button" className="button button-primary" onClick={handleConfirmAccept}>
                    {confirmDialogCopy.confirmLabel}
                  </button>
                </div>
              </div>
            </DialogContent>
          </DialogPortal>
        </DialogRoot>
      )}
    </div>
  );
};
