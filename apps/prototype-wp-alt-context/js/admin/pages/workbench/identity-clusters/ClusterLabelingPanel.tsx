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
import { queryKeys } from '../../../api/queryKeys';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import { Avatar } from '../../../../components/ui/avatar';
import { Combobox, type ComboboxOption } from '../../../../components/ui/combobox';
import { isCroppableBbox } from '../../../../components/ui/faceGeometry';
import { unavailableImageName } from '../../../../components/ui/faceThumbDisplay';
import { isDedicatedFaceThumbUrl } from '../../../../components/ui/isDedicatedFaceThumbUrl';
import { useRosterEntries } from '../../../hooks/useRosterHooks';
import {
  buildNamingOptions,
  findCollisionsForLabel,
  NAMING_GROUP_ALL_LABELS,
  namingOptionValue,
  parseNamingOptionValue,
  uniqueClusterCollisionTarget,
  unwrapClusterOptionId,
  type NamingOption,
} from './buildNamingOptions';
import { formatUserFacingError, isAuthExpiredError } from '../../../utils/userFacingError';
import { getProjectionNotReadyMessage, isProjectionNotReadyError } from './clusterMutationUtils';
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
}

interface DuplicateGuardState {
  readonly label: string;
  readonly collisions: readonly NamingOption[];
  readonly mergeTarget: NamingOption | null;
}

/**
 * Parse API error response to extract user-friendly message.
 */
const getErrorMessage = (error: unknown): string => {
  if (isAuthExpiredError(error)) {
    return formatUserFacingError(error, __('An unexpected error occurred. Please try again.', 'alt-context'));
  }
  if (error instanceof Error) {
    if (
      error.name === 'AbortError' ||
      error.message.toLowerCase().includes('timed out') ||
      error.message.toLowerCase().includes('timeout')
    ) {
      return __('Save is taking too long. Please try again.', 'alt-context');
    }
    if (isProjectionNotReadyError(error.message)) {
      return getProjectionNotReadyMessage();
    }
    // Check for network errors
    if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
      return __('Network error. Please check your connection and try again.', 'alt-context');
    }
    return error.message;
  }
  return __('An unexpected error occurred. Please try again.', 'alt-context');
};

const SAVE_TIMEOUT_MS = 3000;

const withTimeout = async <T,>(
  request: (signal: AbortSignal) => Promise<T>,
  timeoutMs: number,
  timeoutMessage: string,
): Promise<T> => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(timeoutMessage), timeoutMs);
  try {
    return await request(controller.signal);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(timeoutMessage);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
};

const renderNamingOption = (option: ComboboxOption): React.ReactNode => {
  const source =
    option.source === 'person' || option.source === 'cluster'
      ? option.source
      : parseNamingOptionValue(String(option.value))?.source;
  const sourceLabel = source === 'person' ? __('Person', 'alt-context') : __('Cluster', 'alt-context');
  return (
    <span className="acx-naming-option">
      <span className="acx-naming-option__label">{option.label}</span>
      {source && (
        <span className={`acx-badge acx-badge--source acx-badge--source-${source}`} data-source={source}>
          {sourceLabel}
        </span>
      )}
    </span>
  );
};

