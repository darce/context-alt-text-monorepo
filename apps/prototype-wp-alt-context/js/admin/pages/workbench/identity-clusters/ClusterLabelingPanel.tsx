/**
 * ClusterLabelingPanel
 *
 * UI for labeling a cluster with a name, showing a grid of member faces for verification.
 * Naming options come from the shared person∪cluster union; duplicates block pre-save.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { __, sprintf } from '@wordpress/i18n';

import {
  listRecognitionClusters,
  mergeCluster,
  revertMergeCluster,
  updateClusterLabel,
  type MergeClusterResponse,
} from '../../../api/recognition';
import { commitClusterToRosterEntry } from '../../../api/rosterApi';
import { queryKeys } from '../../../api/queryKeys';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import { Avatar } from '../../../../components/ui/avatar';
import type { ComboboxOption } from '../../../../components/ui/combobox';
import { isCroppableBbox } from '../../../../components/ui/faceGeometry';
import { unavailableImageName } from '../../../../components/ui/faceThumbDisplay';
import { EmptyState, EmptyStateVariant } from '../../../components/ui/EmptyState';
import { isDedicatedFaceThumbUrl } from '../../../../components/ui/isDedicatedFaceThumbUrl';
import { useRosterEntries } from '../../../hooks/useRosterHooks';
import {
  buildNamingOptions,
  findCollisionsForLabel,
  NAMING_GROUP_ALL_LABELS,
  namingOptionValue,
  uniqueClusterCollisionTarget,
  unwrapClusterOptionId,
  type NamingOption,
} from './buildNamingOptions';
import { NameFaceControl, normalizeNameFaceLabel, type NameFaceResolution } from './NameFaceControl';
import { getReservedLabelMessage, isReservedLabel } from './reservedLabel';
import { getClusterMutationUserError, type ClusterMutationRecovery } from './clusterMutationUtils';
import { MergeUndoBanner } from './MergeUndoBanner';
import {
  dropClusterFromReviewCaches,
  invalidateReviewCachesWithoutRefetch,
  invalidateSuggestionProjection,
  isHumanLabeledTarget,
  REVIEW_DROP_MODE,
} from './suggestionProjection';
import { useShowAllClusterMembers } from './useShowAllClusterMembers';

interface ClusterLabelingPanelProps {
  clusterId: string;
  onClose: () => void;
  onLabel: (label: string) => void;
  /** Prefill the name field (roster name + Enter binds; UXW2-3-R1-08c). */
  initialLabel?: string;
}

interface DuplicateGuardState {
  readonly label: string;
  readonly collisions: readonly NamingOption[];
  readonly mergeTarget: NamingOption | null;
}

type PanelErrorState = {
  readonly message: string;
  readonly recovery: ClusterMutationRecovery;
};

const SAVE_TIMEOUT_MS = 3000;

const withTimeout = async <T,>(request: (signal: AbortSignal) => Promise<T>, timeoutMs: number): Promise<T> => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await request(controller.signal);
  } finally {
    window.clearTimeout(timeoutId);
  }
};

const ClusterMutationErrorAlert = ({ error }: { error: PanelErrorState }): React.JSX.Element => (
  <div className="acx-cluster-labeling-panel__error" role="alert">
    <p>{error.message}</p>
    {error.recovery === 'reload' ? (
      <button type="button" className="button" onClick={() => window.location.reload()}>
        {__('Reload page', 'alt-context')}
      </button>
    ) : null}
  </div>
);

