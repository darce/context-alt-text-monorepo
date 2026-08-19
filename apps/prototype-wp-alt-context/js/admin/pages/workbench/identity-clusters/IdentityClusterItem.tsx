/**
 * Single identity cluster item with edit, merge, and action capabilities.
 */

import React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { __, sprintf } from '@wordpress/i18n';

import { queryKeys } from '../../../api/queryKeys';
import type { MergeClusterResponse } from '../../../api/recognition';
import { commitClusterToRosterEntry } from '../../../api/rosterApi';
import { getClusterMutationErrorMessage } from './clusterMutationUtils';
import { invalidateSuggestionProjection, type ProjectedSuggestion } from './suggestionProjection';
import type { ClusterGroup } from './types';
import { filterEditableClusterMatch, formatClusterLabel, getEditableClusterId } from './utils';
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
import { ClusterConfirmDialog } from './ClusterConfirmDialog';
import { useClusterConfirmDialog } from './useClusterConfirmDialog';
import { useClusterSaveHandlers } from './useClusterSaveHandlers';
import { useClusterSaveStatus } from './useClusterSaveStatus';
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from '../../../../components/ui/dialog';

const MATCH_DEBOUNCE_MS = 300;

interface IdentityClusterItemProps {
  cluster: ClusterGroup;
  canLabel?: boolean;
  canMutate?: boolean;
  /** Top server-ranked inline suggestion for this cluster's anchor identity. */
  inlineSuggestionMatch?: ProjectedSuggestion;
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
export const IdentityClusterItem = ({
  cluster,
  canLabel = true,
  canMutate = true,
  inlineSuggestionMatch,
}: IdentityClusterItemProps): React.JSX.Element => {
  // Compute derived values
  const derivedLabel = React.useMemo(
    () => formatClusterLabel(cluster.clusterId, cluster.label, cluster.isAutoLabel),
    [cluster.clusterId, cluster.label, cluster.isAutoLabel],
  );

  const editableClusterId = React.useMemo(() => getEditableClusterId(cluster), [cluster]);

  // For singletons without a cluster, we still allow naming/merging via identity ID
  const isSingleton = !editableClusterId && cluster.members.length === 1;
  const canEdit = canLabel && Boolean(editableClusterId) && !cluster.clusteringPending;
  const canSearchForMatch = canLabel && isSingleton && !cluster.clusteringPending;

  // Show "Processing..." when clustering hasn't run yet, otherwise "Unnamed person"
  const labelText = cluster.clusteringPending
    ? __('Processing...', 'alt-context')
    : (derivedLabel ?? __('Unnamed person', 'alt-context'));

  const representative = cluster.members[0];
  const anchorIdentityId = representative?.identity_id;

  // Inline "Is this X?" prompt renders only for unlabeled, mutable clusters.
  // The match is fetched once at the list level (batched) and supplied by prop.
  const showInlinePrompt = Boolean(!cluster.label && anchorIdentityId && canMutate);

  const [isAnchorModalOpen, setIsAnchorModalOpen] = React.useState(false);
  const [isWrongPersonDialogOpen, setIsWrongPersonDialogOpen] = React.useState(false);
  const [matchedCluster, setMatchedCluster] = React.useState<{ id: string; label: string } | null>(null);
  const saveAbortRef = React.useRef<AbortController | null>(null);
  const matchAbortRef = React.useRef<AbortController | null>(null);

  const queryClient = useQueryClient();
  const { saveStatus, resetSaveStatus, queueSaveStatus, markSaveSuccess } = useClusterSaveStatus();
  const {
    confirmDialog,
    confirmDialogCopy,
    requestConfirm,
    handleOpenChange: handleConfirmDialogOpenChange,
    handleConfirm: handleConfirmAccept,
    handleCancel: handleConfirmCancel,
  } = useClusterConfirmDialog();

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
    atRestTotal = 0,
    atRestTruncated = false,
    isAtRestMode = false,
  } = useClusterSuggestions({
    identityId: anchorIdentityId,
    enabled: editState.isEditing,
    editableClusterId,
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
    onAbort: resetSaveStatus,
  });

