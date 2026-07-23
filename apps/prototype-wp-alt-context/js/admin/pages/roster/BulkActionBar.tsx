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
        ? __('Merging…', 'alt-context')
        : __('Merge', 'alt-context');

  const progressAnnouncement =
    isMerging && mergeProgress
      ? sprintf(__('Merging %1$d of %2$d…', 'alt-context'), mergeProgress.current, mergeProgress.total)
      : '';

  const actionsDisabled = controlsDisabled || isMerging || isDismissing;
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
          {isDismissing ? __('Dismissing…', 'alt-context') : __('Dismiss', 'alt-context')}
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
