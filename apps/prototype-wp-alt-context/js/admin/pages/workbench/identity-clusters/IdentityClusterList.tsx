/**
 * List of identity clusters for a media item.
 *
 * This is the main entry point component that groups identities by cluster
 * and renders each cluster as an editable item.
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { DATA_SOURCE, type DataSource } from '../../../api/recognition/types';
import { type DetectedIdentity, type MergeClusterResponse } from '../../../api/recognition';
import { EmptyState, EmptyStateVariant } from '../../../components/ui/EmptyState';
import { APP_LINK_VALUES, toWorkbench } from '../../../navigation/appLinks';
import { ClusterActions } from './ClusterActions';
import { ClusterConfirmDialog } from './ClusterConfirmDialog';
import { ClusterEditForm } from './ClusterEditForm';
import { ClusterPreview } from './ClusterPreview';
import { EmptyStateWarning } from './EmptyStateWarning';
import { InlineSuggestionPrompt } from './InlineSuggestionPrompt';
import { MergeUndoBanner } from './MergeUndoBanner';
import { pendingMergeTwinForCluster } from './pendingMergeTwin';
import { isMeaningfulMergeLabel } from './resolveMergeSurvivor';
import { TWIN_CHIP_PENDING_STATUS } from './twinChipCopy';
import {
  filterEditableClusterMatch,
  groupIdentitiesByClusters,
  isUngroupedGroup,
  unlabeledSuggestionBatchIds,
} from './utils';
import { IdentityClusterItem } from './IdentityClusterItem';
import { useClusterConfirmDialog } from './useClusterConfirmDialog';
import { useClusterEditState } from './useClusterEditState';
import { useClusterMutations } from './useClusterMutations';
import { useClusterSaveHandlers } from './useClusterSaveHandlers';
import { useClusterSaveStatus } from './useClusterSaveStatus';
import { useClusterSuggestions } from './useClusterSuggestions';
import { useInlineSuggestionBatch, type InlineSuggestionBatchResult } from './useInlineSuggestionBatch';
import { usePendingMergeTwins } from './usePendingMergeTwins';

const MATCH_DEBOUNCE_MS = 300;

interface IdentityClusterListProps {
  /** Detected identities to display */
  identities: DetectedIdentity[];
  dataSource?: DataSource;
  isLoading?: boolean;
  onRetry?: () => void;
}

interface UngroupedResidueSectionProps {
  members: DetectedIdentity[];
  canMutate: boolean;
  getMatch: InlineSuggestionBatchResult['getMatch'];
}

interface UngroupedResidueFaceProps {
  member: DetectedIdentity;
  canMutate: boolean;
  getMatch: InlineSuggestionBatchResult['getMatch'];
}

interface UngroupedResidueEditorProps {
  member: DetectedIdentity;
  onClose: () => void;
}

/**
 * Singleton naming editor for one residue face.
 *
 * Reuses IdentityClusterItem's edit hooks + ClusterEditForm so Find similar /
 * Name opens the same combobox path a cluster_id-null singleton used, without
 * mounting an Unnamed person card (C5).
 */
