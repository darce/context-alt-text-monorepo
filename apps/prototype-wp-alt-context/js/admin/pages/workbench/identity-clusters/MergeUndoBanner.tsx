/**
 * Undo banner shown after a successful merge.
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { MergeClusterResponse } from '../../../api/recognition';

interface MergeUndoBannerProps {
  /** The merge result containing target info */
  mergeResult: MergeClusterResponse;
  /** Whether the revert is in progress */
  isReverting: boolean;
  /** Called when undo is clicked */
  onUndo: () => void;
}

/**
 * Banner showing merge success with undo option.
 */
export const MergeUndoBanner = ({ mergeResult, isReverting, onUndo }: MergeUndoBannerProps): React.JSX.Element => {
  const targetLabel = mergeResult.target_label ?? __('existing cluster', 'alt-context');

  return (
    <div className="acx-identity-cluster__undo">
      <span>
        {sprintf(
          /* translators: %s: target cluster label */
          __('Merged into "%s".', 'alt-context'),
          targetLabel,
        )}
      </span>
      <button type="button" onClick={onUndo} disabled={isReverting}>
        {isReverting ? __('Reverting…', 'alt-context') : __('Undo merge', 'alt-context')}
      </button>
    </div>
  );
};
