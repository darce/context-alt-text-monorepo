/**
 * ClusterLabelingPanel
 *
 * UI for labeling a cluster with a name, showing a grid of member faces for verification.
 * Naming options come from the shared person∪cluster union; duplicates block pre-save.
 *
 * FEBT1G-M-14: the member grid, the duplicate-guard domain logic, the write orchestration
 * and the collision prompt live in sibling modules. What remains here is the naming form:
 * typed value, submit routing, and error surface.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { __ } from '@wordpress/i18n';

import { listRecognitionClusters } from '../../../api/recognition';
import { queryKeys } from '../../../api/queryKeys';
import type { ComboboxOption } from '../../../../components/ui/combobox';
import { useRosterEntries } from '../../../hooks/useRosterHooks';
import {
  buildNamingOptions,
  findCollisionsForLabel,
  NAMING_GROUP_ALL_LABELS,
  unwrapClusterOptionId,
  type NamingOption,
} from './buildNamingOptions';
import { NameFaceControl, normalizeNameFaceLabel, type NameFaceResolution } from './NameFaceControl';
import { getReservedLabelMessage, isReservedLabel } from './reservedLabel';
import { getClusterMutationErrorMessage } from './clusterMutationUtils';
import { getClusterLabelLookupFailedMessage } from './clusterLabelLookup';
import { ClusterLabelingDuplicatePrompt } from './ClusterLabelingDuplicatePrompt';
import { ClusterLabelingMemberGrid } from './ClusterLabelingMemberGrid';
import { MergeUndoBanner } from './MergeUndoBanner';
import { DUPLICATE_GUARD_OUTCOME, useClusterLabelingDuplicateGuard } from './useClusterLabelingDuplicateGuard';
import { useClusterLabelingMutations } from './useClusterLabelingMutations';

interface ClusterLabelingPanelProps {
  clusterId: string;
  onClose: () => void;
  onLabel: (label: string) => void;
  /** Prefill the name field (roster name + Enter binds; UXW2-3-R1-08c). */
  initialLabel?: string;
}

const LABEL_SEARCH_MIN_CHARS = 2;

const toComboboxOption = (option: NamingOption): ComboboxOption => ({
  value: option.value,
  label: option.label,
  source: option.source,
  identityCount: option.identityCount,
  group: NAMING_GROUP_ALL_LABELS,
});

