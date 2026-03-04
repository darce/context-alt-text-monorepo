import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { Gavel, Trash, X } from 'lucide-react';

interface BulkActionBarProps {
  count: number;
  onMerge: () => void;
  onDismiss: () => void;
  onClear: () => void;
}

export const BulkActionBar = ({
  count,
  onMerge,
  onDismiss,
  onClear,
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
        disabled={count < 2}
      >
        <Gavel size={16} />
        {__('Merge', 'alt-context')}
      </button>
      <button
        type="button"
        className="acx-button acx-button--danger"
        onClick={onDismiss}
      >
        <Trash size={16} />
        {__('Dismiss', 'alt-context')}
      </button>
    </div>
  </div>
);
