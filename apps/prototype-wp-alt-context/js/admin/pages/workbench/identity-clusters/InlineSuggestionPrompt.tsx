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

import type { ProjectedSuggestion } from './suggestionProjection';

interface InlineSuggestionPromptProps {
  /** Top server-ranked suggestion for this identity, or undefined when none applies */
  match: ProjectedSuggestion | undefined;
  /** Called when user confirms the suggestion (suggestionId resolves the pending row by id) */
  onConfirm: (clusterId: string, label: string, suggestionId?: string) => void;
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
  // Capture trimmed label so TS narrows string | null | undefined → string for
  // onConfirm, and whitespace-only labels never render (defense-in-depth: the
  // hooks already filter, but this gate must not be weaker than theirs).
  const label = match?.label?.trim();
  if (!match || !label) {
    return null;
  }

  const matchPercent = Math.round(match.similarity * 100);

  return (
    <div className="acx-inline-suggestion">
      <div className="acx-inline-suggestion__prompt">
        <span className="acx-inline-suggestion__question">
          {__('Is this', 'alt-context')} <strong>{label}</strong>?
        </span>
        <span className="acx-inline-suggestion__confidence">{matchPercent}%</span>
      </div>
      <div className="acx-inline-suggestion__actions">
        <button
          type="button"
          className="button button-primary button-small acx-inline-suggestion__yes"
          onClick={() => onConfirm(match.clusterId, label, match.suggestionId)}
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
