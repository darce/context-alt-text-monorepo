/**
 * ClusterLabelingPanel
 *
 * UI for labeling a cluster with a name, showing a grid of member faces for verification.
 * Naming options come from the shared person∪cluster union; duplicates block pre-save.
 */

import React, { useMemo, useRef, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { __, sprintf } from '@wordpress/i18n';

import {
  fetchClusterMembers,
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
import { useRosterEntries } from '../../../hooks/useRosterHooks';
import {
  buildNamingOptions,
  findCollisionsForLabel,
  parseNamingOptionValue,
  uniqueClusterCollisionTarget,
  unwrapClusterOptionId,
  type NamingOption,
} from './buildNamingOptions';
import { getProjectionNotReadyMessage, isProjectionNotReadyError } from './clusterMutationUtils';
import { MergeUndoBanner } from './MergeUndoBanner';
import { invalidateSuggestionProjection } from './suggestionProjection';

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

const isDedicatedFaceThumbUrl = (thumbUrl: string | null | undefined): boolean => {
  return typeof thumbUrl === 'string' && thumbUrl.includes('recognition/face-thumbs/');
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
  /** Combobox calls onValueChange after onSelect; skip clearing the guard for that echo. */
  const skipGuardClearOnNextValueRef = useRef(false);
  const queryClient = useQueryClient();

  const handleLabelSuccess = (label: string) => {
    setError(null);
    setDuplicateGuard(null);
    setAllowRenameAnyway(false);
    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
    void invalidateSuggestionProjection(queryClient);
    onLabel(label);
  };

  const handleMergeSuccess = (result: MergeClusterResponse) => {
    setError(null);
    setDuplicateGuard(null);
    setAllowRenameAnyway(false);
    setLastMerge(result);
    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
    void invalidateSuggestionProjection(queryClient);
  };

  const { data: membersResponse, isLoading } = useQuery({
    queryKey: queryKeys.clusters.memberList(clusterId),
    queryFn: () => fetchClusterMembers(clusterId),
    enabled: Boolean(clusterId),
  });
  const members = membersResponse?.members ?? [];

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
        labelMatches: labeledClusters,
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
        group: 'All Labels',
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = labelInput.trim();
    if (!trimmed) {
      return;
    }
    setError(null);

    if (!allowRenameAnyway) {
      const guard = evaluateDuplicateGuard(trimmed);
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

  return (
    <div className="acx-cluster-labeling-panel">
      <div className="acx-cluster-labeling-panel__header">
        <h2>{__('Name this person', 'alt-context')}</h2>
        <button type="button" className="acx-close-button" onClick={onClose} aria-label={__('Close', 'alt-context')}>
          ×
        </button>
      </div>

      <div className="acx-cluster-labeling-panel__content">
        <div className="acx-cluster-labeling-panel__grid">
          {isLoading ? (
            <p>{__('Loading faces...', 'alt-context')}</p>
          ) : members.length > 0 ? (
            members.map((member) => (
              <div key={member.identity_id} className="acx-cluster-labeling-panel__face">
                {member.thumb_url && isDedicatedFaceThumbUrl(member.thumb_url) ? (
                  <Avatar src={member.thumb_url} size="lg" alt={__('Face to label', 'alt-context')} />
                ) : member.media_url && member.bbox ? (
                  <FaceThumbnail
                    mediaUrl={member.media_url}
                    bbox={member.bbox}
                    size="lg"
                    alt={__('Face to label', 'alt-context')}
                  />
                ) : member.thumb_url ? (
                  <Avatar src={member.thumb_url} size="lg" alt={__('Face to label', 'alt-context')} />
                ) : (
                  <div className="acx-face-thumbnail acx-face-thumbnail--placeholder" />
                )}
              </div>
            ))
          ) : (
            <p>{__('No members found.', 'alt-context')}</p>
          )}
        </div>

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
              {mergeTargetId && mergeTargetLabel && (
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
              )}
              <div className="acx-cluster-labeling-panel__suggestion-actions">
                {mergeTargetId && mergeTargetLabel ? (
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