const UngroupedResidueEditor = ({ member, onClose }: UngroupedResidueEditorProps): React.JSX.Element => {
  const members = React.useMemo(() => [member], [member]);
  const anchorIdentityId = member.identity_id;
  const canSearchForMatch = !member.clustering_pending;
  const [matchedCluster, setMatchedCluster] = React.useState<{ id: string; label: string } | null>(null);
  const saveAbortRef = React.useRef<AbortController | null>(null);
  const matchAbortRef = React.useRef<AbortController | null>(null);
  const revertAbortRef = React.useRef<AbortController | null>(null);

  const { saveStatus, resetSaveStatus, queueSaveStatus, markSaveSuccess } = useClusterSaveStatus();
  const {
    confirmDialog,
    confirmDialogCopy,
    requestConfirm,
    handleOpenChange: handleConfirmDialogOpenChange,
    handleConfirm: handleConfirmAccept,
    handleCancel: handleConfirmCancel,
  } = useClusterConfirmDialog();
  const {
    state: editState,
    startEditing,
    cancelEditing,
    setLabel,
    setError,
    onSaveSuccess,
    onMergeSuccess,
    onRevertSuccess,
  } = useClusterEditState({ derivedLabel: null });

  const closeEditor = React.useCallback(() => {
    cancelEditing();
    onClose();
  }, [cancelEditing, onClose]);

  const handleSaveSuccess = React.useCallback(() => {
    saveAbortRef.current = null;
    markSaveSuccess(() => {
      onSaveSuccess();
      onClose();
    });
  }, [markSaveSuccess, onClose, onSaveSuccess]);

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

  const {
    options,
    isLoading: suggestionsLoading,
    findClusterByLabel,
    atRestTotal = 0,
    atRestTruncated = false,
    isAtRestMode = false,
  } = useClusterSuggestions({
    identityId: anchorIdentityId,
    enabled: true,
    editableClusterId: null,
    labelInput: editState.labelInput,
  });

  const mutations = useClusterMutations({
    clusterId: null,
    identityCount: 1,
    currentLabel: null,
    derivedLabel: null,
    onRenameSuccess: handleSaveSuccess,
    onMergeSuccess: handleMergeSuccess,
    onRevertSuccess,
    onError: handleMutationError,
    onAbort: resetSaveStatus,
  });

  const { handleCancel, handleConfirmSuggestion, handleSave, handlePersonSelect } = useClusterSaveHandlers({
    clusterLabel: null,
    members,
    editableClusterId: null,
    anchorIdentityId,
    canEdit: false,
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
    },
    findClusterByLabel,
    requestConfirm,
    cancelEditing: closeEditor,
    setError,
    queueSaveStatus,
    resetSaveStatus,
    saveAbortRef,
  });

  React.useLayoutEffect(() => {
    startEditing();
  }, [startEditing]);

  React.useEffect(() => {
    return () => {
      saveAbortRef.current?.abort();
      matchAbortRef.current?.abort();
      revertAbortRef.current?.abort();
    };
  }, []);

  React.useEffect(() => {
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
    if (!trimmed) {
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
          setMatchedCluster(filterEditableClusterMatch(match, null));
        }
      } catch {
        // Ignore lookup failures; save still runs a fresh match.
      }
    };

    const timer = window.setTimeout(() => void runMatch(), MATCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [editState.isEditing, editState.labelInput, findClusterByLabel]);

  const saveLabel = React.useMemo(() => {
    if (saveStatus === 'queued') {
      return __('Saving…', 'alt-context');
    }
    if (saveStatus === 'saved') {
      return __('Saved!', 'alt-context');
    }
    if (matchedCluster) {
      return sprintf(__('Assign to %s', 'alt-context'), matchedCluster.label);
    }
    return undefined;
  }, [matchedCluster, saveStatus]);

  const handleUndoMerge = React.useCallback(() => {
    const payload = editState.lastMerge;
    if (!payload) {
      return;
    }
    revertAbortRef.current?.abort();
    const controller = new AbortController();
    revertAbortRef.current = controller;
    mutations.revertMerge(payload, controller.signal);
  }, [editState.lastMerge, mutations]);

  return (
    <div className="acx-identity-clusters__ungrouped-editor">
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
      {editState.lastMerge && (
        <MergeUndoBanner
          mergeResult={editState.lastMerge}
          isReverting={mutations.isReverting}
          onUndo={handleUndoMerge}
        />
      )}
      {editState.error && (
        <p className="acx-identity-cluster__error" role="alert">
          {editState.error}
        </p>
      )}
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

const UngroupedResidueFace = ({
  member,
  canMutate,
  getMatch,
}: UngroupedResidueFaceProps): React.JSX.Element => {
  const [isNaming, setIsNaming] = React.useState(false);
  const startNaming = React.useCallback(() => {
    setIsNaming(true);
  }, []);
  const stopNaming = React.useCallback(() => {
    setIsNaming(false);
  }, []);
  const mutations = useClusterMutations({
    clusterId: null,
    identityCount: 1,
    currentLabel: null,
    derivedLabel: null,
  });

  return (
    <li className="acx-identity-clusters__ungrouped-face">
      <ClusterPreview
        representative={member}
        representativeFace={member.representative_face}
        memberCount={1}
      />
      {isNaming ? (
        <UngroupedResidueEditor member={member} onClose={stopNaming} />
      ) : (
        <>
          {!member.clustering_pending && (
            <ClusterActions
              canEdit={false}
              canSearchForMatch
              hasLabel={false}
              isAutoLabel={false}
              canSplit={false}
              canReject={false}
              isPending={mutations.isPending}
              onEdit={startNaming}
              onWrongPerson={() => undefined}
              onSplit={() => undefined}
            />
          )}
          {canMutate ? (
            <InlineSuggestionPrompt
              match={getMatch(member.identity_id)}
              onConfirm={(clusterId, _label, suggestionId) => {
                mutations.assignToCluster(member.identity_id, clusterId, undefined, suggestionId);
              }}
              onReject={startNaming}
              isPending={mutations.isPending}
            />
          ) : null}
        </>
      )}
    </li>
  );
};

const UngroupedResidueSection = ({
  members,
  canMutate,
  getMatch,
}: UngroupedResidueSectionProps): React.JSX.Element => {
  const headingId = React.useId();
  const heading = sprintf(__('Not yet grouped (%d)', 'alt-context'), members.length);

  return (
    <section className="acx-identity-clusters__ungrouped" aria-labelledby={headingId}>
      <h3 id={headingId} className="acx-identity-clusters__ungrouped-heading">
        {heading}
      </h3>
      <ul className="acx-identity-clusters__ungrouped-faces">
        {members.map((member) => (
          <UngroupedResidueFace
            key={member.identity_id}
            member={member}
            canMutate={canMutate}
            getMatch={getMatch}
          />
        ))}
      </ul>
    </section>
  );
};

/**
 * Groups identities by cluster and renders them as a list of editable items.
 *
 * Each cluster shows:
 * - Representative thumbnail with member count
 * - Label (editable via Combobox with suggestions)
 * - Actions: Edit, Wrong person, Split
 *
 * NOTE: v4.12.0 - CurateTopClustersPrompt removed; naming queue is now in
 * ReviewQueue for unified curation flow.
 */
export const IdentityClusterList = ({
  identities,
  dataSource,
  isLoading,
  onRetry,
}: IdentityClusterListProps): React.JSX.Element => {
  const clusters = React.useMemo(() => groupIdentitiesByClusters(identities), [identities]);
  const identityGroups = React.useMemo(
    () => clusters.filter((cluster) => !isUngroupedGroup(cluster)),
    [clusters],
  );
  const ungroupedGroup = React.useMemo(
    () => clusters.find((cluster) => isUngroupedGroup(cluster)),
    [clusters],
  );
  const isLabelOnly = dataSource === DATA_SOURCE.BACKEND_PROXY;
  const canMutate = !isLabelOnly;
  const { mergeSuggestions, truncated, scheduleAcceptMerge, scheduleRejectMerge, isCardPending } =
    usePendingMergeTwins();

  // Same unlabeled predicate as IdentityClusterItem's prompt gate, plus every
  // residue member: grouping changes presentation only, never the batch (rg-002).
  const batchIdentityIds = React.useMemo(() => {
    if (!canMutate) {
      return [];
    }
    return unlabeledSuggestionBatchIds(clusters);
  }, [clusters, canMutate]);

  const { getMatch } = useInlineSuggestionBatch(batchIdentityIds);

  if (clusters.length === 0 && isLoading) {
    return (
      <p className="acx-identity-clusters__empty" aria-busy="true">
        {__('Loading faces…', 'alt-context')}
      </p>
    );
  }

  if (clusters.length === 0) {
    if (dataSource === DATA_SOURCE.UNAVAILABLE) {
      return (
        <EmptyStateWarning
          title={__('Identity data unavailable', 'alt-context')}
          message={__('We could not load identities for this media item right now.', 'alt-context')}
          onRetry={onRetry}
        />
      );
    }

    // BR-05: a reachable-but-erroring backend (endpoint_error) is a distinct
    // honest state from offline (unavailable) — say so instead of falling through
    // to a confident "none detected".
    if (dataSource === DATA_SOURCE.ENDPOINT_ERROR) {
      return (
        <EmptyStateWarning
          title={__('Identity data unavailable', 'alt-context')}
          message={__('Recognition is reachable but returned an error. Please retry.', 'alt-context')}
          onRetry={onRetry}
        />
      );
    }

    // BR-09: an empty local projection for this item is ambiguous between
    // "analyzed, none found" and "not yet analyzed". The offline projection
    // cannot assert a final scan result, so present it as pending sync rather
    // than a confident "none detected". Only a backend_proxy (or unknown) empty
    // result — where recognition was actually reached — is a confident "none".
    if (dataSource === DATA_SOURCE.LOCAL_PROJECTION) {
      return (
        <p className="acx-identity-clusters__empty">
          {__('No identities synced for this item yet.', 'alt-context')}
        </p>
      );
    }

    return (
      <EmptyState
        variant={EmptyStateVariant.EMPTY}
        heading={__('No identities detected yet.', 'alt-context')}
        body={__('Scan media to find faces in this item.', 'alt-context')}
        action={{ label: __('Go to Scan', 'alt-context'), href: toWorkbench({ tab: 'scan' }) }}
        headingLevel={3}
        announceState={false}
      />
    );
  }

  return (
    <div className="acx-identity-clusters">
      {isLabelOnly && (
        <p className="acx-identity-clusters__notice">
          {__(
            'Names can be curated now. Split/remove actions stay disabled until local sync completes.',
            'alt-context',
          )}
        </p>
      )}
      {identityGroups.map((cluster) => {
        const twin = canMutate
          ? pendingMergeTwinForCluster(cluster.clusterId, mergeSuggestions)
          : null;
        const twinPending = twin
          ? isCardPending(twin.suggestionId, ['acceptMerge', 'rejectMerge'])
          : false;
        const showTruncatedReviewLink =
          truncated &&
          canMutate &&
          twin == null &&
          !isMeaningfulMergeLabel(cluster.label);
        return (
          <React.Fragment key={cluster.key}>
            <IdentityClusterItem
              cluster={cluster}
              canLabel
              canMutate={canMutate}
              inlineSuggestionMatch={getMatch(cluster.members[0]?.identity_id)}
              mergeTwin={
                twin
                  ? {
                      suggestionId: twin.suggestionId,
                      survivorClusterId: twin.survivorClusterId,
                      survivorLabel: twin.survivorLabel,
                      survivorMediaUrl: twin.survivorMediaUrl,
                      survivorBbox: twin.survivorBbox,
                      onAccept: () => {
                        void scheduleAcceptMerge(twin.suggestionId);
                      },
                      onReject: () => {
                        void scheduleRejectMerge(twin.suggestionId);
                      },
                      isPending: twinPending,
                      disabledReason: twinPending ? TWIN_CHIP_PENDING_STATUS : null,
                    }
                  : undefined
              }
            />
            {showTruncatedReviewLink ? (
              <a
                className="acx-identity-clusters__truncated-review"
                href={toWorkbench({ tab: 'scan', panel: APP_LINK_VALUES.panelReview })}
              >
                {__('Review pending merges', 'alt-context')}
              </a>
            ) : null}
          </React.Fragment>
        );
      })}
      {ungroupedGroup ? (
        <UngroupedResidueSection members={ungroupedGroup.members} canMutate={canMutate} getMatch={getMatch} />
      ) : null}
    </div>
  );
};