export const ClusterLabelingPanel = ({
  clusterId,
  onClose,
  onLabel,
  initialLabel = '',
}: ClusterLabelingPanelProps): React.JSX.Element => {
  const [labelInput, setLabelInput] = useState(initialLabel);
  const [error, setError] = useState<string | null>(null);
  const submittingRef = useRef(false);
  const rosterRetryRef = useRef<HTMLButtonElement | null>(null);

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

  // Labeled clusters for the union (shared builder; debounced free-text still uses persons + full list).
  const trimmedInput = labelInput.trim();
  const searchTerm = trimmedInput.length >= LABEL_SEARCH_MIN_CHARS ? trimmedInput : '';
  const { data: labeledClusters = [] } = useQuery({
    queryKey: queryKeys.clusters.labelSearch(searchTerm),
    queryFn: () =>
      listRecognitionClusters({
        limit: 20,
        offset: 0,
        labeled_only: true,
        search: searchTerm === '' ? undefined : searchTerm,
      }),
    select: (response) => response.clusters,
    staleTime: 30000,
  });

  // ClusterSummary.label is runtime-nullable (BR-46); naming entries require a string.
  const namedClusters = useMemo(
    () =>
      labeledClusters.filter(
        (cluster): cluster is typeof cluster & { label: string } =>
          typeof cluster.label === 'string' && cluster.label.trim() !== '',
      ),
    [labeledClusters],
  );

  const { options: namingOptions, collisionsByLabel } = useMemo(
    () =>
      buildNamingOptions({
        rosterEntries: rosterError ? [] : persons,
        labelMatches: namedClusters,
        filter: labelInput,
        excludeClusterId: clusterId,
      }),
    [persons, rosterError, namedClusters, labelInput, clusterId],
  );

  const comboboxOptions: ComboboxOption[] = useMemo(() => namingOptions.map(toComboboxOption), [namingOptions]);

  // Full unfiltered union for create-vs-bind (UXW2-3-R1-07). Displayed options
  // stay filter-before-slice; resolution must not inherit that truncation.
  const resolutionOptions: ComboboxOption[] = useMemo(
    () =>
      buildNamingOptions({
        rosterEntries: rosterError ? [] : persons,
        labelMatches: namedClusters,
        limit: null,
        excludeClusterId: clusterId,
      }).options.map(toComboboxOption),
    [persons, rosterError, namedClusters, clusterId],
  );

  const guard = useClusterLabelingDuplicateGuard({ clusterId, collisionsByLabel });

  const resetGuard = guard.reset;

  const mutations = useClusterLabelingMutations({
    clusterId,
    onLabel,
    onWriteSuccess: () => {
      setError(null);
      resetGuard();
    },
    onError: (err: unknown) => setError(getClusterMutationErrorMessage(err, labelInput)),
  });

  const { clearLastMerge } = mutations;

  // Reset panel-local state when the labeled cluster changes (FIX-4). key= at call site
  // remounts; this effect covers non-key remounts / prop-only updates.
  useEffect(() => {
    setLabelInput(initialLabel);
    setError(null);
    resetGuard();
    clearLastMerge();
  }, [clusterId, initialLabel, resetGuard, clearLastMerge]);

  const submitLabel = async (
    rawLabel: string,
    options?: { skipPersonOnlyGuard?: boolean; skipDuplicateGuard?: boolean; rosterEntryId?: number },
  ) => {
    const trimmed = rawLabel.trim();
    if (!trimmed || submittingRef.current || mutations.isBusy) {
      return;
    }
    submittingRef.current = true;
    setError(null);

    try {
      // BR-46: reject machine-shaped / reserved auto-ID labels before any remote guard call.
      if (isReservedLabel(trimmed)) {
        setError(getReservedLabelMessage());
        return;
      }

      const outcome = await guard.evaluate(trimmed, options);
      if (outcome === DUPLICATE_GUARD_OUTCOME.LOOKUP_FAILED) {
        setError(getClusterLabelLookupFailedMessage());
        return;
      }
      if (outcome === DUPLICATE_GUARD_OUTCOME.BLOCKED) {
        return;
      }

      try {
        if (typeof options?.rosterEntryId === 'number') {
          await mutations.bindToRosterEntry({ rosterEntryId: options.rosterEntryId, name: trimmed });
        } else {
          await mutations.saveLabel(trimmed);
        }
      } catch (err) {
        setError(getClusterMutationErrorMessage(err, trimmed));
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
    clearError();
    guard.reset();
  };

  const handleSelectOption = (optionValue: string): void => {
    const matched = comboboxOptions.find((option) => option.value === optionValue);
    if (!matched) {
      return;
    }
    setLabelInput(matched.label);
    clearError();

    // Cluster selection primes the duplicate guard so merge is explicit (INT-07).
    const clusterIdFromValue = unwrapClusterOptionId(optionValue);
    if (clusterIdFromValue && matched.source === 'cluster') {
      const collisions = findCollisionsForLabel(collisionsByLabel, matched.label, clusterId);
      const selectedOption = {
        value: matched.value,
        label: matched.label,
        source: 'cluster' as const,
        identityCount: matched.identityCount as number | undefined,
      };
      guard.armGuard({
        label: matched.label,
        collisions: collisions.length > 0 ? collisions : [selectedOption],
        mergeTarget: selectedOption,
      });
      return;
    }
    guard.reset();
  };

  const handleRenameAnyway = (label: string) => {
    guard.allowRenameAnyway();
    void submitLabel(label, { skipDuplicateGuard: true });
  };

  const { lastMerge } = mutations;
  if (lastMerge) {
    const doneLabel = lastMerge.target_label ?? labelInput;
    return (
      <div className="acx-cluster-labeling-panel">
        <div className="acx-cluster-labeling-panel__header">
          <h2>{__('Name this person', 'alt-context')}</h2>
          <button
            type="button"
            className="acx-close-button"
            onClick={() => {
              onLabel(doneLabel);
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
            isReverting={mutations.isReverting}
            onUndo={() => mutations.revert(lastMerge)}
          />
          <div className="acx-cluster-labeling-panel__input-group">
            <button type="button" className="button button-secondary" onClick={() => onLabel(doneLabel)}>
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
        <ClusterLabelingMemberGrid clusterId={clusterId} onClose={onClose} />

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
                onOptionConfirm={(option) => handleSelectOption(String(option.value))}
                isPending={mutations.isBusy}
                isLoading={rosterLoading}
                inputDisabled={mutations.isMerging}
                disabled={mutations.isMerging}
                commitLabel={__('Save name', 'alt-context')}
                pendingLabel={mutations.isMerging ? __('Merging...', 'alt-context') : __('Saving...', 'alt-context')}
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

          {guard.duplicateGuard && (
            <ClusterLabelingDuplicatePrompt
              guard={guard.duplicateGuard}
              isBusy={mutations.isBusy}
              firstActionRef={guard.firstActionRef}
              onMerge={(targetClusterId, targetLabel) => mutations.merge({ targetClusterId, targetLabel })}
              onRenameAnyway={handleRenameAnyway}
              onCancel={guard.reset}
            />
          )}
          {error && (
            <p className="acx-cluster-labeling-panel__error" role="alert">
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
};
