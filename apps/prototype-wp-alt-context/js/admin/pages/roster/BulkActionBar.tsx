import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
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
 * sprintf + two explicit strings (not _n): lower risk for existing i18n test mocks
 * that only implement __ / sprintf; _n is established elsewhere in the app but not
 * required for this two-branch case.
 */
const mergeIdleLabel = (count: number): string =>
  count === 1
    ? sprintf(
        // translators: %d: number of selected clusters (always 1 here)
        __('Merge %d cluster', 'alt-context'),
        count,
      )
    : sprintf(
        // translators: %d: number of selected clusters
        __('Merge %d clusters', 'alt-context'),
        count,
      );

const dismissIdleLabel = (count: number): string =>
  count === 1
    ? sprintf(
        // translators: %d: number of selected clusters (always 1 here)
        __('Dismiss %d cluster', 'alt-context'),
        count,
      )
    : sprintf(
        // translators: %d: number of selected clusters
        __('Dismiss %d clusters', 'alt-context'),
        count,
      );

const mergingSimpleLabel = (count: number): string =>
  count === 1
    ? sprintf(
        // translators: %d: number of selected clusters (always 1 here)
        __('Merging %d cluster…', 'alt-context'),
        count,
      )
    : sprintf(
        // translators: %d: number of selected clusters
        __('Merging %d clusters…', 'alt-context'),
        count,
      );

const dismissingLabel = (count: number): string =>
  count === 1
    ? sprintf(
        // translators: %d: number of selected clusters (always 1 here)
        __('Dismissing %d cluster…', 'alt-context'),
        count,
      )
    : sprintf(
        // translators: %d: number of selected clusters
        __('Dismissing %d clusters…', 'alt-context'),
        count,
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
      ? sprintf(__('Merging %1$d of %2$d…', 'alt-context'), mergeProgress.current, mergeProgress.total)
      : isMerging
        ? mergingSimpleLabel(count)
        : mergeIdleLabel(count);

  const dismissLabel = isDismissing ? dismissingLabel(count) : dismissIdleLabel(count);

  const progressAnnouncement =
    isMerging && mergeProgress
      ? sprintf(__('Merging %1$d of %2$d…', 'alt-context'), mergeProgress.current, mergeProgress.total)
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
            __('%d selected', 'alt-context'),
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