export const ClusterLabelingPanel = ({
  clusterId,
  onClose,
  onLabel,
  initialLabel = '',
}: ClusterLabelingPanelProps): React.JSX.Element => {
  const [labelInput, setLabelInput] = useState(initialLabel);
  const [error, setError] = useState<PanelErrorState | null>(null);
  const [duplicateGuard, setDuplicateGuard] = useState<DuplicateGuardState | null>(null);
  const [allowRenameAnyway, setAllowRenameAnyway] = useState(false);
  const [lastMerge, setLastMerge] = useState<MergeClusterResponse | null>(null);
  const [showAllAnnouncement, setShowAllAnnouncement] = useState<string | null>(null);
  const memberGridRef = useRef<HTMLDivElement | null>(null);
  const wasExpandingRef = useRef(false);
  const submittingRef = useRef(false);
  const rosterRetryRef = useRef<HTMLButtonElement | null>(null);
  const duplicateGuardFirstActionRef = useRef<HTMLButtonElement | null>(null);
  const queryClient = useQueryClient();

  // Reset panel-local state when the labeled cluster changes (FIX-4). key= at call site remounts;
  // this effect covers non-key remounts / prop-only updates.
  useEffect(() => {
    setLabelInput(initialLabel);
    setError(null);
    setDuplicateGuard(null);
    setAllowRenameAnyway(false);
    setLastMerge(null);
    setShowAllAnnouncement(null);
  }, [clusterId, initialLabel]);

  const handleLabelSuccess = (label: string) => {
    setError(null);
    setDuplicateGuard(null);
    setAllowRenameAnyway(false);
    // UXW2-2 (B6): the labelled cluster's pending rows leave the review caches
    // now — backend suggestion curation lags the label write.
    dropClusterFromReviewCaches(queryClient, clusterId, { mode: REVIEW_DROP_MODE.LABEL });
    invalidateReviewCachesWithoutRefetch(queryClient);
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities(), refetchType: 'none' });
    void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
    onLabel(label);
  };

  const handleMergeSuccess = (result: MergeClusterResponse) => {
    setError(null);
    setDuplicateGuard(null);
    setAllowRenameAnyway(false);
    setLastMerge(result);
    // UXW2-2-R1-21: drop the authoritative retired source, not the local panel id.
    if (typeof result.source_id === 'string' && result.source_id !== '') {
      dropClusterFromReviewCaches(queryClient, result.source_id, { mode: REVIEW_DROP_MODE.MERGE });
    }
    invalidateReviewCachesWithoutRefetch(queryClient);
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities(), refetchType: 'none' });
  };

  const { members, isLoading, isError, truncated, total, isFullyLoaded, isExpanding, expandError, showAll, refetch } =
    useShowAllClusterMembers(clusterId);
  const memberPositions = useMemo(() => {
    const positions: number[] = [];
    const memberIndexesByMedia = new Map<number, number[]>();

    members.forEach((member, memberIndex) => {
      const mediaMemberIndexes = memberIndexesByMedia.get(member.media_id) ?? [];
      mediaMemberIndexes.push(memberIndex);
      memberIndexesByMedia.set(member.media_id, mediaMemberIndexes);
    });

    memberIndexesByMedia.forEach((memberIndexes) => {
      memberIndexes
        .sort((leftIndex, rightIndex) => {
          const leftX = members[leftIndex]?.bbox?.x;
          const rightX = members[rightIndex]?.bbox?.x;
          const leftHasPosition = Number.isFinite(leftX);
          const rightHasPosition = Number.isFinite(rightX);

          if (
            leftHasPosition &&
            rightHasPosition &&
            typeof leftX === 'number' &&
            typeof rightX === 'number' &&
            leftX !== rightX
          ) {
            return leftX - rightX;
          }
          if (leftHasPosition !== rightHasPosition) {
            return leftHasPosition ? -1 : 1;
          }
          return leftIndex - rightIndex;
        })
        .forEach((memberIndex, positionIndex) => {
          positions[memberIndex] = positionIndex + 1;
        });
    });

    return positions;
  }, [members]);

  // AT affordance: when expansion completes the show-all button unmounts, so
  // announce completion and move focus to the member grid before it drops.
  useEffect(() => {
    if (wasExpandingRef.current && !isExpanding && isFullyLoaded && !expandError) {
      setShowAllAnnouncement(
        sprintf(
          /* translators: %d: total member count */
          __('All %d members shown', 'alt-context'),
          total,
        ),
      );
      memberGridRef.current?.focus();
    }
    wasExpandingRef.current = isExpanding;
  }, [isExpanding, isFullyLoaded, expandError, total]);

  const {
    data: persons = [],
    isLoading: rosterLoading,
    isError: rosterError,
    refetch: refetchRoster,
  } = useRosterEntries();

  useEffect(() => {
    if (rosterError) {
      rosterRetryRef.current?.focus();
    }
  }, [rosterError]);

  useEffect(() => {
    if (duplicateGuard) {
      duplicateGuardFirstActionRef.current?.focus();
    }
  }, [duplicateGuard]);

  // Labeled clusters for the union (shared builder; debounced free-text still uses persons + full list).
  const { data: labeledClusters = [] } = useQuery({
    queryKey: queryKeys.clusters.labelSearch(labelInput.trim().length >= 2 ? labelInput.trim() : ''),
    queryFn: () =>
      listRecognitionClusters({
        limit: 20,
        offset: 0,
        labeled_only: true,
        search: labelInput.trim().length >= 2 ? labelInput.trim() : undefined,
      }),
    select: (response) => response.clusters,
    staleTime: 30000,
  });

  const { options: namingOptions, collisionsByLabel } = useMemo(
    () =>
      buildNamingOptions({
        rosterEntries: rosterError ? [] : persons,
        // ClusterSummary.label is runtime-nullable (BR-46); naming entries require a string.
        labelMatches: labeledClusters.filter(
          (cluster): cluster is typeof cluster & { label: string } =>
            typeof cluster.label === 'string' && cluster.label.trim() !== '',
        ),
        filter: labelInput,
        excludeClusterId: clusterId,
      }),
    [persons, rosterError, labeledClusters, labelInput, clusterId],
  );

  const comboboxOptions: ComboboxOption[] = useMemo(
    () =>
      namingOptions.map((option) => ({
        value: option.value,
        label: option.label,
        source: option.source,
        identityCount: option.identityCount,
        group: NAMING_GROUP_ALL_LABELS,
      })),
    [namingOptions],
  );

  // Full unfiltered union for create-vs-bind (UXW2-3-R1-07). Displayed options
  // stay filter-before-slice; resolution must not inherit that truncation.
  const resolutionOptions: ComboboxOption[] = useMemo(
    () =>
      buildNamingOptions({
        rosterEntries: rosterError ? [] : persons,
        labelMatches: labeledClusters.filter(
          (cluster): cluster is typeof cluster & { label: string } =>
            typeof cluster.label === 'string' && cluster.label.trim() !== '',
        ),
        limit: null,
        excludeClusterId: clusterId,
      }).options.map((option) => ({
        value: option.value,
        label: option.label,
        source: option.source,
        identityCount: option.identityCount,
        group: NAMING_GROUP_ALL_LABELS,
      })),
    [persons, rosterError, labeledClusters, clusterId],
  );

  const labelMutation = useMutation({
    mutationFn: (newLabel: string) =>
      withTimeout((signal) => updateClusterLabel(clusterId, newLabel, signal), SAVE_TIMEOUT_MS),
    retry: false,
    onSuccess: (_result, newLabel) => handleLabelSuccess(newLabel),
  });

  const bindMutation = useMutation({
    mutationFn: ({ rosterEntryId }: { rosterEntryId: number; name: string }) =>
      withTimeout((_signal) => commitClusterToRosterEntry({ clusterId, rosterEntryId }), SAVE_TIMEOUT_MS),
    retry: false,
    onSuccess: (result, variables) => handleLabelSuccess(result.person_name ?? variables.name),
  });

  const mergeMutation = useMutation({
    mutationFn: ({ targetClusterId, targetLabel }: { targetClusterId: string; targetLabel: string }) =>
      mergeCluster(clusterId, targetClusterId, targetLabel),
    retry: false,
    onSuccess: (result) => handleMergeSuccess(result),
    onError: (err: unknown) => {
      setError(getClusterMutationUserError(err, labelInput));
    },
  });

  const revertMutation = useMutation({
    mutationFn: (payload: MergeClusterResponse) =>
      revertMergeCluster({
        targetClusterId: payload.target_id,
        movedIdentityIds: payload.moved_identity_ids,
        sourceLabel: payload.source_label,
      }),
    retry: false,
    onSuccess: () => {
      setLastMerge(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void invalidateSuggestionProjection(queryClient);
    },
    onError: (err: unknown) => {
      setError(getClusterMutationUserError(err, labelInput));
    },
  });

  const evaluateDuplicateGuard = (trimmed: string): DuplicateGuardState | null => {
    const collisions = findCollisionsForLabel(collisionsByLabel, trimmed, clusterId);
    if (collisions.length === 0) {
      return null;
    }
    return {
      label: trimmed,
      collisions,
      mergeTarget: uniqueClusterCollisionTarget(collisions),
    };
  };

  /**
   * When the local collision set is empty/pending (limit 20, disabled <2 chars),
   * look up an exact remote labeled match so free-text create cannot silent-dupe (FIX-8).
   * Collision is raw case-insensitive equality (BR-42) — not isHumanLabeledTarget —
   * so backend-labeled machine shapes (e.g. cluster-auto-1) still arm the guard.
   */
  const evaluateRemoteDuplicateGuard = async (trimmed: string): Promise<DuplicateGuardState | null> => {
    try {
      const results = await listRecognitionClusters({
        search: trimmed,
        limit: 10,
        labeled_only: true,
      });
      const normalized = trimmed.toLowerCase();
      const match = results.clusters.find(
        (cluster) =>
          cluster.id !== clusterId && typeof cluster.label === 'string' && cluster.label.toLowerCase() === normalized,
      );
      if (!match?.id || !match.label) {
        return null;
      }
      const remoteOption: NamingOption = {
        value: namingOptionValue('cluster', match.id),
        label: match.label,
        source: 'cluster',
        identityCount: typeof match.identity_count === 'number' ? match.identity_count : undefined,
      };
      return {
        label: trimmed,
        collisions: [remoteOption],
        mergeTarget: remoteOption,
      };
    } catch {
      return null;
    }
  };

  const isBusy = labelMutation.isPending || mergeMutation.isPending || bindMutation.isPending;

  const submitLabel = async (
    rawLabel: string,
    options?: { skipPersonOnlyGuard?: boolean; skipDuplicateGuard?: boolean; rosterEntryId?: number },
  ) => {
    const trimmed = rawLabel.trim();
    if (!trimmed) {
      return;
    }
    if (submittingRef.current || isBusy) {
      return;
    }
    submittingRef.current = true;
    setError(null);

    try {
      // BR-46: reject machine-shaped / reserved auto-ID labels before any remote guard call.
      if (isReservedLabel(trimmed)) {
        setError({ message: getReservedLabelMessage(), recovery: 'none' });
        return;
      }

      if (!allowRenameAnyway && !options?.skipDuplicateGuard) {
        const localGuard = evaluateDuplicateGuard(trimmed);
        const skipPersonOnly = Boolean(options?.skipPersonOnlyGuard && localGuard && !localGuard.mergeTarget);
        if (localGuard && !skipPersonOnly) {
          setDuplicateGuard(localGuard);
          return;
        }
        const remoteGuard = await evaluateRemoteDuplicateGuard(trimmed);
        if (remoteGuard) {
          setDuplicateGuard(remoteGuard);
          return;
        }
      }

      setDuplicateGuard(null);
      setAllowRenameAnyway(false);

      try {
        if (typeof options?.rosterEntryId === 'number') {
          await bindMutation.mutateAsync({ rosterEntryId: options.rosterEntryId, name: trimmed });
        } else {
          await labelMutation.mutateAsync(trimmed);
        }
      } catch (err) {
        setError(getClusterMutationUserError(err, trimmed));
      }
    } finally {
      submittingRef.current = false;
    }
  };

  const resolveCommit = (resolution: NameFaceResolution): void => {
    if (resolution.kind === 'ambiguous') {
      return;
    }
    const folded = normalizeNameFaceLabel(resolution.name);
    const hasClusterCollision = comboboxOptions.some(
      (option) => option.source === 'cluster' && normalizeNameFaceLabel(option.label) === folded,
    );
    const rosterEntryId = resolution.kind === 'roster' ? resolution.rosterEntryId : undefined;
    if (resolution.kind === 'roster' && !hasClusterCollision) {
      void submitLabel(resolution.name, { skipPersonOnlyGuard: true, rosterEntryId });
      return;
    }
    void submitLabel(resolution.name, { rosterEntryId });
  };

  const clearError = () => {
    if (error) {
      setError(null);
    }
  };

  const handleTypedValueChange = (value: string) => {
    setLabelInput(value);
    setAllowRenameAnyway(false);
    clearError();
    if (duplicateGuard) {
      setDuplicateGuard(null);
    }
  };

  const handleOptionConfirm = (option: ComboboxOption): void => {
    handleSelectOption(String(option.value));
  };

  const handleSelectOption = (optionValue: string): void => {
    const matched = comboboxOptions.find((option) => option.value === optionValue);
    if (!matched) {
      return;
    }
    setLabelInput(matched.label);
    setAllowRenameAnyway(false);
    clearError();

    // Cluster selection primes the duplicate guard so merge is explicit (INT-07).
    const clusterIdFromValue = unwrapClusterOptionId(optionValue);
    if (clusterIdFromValue && matched.source === 'cluster') {
      const collisions = findCollisionsForLabel(collisionsByLabel, matched.label, clusterId);
      setDuplicateGuard({
        label: matched.label,
        collisions:
          collisions.length > 0
            ? collisions
            : [
                {
                  value: matched.value,
                  label: matched.label,
                  source: 'cluster',
                  identityCount: matched.identityCount as number | undefined,
                },
              ],
        mergeTarget: {
          value: matched.value,
          label: matched.label,
          source: 'cluster',
          identityCount: matched.identityCount as number | undefined,
        },
      });
      return;
    }
    setDuplicateGuard(null);
  };

  const mergeTargetId = duplicateGuard?.mergeTarget ? unwrapClusterOptionId(duplicateGuard.mergeTarget.value) : null;
  const mergeTargetLabel = duplicateGuard?.mergeTarget?.label;
  const mergeTargetCount = duplicateGuard?.mergeTarget?.identityCount;
  // BR-66 / BR-58: outcome-sample copy must match the merge button predicate — never advertise
  // a merge that the machine-labeled-target guard suppresses.
  const canOfferMerge =
    Boolean(mergeTargetId) &&
    typeof mergeTargetLabel === 'string' &&
    mergeTargetLabel.length > 0 &&
    isHumanLabeledTarget(mergeTargetLabel);

  if (lastMerge) {
    return (
      <div className="acx-cluster-labeling-panel">
        <div className="acx-cluster-labeling-panel__header">
          <h2>{__('Name this person', 'alt-context')}</h2>
          <button
            type="button"
            className="acx-close-button"
            onClick={() => {
              onLabel(lastMerge.target_label ?? labelInput);
              onClose();
            }}
            aria-label={__('Close', 'alt-context')}
          >
            ×
          </button>
        </div>
        <div className="acx-cluster-labeling-panel__content">
          <MergeUndoBanner
            mergeResult={lastMerge}
            isReverting={revertMutation.isPending}
            onUndo={() => revertMutation.mutate(lastMerge)}
          />
          <div className="acx-cluster-labeling-panel__input-group">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                onLabel(lastMerge.target_label ?? labelInput);
              }}
            >
              {__('Done', 'alt-context')}
            </button>
          </div>
          {error ? <ClusterMutationErrorAlert error={error} /> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="acx-cluster-labeling-panel">
      <div className="acx-cluster-labeling-panel__header">
        <h2>{__('Name this person', 'alt-context')}</h2>
        <button type="button" className="acx-close-button" onClick={onClose} aria-label={__('Close', 'alt-context')}>
          ×
        </button>
      </div>

      <div className="acx-cluster-labeling-panel__content">
        <div className="acx-cluster-labeling-panel__grid" ref={memberGridRef} tabIndex={-1}>
          {isLoading ? (
            <p>{__('Loading faces...', 'alt-context')}</p>
          ) : isError ? (
            <div className="acx-cluster-labeling-panel__error" role="alert" data-testid="acx-cluster-members-error">
              <p>{__('Unable to load these faces.', 'alt-context')}</p>
              <button type="button" className="button" onClick={() => refetch()}>
                {__('Retry', 'alt-context')}
              </button>
            </div>
          ) : members.length > 0 ? (
            members.map((member, memberIndex) => {
              const memberAlt = sprintf(
                __('Face %1$d in media %2$d', 'alt-context'),
                memberPositions[memberIndex] ?? memberIndex + 1,
                member.media_id,
              );

              return (
                <div key={member.identity_id} className="acx-cluster-labeling-panel__face">
                  {member.thumb_url && isDedicatedFaceThumbUrl(member.thumb_url) ? (
                    <Avatar src={member.thumb_url} size="lg" alt={memberAlt} />
                  ) : member.media_url && isCroppableBbox(member.bbox) ? (
                    <FaceThumbnail mediaUrl={member.media_url} bbox={member.bbox} size="lg" alt={memberAlt} />
                  ) : member.thumb_url ? (
                    <Avatar src={member.thumb_url} size="lg" alt={memberAlt} />
                  ) : (
                    <div
                      className="acx-cluster-labeling-panel__face-unavailable"
                      role="img"
                      aria-label={unavailableImageName(memberAlt)}
                    >
                      <span className="acx-cluster-labeling-panel__face-unavailable-label">
                        {__('No image', 'alt-context')}
                      </span>
                    </div>
                  )}
                </div>
              );
            })
          ) : (
            <EmptyState
              variant={EmptyStateVariant.EMPTY}
              heading={__('No faces available to name', 'alt-context')}
              body={__('Return to the review suggestions and choose another face group.', 'alt-context')}
              action={{ label: __('Back to review suggestions', 'alt-context'), onClick: onClose }}
              headingLevel={3}
            />
          )}
        </div>
        <p className="acx-cluster-members-show-all__announce" role="status" aria-live="polite">
          {showAllAnnouncement}
        </p>
        {truncated && !isFullyLoaded ? (
          <div className="acx-cluster-members-show-all">
            <button
              type="button"
              className="button acx-cluster-members-show-all__button"
              onClick={() => {
                void showAll();
              }}
              disabled={isExpanding}
              data-truncated={truncated ? 'true' : 'false'}
              data-total={total}
            >
              {isExpanding
                ? __('Loading all members…', 'alt-context')
                : sprintf(
                    /* translators: %d: total member count */
                    __('Show all (%d)', 'alt-context'),
                    total,
                  )}
            </button>
            {expandError ? (
              <p className="acx-cluster-members-show-all__error" role="alert">
                {expandError}
              </p>
            ) : null}
          </div>
        ) : null}

        <div className="acx-cluster-labeling-panel__form">
          {rosterError ? (
            <div className="acx-cluster-labeling-panel__failure" role="alert">
              <p className="acx-cluster-labeling-panel__failure-message">
                {__('Unable to load people. Retry before naming someone new.', 'alt-context')}
              </p>
              <button
                ref={rosterRetryRef}
                type="button"
                className="button acx-cluster-labeling-panel__retry"
                onClick={() => {
                  void refetchRoster();
                }}
              >
                {__('Retry', 'alt-context')}
              </button>
            </div>
          ) : (
            <>
              <label htmlFor="cluster-label-input">{__('Name', 'alt-context')}</label>
              <NameFaceControl
                options={comboboxOptions}
                resolutionOptions={resolutionOptions}
                value={labelInput}
                onValueChange={handleTypedValueChange}
                onCommit={resolveCommit}
                onOptionConfirm={handleOptionConfirm}
                isPending={isBusy}
                isLoading={rosterLoading}
                inputDisabled={mergeMutation.isPending}
                disabled={mergeMutation.isPending}
                commitLabel={__('Save name', 'alt-context')}
                pendingLabel={
                  mergeMutation.isPending ? __('Merging...', 'alt-context') : __('Saving...', 'alt-context')
                }
                placeholder={__('Enter name...', 'alt-context')}
                searchPlaceholder={__('Enter name...', 'alt-context')}
                inputId="cluster-label-input"
                autoFocus={false}
                suggestionsHeader={labelInput.trim() ? __('Matches', 'alt-context') : __('Suggested', 'alt-context')}
                className="acx-cluster-labeling-panel__input-group"
                classPrefix="acx-cluster-labeling-panel"
              />
            </>
          )}

          {duplicateGuard && (
            <div
              className="acx-cluster-labeling-panel__duplicate-guard"
              role="group"
              aria-labelledby="acx-cluster-labeling-panel-duplicate-guard-label"
            >
              <p
                id="acx-cluster-labeling-panel-duplicate-guard-label"
                className="acx-cluster-labeling-panel__suggestion-text"
              >
                {sprintf(
                  __('A name matching "%s" already exists. Choose how to proceed.', 'alt-context'),
                  duplicateGuard.label,
                )}
              </p>
              {canOfferMerge ? (
                <p className="acx-cluster-labeling-panel__outcome-sample">
                  {typeof mergeTargetCount === 'number'
                    ? sprintf(
                        /* translators: 1: cluster label, 2: member count */
                        __('Merge target: group "%1$s" (%2$d members)', 'alt-context'),
                        mergeTargetLabel,
                        mergeTargetCount,
                      )
                    : sprintf(
                        /* translators: %s: cluster label */
                        __('Merge target: group "%s"', 'alt-context'),
                        mergeTargetLabel,
                      )}
                </p>
              ) : null}
              <div className="acx-cluster-labeling-panel__suggestion-actions">
                {canOfferMerge && mergeTargetId ? (
                  <button
                    ref={duplicateGuardFirstActionRef}
                    type="button"
                    className="button button-primary"
                    disabled={isBusy}
                    onClick={() =>
                      mergeMutation.mutate({
                        targetClusterId: mergeTargetId,
                        targetLabel: mergeTargetLabel,
                      })
                    }
                  >
                    {sprintf(
                      /* translators: %s: target cluster label */
                      __('Merge into group "%s"', 'alt-context'),
                      mergeTargetLabel,
                    )}
                  </button>
                ) : null}
                <button
                  ref={canOfferMerge && mergeTargetId ? undefined : duplicateGuardFirstActionRef}
                  type="button"
                  className="button"
                  disabled={isBusy}
                  onClick={() => {
                    setAllowRenameAnyway(true);
                    setDuplicateGuard(null);
                    void submitLabel(duplicateGuard.label, { skipDuplicateGuard: true });
                  }}
                >
                  {__('Rename anyway', 'alt-context')}
                </button>
                <button
                  type="button"
                  className="button"
                  disabled={isBusy}
                  onClick={() => {
                    setDuplicateGuard(null);
                    setAllowRenameAnyway(false);
                  }}
                >
                  {__('Cancel', 'alt-context')}
                </button>
              </div>
            </div>
          )}
          {error ? <ClusterMutationErrorAlert error={error} /> : null}
        </div>
      </div>
    </div>
  );
};