export const ClusterLabelingPanel = ({ clusterId, onClose, onLabel }: ClusterLabelingPanelProps): React.JSX.Element => {
  const [labelInput, setLabelInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [duplicateGuard, setDuplicateGuard] = useState<DuplicateGuardState | null>(null);
  const [allowRenameAnyway, setAllowRenameAnyway] = useState(false);
  const [lastMerge, setLastMerge] = useState<MergeClusterResponse | null>(null);
  const [showAllAnnouncement, setShowAllAnnouncement] = useState<string | null>(null);
  const memberGridRef = useRef<HTMLDivElement | null>(null);
  const wasExpandingRef = useRef(false);
  /** Combobox calls onValueChange after onSelect; skip clearing the guard for that echo. */
  const skipGuardClearOnNextValueRef = useRef(false);
  const queryClient = useQueryClient();

  // Reset panel-local state when the labeled cluster changes (FIX-4). key= at call site remounts;
  // this effect covers non-key remounts / prop-only updates.
  useEffect(() => {
    setLabelInput('');
    setError(null);
    setDuplicateGuard(null);
    setAllowRenameAnyway(false);
    setLastMerge(null);
    setShowAllAnnouncement(null);
    skipGuardClearOnNextValueRef.current = false;
  }, [clusterId]);

  const handleLabelSuccess = (label: string) => {
    setError(null);
    setDuplicateGuard(null);
    setAllowRenameAnyway(false);
    // UXW2-2 (B6): the labelled cluster's pending rows leave the review caches
    // now — backend suggestion curation lags the label write.
    dropClusterFromReviewCaches(queryClient, clusterId, { mode: REVIEW_DROP_MODE.LABEL });
    invalidateReviewCachesWithoutRefetch(queryClient);
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities(), refetchType: 'none' });
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

  const {
    members,
    isLoading,
    isError,
    truncated,
    total,
    isFullyLoaded,
    isExpanding,
    expandError,
    showAll,
    refetch,
  } = useShowAllClusterMembers(clusterId);

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
    isSuccess: rosterSuccess,
  } = useRosterEntries();

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

  const resultCountAnnouncement = useMemo(() => {
    if (rosterLoading) {
      return __('Loading people…', 'alt-context');
    }
    if (rosterError) {
      return __('People list unavailable; showing labeled clusters only.', 'alt-context');
    }
    if (rosterSuccess && persons.length === 0 && namingOptions.length === 0) {
      return __('No naming options available.', 'alt-context');
    }
    return sprintf(
      /* translators: %d: number of naming options */
      __('%d naming options', 'alt-context'),
      namingOptions.length,
    );
  }, [rosterLoading, rosterError, rosterSuccess, persons.length, namingOptions.length]);

  const labelMutation = useMutation({
    mutationFn: (newLabel: string) =>
      withTimeout(
        (signal) => updateClusterLabel(clusterId, newLabel, signal),
        SAVE_TIMEOUT_MS,
        'save request timed out',
      ),
    retry: false,
    onSuccess: (_result, newLabel) => handleLabelSuccess(newLabel),
  });

  const mergeMutation = useMutation({
    mutationFn: ({ targetClusterId, targetLabel }: { targetClusterId: string; targetLabel: string }) =>
      mergeCluster(clusterId, targetClusterId, targetLabel),
    retry: false,
    onSuccess: (result) => handleMergeSuccess(result),
    onError: (err: Error) => {
      setError(getErrorMessage(err));
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
    onError: (err: Error) => {
      setError(getErrorMessage(err));
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
          cluster.id !== clusterId &&
          typeof cluster.label === 'string' &&
          cluster.label.toLowerCase() === normalized,
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = labelInput.trim();
    if (!trimmed) {
      return;
    }
    setError(null);

    // BR-46: reject machine-shaped / reserved auto-ID labels before any remote guard call.
    if (!isHumanLabeledTarget(trimmed)) {
      setError(
        __('This label format is reserved for automatic cluster IDs. Choose a descriptive name.', 'alt-context'),
      );
      return;
    }

    if (!allowRenameAnyway) {
      const localGuard = evaluateDuplicateGuard(trimmed);
      const guard = localGuard ?? (await evaluateRemoteDuplicateGuard(trimmed));
      if (guard) {
        setDuplicateGuard(guard);
        return;
      }
    }

    setDuplicateGuard(null);
    setAllowRenameAnyway(false);

    try {
      await labelMutation.mutateAsync(trimmed);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const clearError = () => {
    if (error) {
      setError(null);
    }
  };

  const handleTypedValueChange = (value: string) => {
    setLabelInput(value);
    if (skipGuardClearOnNextValueRef.current) {
      skipGuardClearOnNextValueRef.current = false;
      return;
    }
    setAllowRenameAnyway(false);
    clearError();
    if (duplicateGuard) {
      setDuplicateGuard(null);
    }
  };

  const handleSelectOption = (optionValue: string): void => {
    const matched = comboboxOptions.find((option) => option.value === optionValue);
    if (!matched) {
      return;
    }
    // Combobox also fires onValueChange(label) after onSelect — don't clear the guard we arm here.
    skipGuardClearOnNextValueRef.current = true;
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
              className="button button-primary"
              onClick={() => {
                onLabel(lastMerge.target_label ?? labelInput);
              }}
            >
              {__('Done', 'alt-context')}
            </button>
          </div>
          {error && (
            <p className="acx-cluster-labeling-panel__error" role="alert">
              {error}
            </p>
          )}
        </div>
      </div>
    );
  }

  const memberAlt = __('Face to label', 'alt-context');

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
              <p>{__('Unable to load cluster members.', 'alt-context')}</p>
              <button type="button" className="button" onClick={() => refetch()}>
                {__('Retry', 'alt-context')}
              </button>
            </div>
          ) : members.length > 0 ? (
            members.map((member) => (
              <div key={member.identity_id} className="acx-cluster-labeling-panel__face">
                {member.thumb_url && isDedicatedFaceThumbUrl(member.thumb_url) ? (
                  <Avatar src={member.thumb_url} size="lg" alt={memberAlt} />
                ) : member.media_url && isCroppableBbox(member.bbox) ? (
                  <FaceThumbnail
                    mediaUrl={member.media_url}
                    bbox={member.bbox}
                    size="lg"
                    alt={memberAlt}
                  />
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
            ))
          ) : (
            <p>{__('No members found.', 'alt-context')}</p>
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

        <form
          onSubmit={(event) => {
            void handleSubmit(event);
          }}
          className="acx-cluster-labeling-panel__form"
        >
          <label htmlFor="cluster-label-input">{__('Name', 'alt-context')}</label>
          <div className="acx-cluster-labeling-panel__input-group">
            <Combobox
              id="cluster-label-input"
              options={comboboxOptions}
              value={labelInput}
              onSelect={handleSelectOption}
              onValueChange={handleTypedValueChange}
              onCreate={handleTypedValueChange}
              placeholder={__('Enter name...', 'alt-context')}
              searchPlaceholder={__('Search people...', 'alt-context')}
              ariaLabel={__('Name', 'alt-context')}
              disabled={mergeMutation.isPending}
              isLoading={rosterLoading}
              renderOption={renderNamingOption}
            />
            <button
              type="submit"
              className="button button-primary"
              disabled={!labelInput.trim() || labelMutation.isPending || mergeMutation.isPending}
            >
              {labelMutation.isPending
                ? __('Saving...', 'alt-context')
                : mergeMutation.isPending
                  ? __('Merging...', 'alt-context')
                  : __('Save', 'alt-context')}
            </button>
          </div>

          <p className="acx-cluster-labeling-panel__result-count" role="status" aria-live="polite">
            {resultCountAnnouncement}
          </p>

          {duplicateGuard && (
            <div className="acx-cluster-labeling-panel__duplicate-guard" role="status" aria-live="polite">
              <p className="acx-cluster-labeling-panel__suggestion-text">
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
                        __('Merge target: cluster "%1$s" (%2$d members)', 'alt-context'),
                        mergeTargetLabel,
                        mergeTargetCount,
                      )
                    : sprintf(
                        /* translators: %s: cluster label */
                        __('Merge target: cluster "%s"', 'alt-context'),
                        mergeTargetLabel,
                      )}
                </p>
              ) : null}
              <div className="acx-cluster-labeling-panel__suggestion-actions">
                {canOfferMerge && mergeTargetId ? (
                  <button
                    type="button"
                    className="button button-primary"
                    disabled={mergeMutation.isPending || labelMutation.isPending}
                    onClick={() =>
                      mergeMutation.mutate({
                        targetClusterId: mergeTargetId,
                        targetLabel: mergeTargetLabel,
                      })
                    }
                  >
                    {sprintf(
                      /* translators: %s: target cluster label */
                      __('Merge into cluster "%s"', 'alt-context'),
                      mergeTargetLabel,
                    )}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="button"
                  disabled={mergeMutation.isPending || labelMutation.isPending}
                  onClick={() => {
                    setAllowRenameAnyway(true);
                    setDuplicateGuard(null);
                    void labelMutation.mutateAsync(duplicateGuard.label).catch((err: unknown) => {
                      setError(getErrorMessage(err));
                      setAllowRenameAnyway(false);
                    });
                  }}
                >
                  {__('Rename anyway', 'alt-context')}
                </button>
                <button
                  type="button"
                  className="button"
                  disabled={mergeMutation.isPending || labelMutation.isPending}
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
          {error && (
            <p className="acx-cluster-labeling-panel__error" role="alert">
              {error}
            </p>
          )}
        </form>
      </div>
    </div>
  );
};
