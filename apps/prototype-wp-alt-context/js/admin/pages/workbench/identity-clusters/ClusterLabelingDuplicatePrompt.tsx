/**
 * Duplicate-collision prompt for ClusterLabelingPanel (extracted for FEBT1G-M-14).
 *
 * Presentation only: it renders the three resolutions (merge / rename anyway / cancel) the
 * guard offers. The merge affordance and the outcome-sample copy share one predicate so the
 * UI can never advertise a merge the button suppresses (BR-66 / BR-58).
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { unwrapClusterOptionId } from './buildNamingOptions';
import { isHumanLabeledTarget } from './suggestionProjection';
import type { DuplicateGuardState } from './useClusterLabelingDuplicateGuard';

interface ClusterLabelingDuplicatePromptProps {
  readonly guard: DuplicateGuardState;
  readonly isBusy: boolean;
  readonly firstActionRef: React.MutableRefObject<HTMLButtonElement | null>;
  readonly onMerge: (targetClusterId: string, targetLabel: string) => void;
  readonly onRenameAnyway: (label: string) => void;
  readonly onCancel: () => void;
}

export const ClusterLabelingDuplicatePrompt = ({
  guard,
  isBusy,
  firstActionRef,
  onMerge,
  onRenameAnyway,
  onCancel,
}: ClusterLabelingDuplicatePromptProps): React.JSX.Element => {
  const mergeTargetId = guard.mergeTarget ? unwrapClusterOptionId(guard.mergeTarget.value) : null;
  const mergeTargetLabel = guard.mergeTarget?.label;
  const mergeTargetCount = guard.mergeTarget?.identityCount;
  const canOfferMerge =
    Boolean(mergeTargetId) &&
    typeof mergeTargetLabel === 'string' &&
    mergeTargetLabel.length > 0 &&
    isHumanLabeledTarget(mergeTargetLabel);
  const offersMerge = canOfferMerge && mergeTargetId !== null && mergeTargetLabel !== undefined;

  return (
    <div
      className="acx-cluster-labeling-panel__duplicate-guard"
      role="group"
      aria-labelledby="acx-cluster-labeling-panel-duplicate-guard-label"
    >
      <p id="acx-cluster-labeling-panel-duplicate-guard-label" className="acx-cluster-labeling-panel__suggestion-text">
        {sprintf(__('A name matching "%s" already exists. Choose how to proceed.', 'alt-context'), guard.label)}
      </p>
      {offersMerge ? (
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
        {offersMerge ? (
          <button
            ref={firstActionRef}
            type="button"
            className="button button-primary"
            disabled={isBusy}
            onClick={() => onMerge(mergeTargetId, mergeTargetLabel)}
          >
            {sprintf(
              /* translators: %s: target cluster label */
              __('Merge into group "%s"', 'alt-context'),
              mergeTargetLabel,
            )}
          </button>
        ) : null}
        <button
          ref={offersMerge ? undefined : firstActionRef}
          type="button"
          className="button"
          disabled={isBusy}
          onClick={() => onRenameAnyway(guard.label)}
        >
          {__('Rename anyway', 'alt-context')}
        </button>
        <button type="button" className="button" disabled={isBusy} onClick={onCancel}>
          {__('Cancel', 'alt-context')}
        </button>
      </div>
    </div>
  );
};
