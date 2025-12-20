/**
 * Single identity cluster item with edit, merge, and action capabilities.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

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

interface IdentityClusterItemProps {
  cluster: ClusterGroup;
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

  // Suggestions
  const {
    options,
    isLoading: suggestionsLoading,
    ensureLabels,
    findClusterIdByLabel,
  } = useClusterSuggestions({
    identityId: anchorIdentityId,
    enabled: editState.isEditing,
  });

  // Mutations
  const mutations = useClusterMutations({
    clusterId: editableClusterId,
    currentLabel: cluster.label,
    derivedLabel,
    onRenameSuccess: onSaveSuccess,
    onMergeSuccess,
    onRevertSuccess,
    onError: setError,
  });

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
  const handleSave = async () => {
    // Allow save for regular clusters with canEdit, or for singletons searching for matches
    if (!canEdit && !canSearchForMatch) {
      return;
    }

    const trimmed = editState.labelInput.trim();
    if (!trimmed) {
      setError(__('Provide a label before saving.', 'alt-context'));
      return;
    }

    // Ensure we have existing labels for merge detection
    const labels = await ensureLabels();
    const suggestionLabels = options.filter((opt) => opt.group === 'Suggested').map((opt) => opt.label);
    const allLabels = Array.from(new Set([...labels, ...suggestionLabels]));

    // Check if label exists (case-insensitive) to trigger merge/assign
    const targetLabel = allLabels.find((l) => l.toLowerCase() === trimmed.toLowerCase());

    if (targetLabel) {
      // Label exists - merge or assign
      if (targetLabel !== cluster.label) {
        const confirmMessage = canSearchForMatch
          ? __('Assign this identity to "' + targetLabel + '"?', 'alt-context')
          : __('Merge this cluster into existing "' + targetLabel + '"?', 'alt-context');

        if (window.confirm(confirmMessage)) {
          // Look up the target cluster ID by label
          const targetClusterId = await findClusterIdByLabel(targetLabel);

          if (!targetClusterId) {
            setError(__('Could not find cluster to assign to.', 'alt-context'));
            return;
          }

          // If we have a cluster ID, merge normally
          // Otherwise, assign identities to the target cluster
          if (editableClusterId) {
            // Regular cluster: merge by cluster ID
            mutations.merge(targetClusterId, targetLabel);
          } else {
            // No cluster ID: assign all members to target cluster
            // This handles both singletons and unclustered groups
            for (const member of cluster.members) {
              mutations.assignToCluster(member.identity_id, targetClusterId);
            }
          }
        }
      } else {
        // No change
        cancelEditing();
      }
    } else {
      // New label
      if (editableClusterId) {
        // Regular cluster with ID: rename
        mutations.rename(trimmed);
      } else if (anchorIdentityId) {
        // No cluster ID: create cluster for this identity
        // (handles both singletons and unclustered identities)
        mutations.createClusterForIdentity(anchorIdentityId, trimmed);
      } else {
        setError(__('Cannot create cluster: no identity ID', 'alt-context'));
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
      mutations.reassign(cluster.members.map((m) => m.identity_id));
    }
  };

  // Handle "Split cluster" action
  const handleSplit = () => {
    if (!cluster.clusterId) {
      return;
    }

    // Force split into at least 2 clusters when user explicitly requests it.
    // This ensures the split actually happens even if faces appear similar.
    // The hierarchical algorithm will find the best 2-way split.
    if (window.confirm(__('Split this cluster into 2 groups based on face similarity?', 'alt-context'))) {
      mutations.split(cluster.clusterId, 2);
    }
  };

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
            isPending={mutations.isPending}
            onSave={() => void handleSave()}
            onCancel={cancelEditing}
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
    </div>
  );
};
