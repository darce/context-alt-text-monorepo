/**
 * Inline "Is this X?" prompt for unlabeled identities with high-confidence suggestions.
 *
 * Shows a compact confirmation UI directly on the identity card instead of
 * requiring users to open the dropdown to see suggestions.
 *
 * Presentational: the top suggestion is supplied by the caller (a single
 * batched fetch at the list level), so this component owns no data fetching.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import { type ClusterSuggestion } from '../../../api/recognition';

interface InlineSuggestionPromptProps {
  /** Top server-ranked suggestion for this identity, or undefined when none applies */
  match: ClusterSuggestion | undefined;
  /** Called when user confirms the suggestion */
  onConfirm: (clusterId: string, label: string) => void;
  /** Called when user rejects the suggestion */
  onReject: () => void;
  /** Whether a mutation is in progress */
  isPending: boolean;
}

/**
 * Inline confirmation prompt for high-confidence suggestions.
 *
 * The backend controls all threshold decisions - if a suggestion exists,
 * it means the backend determined it's worth showing to the user.
 */
export const InlineSuggestionPrompt = ({
  match,
  onConfirm,
  onReject,
  isPending,
}: InlineSuggestionPromptProps): React.JSX.Element | null => {
  // Don't render without a suggestion that carries a label.
  if (!match?.label) {
    return null;
  }

  const matchPercent = Math.round(match.similarity * 100);

  return (
    <div className="acx-inline-suggestion">
      <div className="acx-inline-suggestion__prompt">
        <span className="acx-inline-suggestion__question">
          {__('Is this', 'alt-context')} <strong>{match.label}</strong>?
        </span>
        <span className="acx-inline-suggestion__confidence">{matchPercent}%</span>
      </div>
      <div className="acx-inline-suggestion__actions">
        <button
          type="button"
          className="button button-primary button-small acx-inline-suggestion__yes"
          onClick={() => onConfirm(match.cluster_id, match.label)}
          disabled={isPending}
        >
          {__('Yes', 'alt-context')}
        </button>
        <button
          type="button"
          className="button button-small acx-inline-suggestion__no"
          onClick={onReject}
          disabled={isPending}
        >
          {__('No', 'alt-context')}
        </button>
      </div>
    </div>
  );
};
