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
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../../components/ui/dialog';

interface IdentityClusterItemProps {
  cluster: ClusterGroup;
}

type SaveDialogStatus = 'queued' | 'saved' | 'error';
type SaveDialogAction = 'rename' | 'merge' | 'assign' | 'create';

interface SaveDialogState {
  open: boolean;
  status: SaveDialogStatus;
  action: SaveDialogAction;
  label: string;
  error?: string;
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
  const [isSaving, setIsSaving] = React.useState(false);
  const [saveDialog, setSaveDialog] = React.useState<SaveDialogState | null>(null);
  const saveAbortRef = React.useRef<AbortController | null>(null);

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

  const closeSaveDialog = React.useCallback(() => {
    setSaveDialog(null);
  }, []);

  const queueSaveDialog = React.useCallback((action: SaveDialogAction, label: string) => {
    setSaveDialog({
      open: true,
      status: 'queued',
      action,
      label,
    });
  }, []);

  const updateSaveDialog = React.useCallback((action: SaveDialogAction, label: string) => {
    setSaveDialog((prev) =>
      prev
        ? {
            ...prev,
            action,
            label,
          }
        : {
            open: true,
            status: 'queued',
            action,
            label,
          },
    );
  }, []);

  const markSaveSuccess = React.useCallback(() => {
    setSaveDialog((prev) => (prev ? { ...prev, status: 'saved', error: undefined } : prev));
  }, []);

  const markSaveError = React.useCallback((message: string) => {
    setSaveDialog((prev) =>
      prev
        ? { ...prev, status: 'error', error: message }
        : {
            open: true,
            status: 'error',
            action: 'rename',
            label: '',
            error: message,
          },
    );
  }, []);

  const handleSaveDialogOpenChange = React.useCallback(
    (open: boolean) => {
      if (!open) {
        closeSaveDialog();
      }
    },
    [closeSaveDialog],
  );

