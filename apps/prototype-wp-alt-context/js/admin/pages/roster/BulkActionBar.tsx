import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import { Gavel, Trash, X } from 'lucide-react';

import type { BulkMergeFailure, BulkMergeProgress } from './hooks/useClusterActions';

interface BulkActionBarProps {
  count: number;
  onMerge: () => void;
  onDismiss: () => void;
  onClear: () => void;
  isMerging?: boolean;
  isDismissing?: boolean;
  mergeProgress?: BulkMergeProgress | null;
  mergeFailure?: BulkMergeFailure | null;
  onRetryMerge?: () => void;
  onDismissFailure?: () => void;
  /** When true, merge/dismiss controls stay visible but disabled with a reason. */
  controlsDisabled?: boolean;
  controlsDisabledReason?: string;
}

/**
 * Accessible name for a bulk cluster action.
 * Uses sprintf(_n(...)) so translators with >2 plural forms can select correctly.
 */
const mergeIdleLabel = (count: number): string =>
  sprintf(
    // translators: %d: number of selected clusters
    _n('Merge %d cluster', 'Merge %d clusters', count, 'alt-context'),
    count,
  );

const dismissIdleLabel = (count: number): string =>
  sprintf(
    // translators: %d: number of selected clusters
    _n('Dismiss %d cluster', 'Dismiss %d clusters', count, 'alt-context'),
    count,
  );

const mergingSimpleLabel = (count: number): string =>
  sprintf(
    // translators: %d: number of selected clusters
    _n('Merging %d cluster…', 'Merging %d clusters…', count, 'alt-context'),
    count,
  );

const dismissingLabel = (count: number): string =>
  sprintf(
    // translators: %d: number of selected clusters
    _n('Dismissing %d cluster…', 'Dismissing %d clusters…', count, 'alt-context'),
    count,
  );

/**
 * Progress labels name the unit they count: sequential *source* merges
 * (sourceIds.length from useClusterActions), not the selection size.
 * So a 3-cluster merge reports "Merging source 1 of 2…" rather than
 * contradicting the idle "Merge 3 clusters" label with "Merging 1 of 2…".
 */
const mergingProgressLabel = (current: number, total: number): string =>
  sprintf(
    // translators: %1$d: current source merge step (1-based); %2$d: total source merges
    __('Merging source %1$d of %2$d…', 'alt-context'),
    current,
    total,
  );

export const BulkActionBar = ({
  count,
  onMerge,
  onDismiss,
  onClear,
  isMerging = false,
  isDismissing = false,
  mergeProgress = null,
  mergeFailure = null,
  onRetryMerge,
  onDismissFailure,
  controlsDisabled = false,
  controlsDisabledReason,
}: BulkActionBarProps): React.JSX.Element => {
  const mergeLabel =
    isMerging && mergeProgress
      ? mergingProgressLabel(mergeProgress.current, mergeProgress.total)
      : isMerging
        ? mergingSimpleLabel(count)
        : mergeIdleLabel(count);

  const dismissLabel = isDismissing ? dismissingLabel(count) : dismissIdleLabel(count);

  const progressAnnouncement =
    isMerging && mergeProgress
      ? mergingProgressLabel(mergeProgress.current, mergeProgress.total)
      : '';

  const actionsDisabled = controlsDisabled || isMerging || isDismissing;
  // Domain: merge needs ≥2 clusters; dismiss needs ≥1. Do not flatten.
  const mergeDisabled = count < 2 || actionsDisabled;
  const dismissDisabled = count < 1 || actionsDisabled;

  return (
    <div className="acx-bulk-action-bar">
      <div className="acx-bulk-action-bar__info">
        <span className="acx-bulk-action-bar__count">
          {sprintf(
            // translators: %d: number of selected clusters
            _n('%d selected', '%d selected', count, 'alt-context'),
            count,
          )}
        </span>
        <button type="button" className="acx-icon-button" onClick={onClear} title={__('Clear selection', 'alt-context')}>
          <X size={16} />
        </button>
      </div>
      <div className="acx-bulk-action-bar__actions">
        <button
          type="button"
          className="acx-button acx-button--secondary"
          onClick={onMerge}
          disabled={mergeDisabled}
          title={controlsDisabled ? controlsDisabledReason : undefined}
        >
          {isMerging ? <span className="acx-spinner" aria-hidden="true" /> : <Gavel size={16} />}
          {mergeLabel}
        </button>
        <button
          type="button"
          className="acx-button acx-button--danger"
          onClick={onDismiss}
          disabled={dismissDisabled}
          title={controlsDisabled ? controlsDisabledReason : undefined}
        >
          {isDismissing ? <span className="acx-spinner" aria-hidden="true" /> : <Trash size={16} />}
          {dismissLabel}
        </button>
      </div>
      <p
        className="acx-bulk-action-bar__status"
        role="status"
        aria-live="polite"
        data-testid="bulk-merge-status"
      >
        {progressAnnouncement}
      </p>
      {mergeFailure ? (
        <div
          className="acx-bulk-action-bar__failure"
          role="alert"
          data-testid="bulk-merge-failure"
        >
          <p className="acx-bulk-action-bar__failure-message">{mergeFailure.message}</p>
          <div className="acx-bulk-action-bar__failure-actions">
            {onRetryMerge ? (
              <button
                type="button"
                className="acx-button acx-button--secondary"
                onClick={onRetryMerge}
                disabled={isMerging || isDismissing}
              >
                {__('Retry', 'alt-context')}
              </button>
            ) : null}
            {onDismissFailure ? (
              <button type="button" className="acx-button acx-button--secondary" onClick={onDismissFailure}>
                {__('Dismiss notice', 'alt-context')}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
};
