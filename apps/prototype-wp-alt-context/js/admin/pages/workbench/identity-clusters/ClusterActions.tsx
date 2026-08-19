/**
 * Cluster action buttons (Edit, Wrong person, Split).
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

interface ClusterActionsProps {
  /** Whether the cluster can be edited */
  canEdit: boolean;
  /** Whether this is a singleton that can search for matches */
  canSearchForMatch: boolean;
  /** Whether the cluster has a user-assigned label */
  hasLabel: boolean;
  /** Whether the label is auto-generated */
  isAutoLabel: boolean;
  /** Whether the cluster can be split (has a cluster ID) */
  canSplit: boolean;
  /** Whether the identity can be rejected/removed (e.g. singletons) */
  canReject?: boolean;
  /** Whether any mutation is in progress */
  isPending: boolean;
  /** Remote-compute offline gate for split only (RES-15). */
  splitDisabled?: boolean;
  splitTitle?: string;
  splitAriaDisabled?: true;
  /** Called when edit button is clicked */
  onEdit: () => void;
  /** Called when "Wrong person" is clicked */
  onWrongPerson: () => void;
  /** Called when "Split cluster" is clicked */
  onSplit: () => void;
}

/**
 * Action buttons displayed when not in edit mode.
 */
export const ClusterActions = ({
  canEdit,
  canSearchForMatch,
  hasLabel,
  isAutoLabel,
  canSplit,
  canReject = true,
  isPending,
  splitDisabled = false,
  splitTitle,
  splitAriaDisabled,
  onEdit,
  onWrongPerson,
  onSplit,
}: ClusterActionsProps): React.JSX.Element | null => {
  // Show actions for regular editable clusters or singletons that can search for matches
  if (!canEdit && !canSearchForMatch) {
    return null;
  }

  // For singletons, only show "Find similar" button
  if (canSearchForMatch && !canEdit) {
    return (
      <button type="button" className="acx-identity-cluster__action" onClick={onEdit}>
        {__('Find similar / Name', 'alt-context')}
      </button>
    );
  }

  return (
    <>
      <button type="button" className="acx-identity-cluster__action" onClick={onEdit}>
        {!hasLabel || isAutoLabel ? __('Name this person', 'alt-context') : __('Edit label', 'alt-context')}
      </button>
      {canReject && (
        <button type="button" className="acx-identity-cluster__action" onClick={onWrongPerson} disabled={isPending}>
          {__('Remove from group', 'alt-context')}
        </button>
      )}
      {canSplit && (
        <button
          type="button"
          className="acx-identity-cluster__action"
          onClick={onSplit}
          disabled={isPending || splitDisabled}
          aria-disabled={splitAriaDisabled}
          title={splitTitle}
        >
          {__('Split group', 'alt-context')}
        </button>
      )}
    </>
  );
};
