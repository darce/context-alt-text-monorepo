/**
 * Panel for reviewing pending identity suggestions.
 * Shows "Is this X?" prompts for borderline matches that need user confirmation.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  fetchPendingSuggestions,
  acceptSuggestion,
  rejectSuggestion,
  type PendingSuggestion,
} from '../../../api/recognition';

interface SuggestionCardProps {
  suggestion: PendingSuggestion;
  onAccept: () => void;
  onReject: () => void;
  isPending: boolean;
}

/**
 * Single suggestion card with "Is this X?" prompt.
 */
const SuggestionCard = ({ suggestion, onAccept, onReject, isPending }: SuggestionCardProps): React.JSX.Element => {
  const matchPercent = Math.round(suggestion.representative_similarity * 100);
  const clusterName = suggestion.cluster_label ?? __('Unnamed cluster', 'alt-context');

  return (
    <div className="acx-suggestion-card">
      <div className="acx-suggestion-card__content">
        <p className="acx-suggestion-card__question">
          {__('Is this', 'alt-context')} <strong>{clusterName}</strong>?
        </p>
        <p className="acx-suggestion-card__match">
          {matchPercent}% {__('match', 'alt-context')}
          {suggestion.cluster_identity_count && (
            <span className="acx-suggestion-card__count">
              {' '}
              ({suggestion.cluster_identity_count} {__('in cluster', 'alt-context')})
            </span>
          )}
        </p>
      </div>

      <div className="acx-suggestion-card__actions">
        <button
          type="button"
          className="button button-primary acx-suggestion-card__accept"
          onClick={onAccept}
          disabled={isPending}
        >
          {__('Yes', 'alt-context')}
        </button>
        <button type="button" className="button acx-suggestion-card__reject" onClick={onReject} disabled={isPending}>
          {__('No', 'alt-context')}
        </button>
      </div>
    </div>
  );
};

/**
 * Panel showing all pending suggestions for user review.
 */
export const SuggestionReviewPanel = (): React.JSX.Element | null => {
  const queryClient = useQueryClient();

  // Fetch pending suggestions
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.suggestions.pending(),
    queryFn: () => fetchPendingSuggestions(10, 0),
    refetchInterval: (query) => (query.state.status === 'error' ? false : 30000),
    retry: 1,
  });

  // Accept mutation
  const acceptMutation = useMutation({
    mutationFn: acceptSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
  });

  // Reject mutation
  const rejectMutation = useMutation({
    mutationFn: rejectSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
    },
  });

  const suggestions = data?.suggestions ?? [];
  const totalCount = data?.total ?? 0;

  if (isLoading) {
    return (
      <div className="acx-suggestion-panel acx-suggestion-panel--loading">
        <p>{__('Loading suggestions...', 'alt-context')}</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="acx-suggestion-panel acx-suggestion-panel--error">
        <p>{__('Failed to load suggestions.', 'alt-context')}</p>
        <button type="button" className="button" onClick={() => void refetch()}>
          {__('Retry', 'alt-context')}
        </button>
      </div>
    );
  }

  // Don't render if no suggestions
  if (suggestions.length === 0) {
    return null;
  }

  return (
    <div className="acx-suggestion-panel">
      <h3 className="acx-suggestion-panel__title">
        {__('Review Suggestions', 'alt-context')}
        {totalCount > 0 && <span className="acx-suggestion-panel__count">{totalCount}</span>}
      </h3>
      <p className="acx-suggestion-panel__description">
        {__('These faces are close matches but need your confirmation.', 'alt-context')}
      </p>

      <div className="acx-suggestion-panel__list">
        {suggestions.map((suggestion) => (
          <SuggestionCard
            key={suggestion.id}
            suggestion={suggestion}
            onAccept={() => acceptMutation.mutate(suggestion.id)}
            onReject={() => rejectMutation.mutate(suggestion.id)}
            isPending={acceptMutation.isPending || rejectMutation.isPending}
          />
        ))}
      </div>

      {totalCount > suggestions.length && (
        <p className="acx-suggestion-panel__more">
          {__('and', 'alt-context')} {totalCount - suggestions.length} {__('more...', 'alt-context')}
        </p>
      )}
    </div>
  );
};
