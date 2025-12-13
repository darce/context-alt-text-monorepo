/**
 * Inline "Is this X?" prompt for unlabeled identities with high-confidence suggestions.
 *
 * Shows a compact confirmation UI directly on the identity card instead of
 * requiring users to open the dropdown to see suggestions.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery } from '@tanstack/react-query';

import { fetchIdentitySuggestions, type ClusterSuggestion } from '../../../api/recognition';

interface InlineSuggestionPromptProps {
  /** Identity ID to fetch suggestions for */
  identityId: string;
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
  identityId,
  onConfirm,
  onReject,
  isPending,
}: InlineSuggestionPromptProps): React.JSX.Element | null => {
  // Fetch top suggestion for this identity
  const { data: suggestions, isLoading } = useQuery({
    queryKey: ['identity-suggestions', identityId, 'inline'],
    queryFn: () => fetchIdentitySuggestions(identityId, 1), // Only fetch top 1
    staleTime: 60000, // Cache for 1 minute
    enabled: Boolean(identityId),
  });

  // Get the top suggestion - backend already filtered for threshold
  const topMatch: ClusterSuggestion | undefined = suggestions?.matches?.[0];
  const hasSuggestion = topMatch?.label;

  // Don't render if loading or no suggestion with a label
  if (isLoading || !hasSuggestion || !topMatch) {
    return null;
  }

  const matchPercent = Math.round(topMatch.similarity * 100);

  return (
    <div className="acx-inline-suggestion">
      <div className="acx-inline-suggestion__prompt">
        <span className="acx-inline-suggestion__question">
          {__('Is this', 'alt-context')} <strong>{topMatch.label}</strong>?
        </span>
        <span className="acx-inline-suggestion__confidence">{matchPercent}%</span>
      </div>
      <div className="acx-inline-suggestion__actions">
        <button
          type="button"
          className="button button-primary button-small acx-inline-suggestion__yes"
          onClick={() => onConfirm(topMatch.cluster_id, topMatch.label)}
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