  const bindToRosterEntry = React.useCallback(
    (rosterEntryId: number, label: string, _signal?: AbortSignal) => {
      if (!editableClusterId) {
        handleMutationError(__('Cannot bind this person: missing group.', 'alt-context'));
        return;
      }
      void commitClusterToRosterEntry({ clusterId: editableClusterId, rosterEntryId })
        .then(() => {
          void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
          void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.labels() });
          void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
          void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
          void invalidateSuggestionProjection(queryClient);
          handleSaveSuccess();
        })
        .catch((error: unknown) => {
          handleMutationError(getClusterMutationErrorMessage(error, label));
        });
    },
    [editableClusterId, handleMutationError, handleSaveSuccess, queryClient],
  );

  const { handleCancel, handleConfirmSuggestion, handleSave, handlePersonSelect } = useClusterSaveHandlers({
    clusterLabel: cluster.label,
    members: cluster.members,
    editableClusterId,
    anchorIdentityId,
    canEdit,
    canSearchForMatch,
    labelInput: editState.labelInput,
    matchedCluster,
    options,
    saveStatus,
    mutations: {
      isPending: mutations.isPending,
      merge: mutations.merge,
      assignToCluster: mutations.assignToCluster,
      rename: mutations.rename,
      createClusterForIdentity: mutations.createClusterForIdentity,
      bindToRosterEntry,
    },
    findClusterByLabel,
    requestConfirm,
    cancelEditing,
    setError,
    queueSaveStatus,
    resetSaveStatus,
    saveAbortRef,
  });

  React.useEffect(() => {
    return () => {
      saveAbortRef.current?.abort();
      matchAbortRef.current?.abort();
    };
  }, []);

  // Proactive matching while typing
  React.useEffect(() => {
    // Bail paths must abort any in-flight lookup so a late response cannot re-arm
    // matchedCluster after we cleared it (UXP-3-BR-45).
    const abortInFlightMatch = () => {
      matchAbortRef.current?.abort();
      matchAbortRef.current = null;
    };

    if (!editState.isEditing) {
      abortInFlightMatch();
      setMatchedCluster(null);
      return;
    }

    const trimmed = editState.labelInput.trim();
    const currentLabel = cluster.label ?? '';
    // Exact bail (B6 / UXP-3-BR-39): case-only edits must still run proactive match so
    // "bob"→"Bob" against a different "Bob" cluster arms the Merge-with preview.
    if (!trimmed || trimmed === currentLabel) {
      abortInFlightMatch();
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
          // Mirror save-path BR-40: remote exact-dupe (match.label === currentLabel) renames,
          // so the preview must not promise Merge/Assign (UXP-3-BR-44).
          const filtered = filterEditableClusterMatch(match, editableClusterId);
          setMatchedCluster(filtered?.label === currentLabel ? null : filtered);
        }
      } catch {
        // Ignore
      }
    };

    const timer = window.setTimeout(() => void runMatch(), MATCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [editState.isEditing, editState.labelInput, cluster.label, findClusterByLabel, editableClusterId]);

  // Handle "Wrong person" action
  const handleWrongPerson = () => {
    if (!representative?.identity_id) {
      return;
    }

    setIsWrongPersonDialogOpen(true);
  };

  const handleCancelWrongPerson = () => {
    setIsWrongPersonDialogOpen(false);
  };

  const handleConfirmWrongPerson = () => {
    if (representative?.identity_id) {
      // Send only representative ID per requirements (backend will handle cluster implications).
      mutations.reassign([representative.identity_id]);
    }

    setIsWrongPersonDialogOpen(false);
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
    [cluster, mutations],
  );

  const saveLabel = React.useMemo(() => {
    if (saveStatus === 'queued') {
      return __('Saving…', 'alt-context');
    }
    if (saveStatus === 'saved') {
      return __('Saved!', 'alt-context');
    }
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
            {cluster.clusteringPending ? (
              <span className="acx-identity-cluster__label acx-identity-cluster__label--processing">{labelText}</span>
            ) : canEdit || canSearchForMatch ? (
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
            {!cluster.clusteringPending && (
              <ClusterActions
                canEdit={canEdit}
                canSearchForMatch={canSearchForMatch}
                hasLabel={Boolean(cluster.label)}
                isAutoLabel={cluster.isAutoLabel}
                canSplit={canMutate && Boolean(cluster.clusterId)}
                canReject={canMutate && (isSingleton || cluster.members.length === 1)}
                isPending={mutations.isPending}
                splitDisabled={mutations.splitGate.disabled}
                splitTitle={mutations.splitGate.title}
                splitAriaDisabled={mutations.splitGate['aria-disabled']}
                onEdit={startEditing}
                onWrongPerson={handleWrongPerson}
                onSplit={handleSplit}
              />
            )}
            {/* Show inline "Is this X?" prompt for unlabeled items */}
            {showInlinePrompt && (
              <InlineSuggestionPrompt
                match={inlineSuggestionMatch}
                onConfirm={(clusterId, label, suggestionId) =>
                  void handleConfirmSuggestion(clusterId, label, suggestionId)
                }
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
            onPersonSelect={handlePersonSelect}
            onConfirmSuggestion={(clusterId, label, suggestionId) =>
              void handleConfirmSuggestion(clusterId, label, suggestionId)
            }
            onCancel={handleCancel}
            onRejectSuggestion={(suggestionId) => mutations.rejectSuggestion(suggestionId)}
            saveLabel={saveLabel}
            atRestTotal={atRestTotal}
            atRestTruncated={atRestTruncated}
            isAtRestMode={isAtRestMode}
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

      {editState.error && (
        <p className="acx-identity-cluster__error" role="alert">
          {editState.error}
        </p>
      )}

      <DebugMetricsPanel metrics={representative?.debug_metrics} />

      <AnchorSelectionModal
        isOpen={isAnchorModalOpen}
        label={cluster.label}
        members={cluster.members}
        onClose={() => setIsAnchorModalOpen(false)}
        onSelectAnchor={handleAnchorSelect}
      />

      <DialogRoot
        open={isWrongPersonDialogOpen}
        onOpenChange={(open) => {
          if (!open) {
            handleCancelWrongPerson();
          }
        }}
      >
        <DialogPortal>
          <DialogOverlay />
          <DialogContent>
            <div className="acx-queue-modal">
              <DialogTitle>{__('Remove this face from the group', 'alt-context')}</DialogTitle>
              <DialogDescription>
                {__('Remove this face from the group?', 'alt-context')}
              </DialogDescription>
              <div className="acx-queue-modal__actions">
                <button type="button" className="button" onClick={handleCancelWrongPerson}>
                  {__('Cancel', 'alt-context')}
                </button>
                <button type="button" className="button button-primary" onClick={handleConfirmWrongPerson}>
                  {__('Remove member', 'alt-context')}
                </button>
              </div>
            </div>
          </DialogContent>
        </DialogPortal>
      </DialogRoot>

      <ClusterConfirmDialog
        dialog={confirmDialog}
        copy={confirmDialogCopy}
        onOpenChange={handleConfirmDialogOpenChange}
        onConfirm={handleConfirmAccept}
        onCancel={handleConfirmCancel}
      />
    </div>
  );
};
