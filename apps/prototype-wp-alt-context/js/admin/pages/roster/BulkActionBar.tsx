import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { Gavel, Trash, X } from 'lucide-react';

interface BulkActionBarProps {
  count: number;
  onMerge: () => void;
  onDismiss: () => void;
  onClear: () => void;
  isMerging?: boolean;
  isDismissing?: boolean;
  mergeProgress?: { current: number; total: number } | null;
}

export const BulkActionBar = ({
  count,
  onMerge,
  onDismiss,
  onClear,
  isMerging = false,
  isDismissing = false,
  mergeProgress = null,
}: BulkActionBarProps): React.JSX.Element => (
  <div className="acx-bulk-action-bar">
    <div className="acx-bulk-action-bar__info">
      <span className="acx-bulk-action-bar__count">
        {sprintf(
          // translators: %d: number of selected clusters
          __('%d selected', 'alt-context'),
          count,
        )}
      </span>
      <button
        type="button"
        className="acx-icon-button"
        onClick={onClear}
        title={__('Clear selection', 'alt-context')}
      >
        <X size={16} />
      </button>
    </div>
    <div className="acx-bulk-action-bar__actions">
      <button
        type="button"
        className="acx-button acx-button--secondary"
        onClick={onMerge}
        disabled={count < 2 || isMerging || isDismissing}
      >
        {isMerging ? <span className="acx-spinner" aria-hidden="true" /> : <Gavel size={16} />}
        {isMerging && mergeProgress
          ? sprintf(
              __('Merging %1$d of %2$d…', 'alt-context'),
              mergeProgress.current,
              mergeProgress.total,
            )
          : isMerging
            ? __('Merging…', 'alt-context')
            : __('Merge', 'alt-context')}
      </button>
      <button
        type="button"
        className="acx-button acx-button--danger"
        onClick={onDismiss}
        disabled={isMerging || isDismissing}
      >
        {isDismissing ? <span className="acx-spinner" aria-hidden="true" /> : <Trash size={16} />}
        {isDismissing ? __('Dismissing…', 'alt-context') : __('Dismiss', 'alt-context')}
      </button>
    </div>
  </div>
);
