/**
 * Inline "Is this X?" prompt for unlabeled identities with high-confidence suggestions.
 *
 * Shows a compact confirmation UI directly on the identity card instead of
 * requiring users to open the dropdown to see suggestions.
 *
 * Fetches via a shared batched query (GET /recognition/suggestions?limit=500)
 * so N unlabeled cards produce one network request (React Query key dedupe).
 */

import React from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  fetchAllPendingSuggestionRows,
  reduceInlineSuggestionsByIdentity,
  type InlineTopMatch,
} from './inlineSuggestionBatch';

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
 * Client reduction keeps labeled-only top-1 per identity (per-identity route parity).
 */
export const InlineSuggestionPrompt = ({
  identityId,
  onConfirm,
  onReject,
  isPending,
}: InlineSuggestionPromptProps): React.JSX.Element | null => {
  // Shared batch query — every card uses the same key so React Query fires once.
  const { data: byIdentity, isLoading } = useQuery({
    queryKey: queryKeys.suggestions.inlineBatch(),
    queryFn: async () => {
      const rows = await fetchAllPendingSuggestionRows();
      return reduceInlineSuggestionsByIdentity(rows);
    },
    staleTime: 60000,
    enabled: Boolean(identityId),
  });

  // Absent identity in the batch = no labeled suggestion (render honestly).
  const topMatch: InlineTopMatch | undefined = byIdentity?.get(identityId);
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