  React.useEffect(() => {
    if (saveDialog?.status !== 'saved') {
      return;
    }
    const timer = window.setTimeout(() => {
      setSaveDialog(null);
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [saveDialog?.status]);

  const handleSaveSuccess = React.useCallback(() => {
    saveAbortRef.current = null;
    onSaveSuccess();
    markSaveSuccess();
  }, [markSaveSuccess, onSaveSuccess]);

  const handleMergeSuccess = React.useCallback(
    (result: MergeClusterResponse) => {
      saveAbortRef.current = null;
      onMergeSuccess(result);
      markSaveSuccess();
    },
    [markSaveSuccess, onMergeSuccess],
  );

  const handleMutationError = React.useCallback(
    (message: string) => {
      saveAbortRef.current = null;
      setError(message);
      markSaveError(message);
    },
    [markSaveError, setError],
  );

  // Suggestions
  const {
    options,
    isLoading: suggestionsLoading,
    findClusterByLabel,
  } = useClusterSuggestions({
    identityId: anchorIdentityId,
    enabled: editState.isEditing,
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
    if (!mutations.isPending) {
      setIsSaving(false);
    }
  }, [mutations.isPending]);

  React.useEffect(() => () => saveAbortRef.current?.abort(), []);

  const handleCancel = React.useCallback(() => {
    if (saveAbortRef.current) {
      saveAbortRef.current.abort();
      saveAbortRef.current = null;
    }
    setIsSaving(false);
    closeSaveDialog();
    cancelEditing();
  }, [cancelEditing, closeSaveDialog]);

  // Callback for accepting inline suggestion prompt
  const handleSuggestionConfirm = React.useCallback(
    (clusterId: string) => {
      if (anchorIdentityId) {
        mutations.assignToCluster(anchorIdentityId, clusterId);
      }
    },
    [anchorIdentityId, mutations],
  );

  // Handle save (rename or merge)
  const handleSave = async (labelOverride?: string) => {
    if (isSaving || mutations.isPending) {
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

    queueSaveDialog('rename', trimmed);
    setIsSaving(true);
    let mutationStarted = false;
    try {
      const match = await findClusterByLabel(trimmed, abortController.signal);
      if (abortController.signal.aborted) {
        closeSaveDialog();
        return;
      }

      if (match && match.label.toLowerCase() === (cluster.label ?? '').toLowerCase()) {
        // No change
        cancelEditing();
        closeSaveDialog();
        return;
      }

      if (match) {
        // Label exists - merge or assign
        const action: SaveDialogAction = canSearchForMatch ? 'assign' : 'merge';
        updateSaveDialog(action, match.label);
        const confirmMessage = canSearchForMatch
          ? __('Assign this identity to "' + match.label + '"?', 'alt-context')
          : __('Merge this cluster into existing "' + match.label + '"?', 'alt-context');

        if (!window.confirm(confirmMessage)) {
          closeSaveDialog();
          return;
        }

        if (abortController.signal.aborted) {
          closeSaveDialog();
          return;
        }

        if (editableClusterId) {
          // Regular cluster: merge by cluster ID
          mutationStarted = true;
          mutations.merge(match.id, match.label, abortController.signal);
        } else {
          // No cluster ID: assign all members to target cluster
          // This handles both singletons and unclustered groups
          mutationStarted = true;
          for (const member of cluster.members) {
            mutations.assignToCluster(member.identity_id, match.id, abortController.signal);
          }
        }
      } else {
        // New label
        const action: SaveDialogAction = editableClusterId ? 'rename' : 'create';
        updateSaveDialog(action, trimmed);
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
          markSaveError(message);
        }
      }
    } catch (err) {
      if (err && typeof err === 'object' && 'name' in err && (err as { name: string }).name === 'AbortError') {
        closeSaveDialog();
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      markSaveError(message);
    } finally {
      if (!mutationStarted) {
        setIsSaving(false);
        saveAbortRef.current = null;
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

  const saveDialogCopy = React.useMemo(() => {
    if (!saveDialog) {
      return null;
    }

    const fallbackLabel = __('this change', 'alt-context');
    const labelText = saveDialog.label || fallbackLabel;
    const actionLabel = (() => {
      switch (saveDialog.action) {
        case 'merge':
          return sprintf(__('Merge into "%s"', 'alt-context'), labelText);
        case 'assign':
          return sprintf(__('Assign to "%s"', 'alt-context'), labelText);
        case 'create':
          return sprintf(__('Create "%s"', 'alt-context'), labelText);
        default:
          return sprintf(__('Save "%s"', 'alt-context'), labelText);
      }
    })();

    if (saveDialog.status === 'error') {
      return {
        title: __('Save failed', 'alt-context'),
        description:
          saveDialog.error || __('We could not save this change. Please try again.', 'alt-context'),
      };
    }

    if (saveDialog.status === 'saved') {
      return {
        title: __('Saved', 'alt-context'),
        description: sprintf(__('%s is saved.', 'alt-context'), actionLabel),
      };
    }

    return {
      title: __('Saving queued', 'alt-context'),
      description: sprintf(
        __('%s is queued. You can keep working while we save.', 'alt-context'),
        actionLabel,
      ),
    };
  }, [saveDialog]);

  return (
    <div className="acx-identity-cluster">
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
                onConfirm={handleSuggestionConfirm}
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
            isPending={mutations.isPending || isSaving}
            onSave={(labelOverride) => void handleSave(labelOverride)}
            onCancel={handleCancel}
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

      {saveDialog && saveDialogCopy && (
        <DialogRoot open={saveDialog.open} onOpenChange={handleSaveDialogOpenChange}>
          <DialogPortal>
            <DialogOverlay />
            <DialogContent>
              <div className="acx-queue-modal">
                <DialogTitle>{saveDialogCopy.title}</DialogTitle>
                <DialogDescription>{saveDialogCopy.description}</DialogDescription>
                <div className="acx-queue-modal__actions">
                  {saveDialog.status === 'queued' && (
                    <button type="button" className="button" onClick={handleCancel}>
                      {__('Cancel save', 'alt-context')}
                    </button>
                  )}
                  <DialogClose asChild>
                    <button type="button" className="button">
                      {__('Close', 'alt-context')}
                    </button>
                  </DialogClose>
                </div>
              </div>
            </DialogContent>
          </DialogPortal>
        </DialogRoot>
      )}
    </div>
  );
};
