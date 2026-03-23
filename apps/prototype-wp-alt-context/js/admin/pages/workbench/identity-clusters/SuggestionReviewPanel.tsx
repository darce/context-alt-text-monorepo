/**
 * Panel for reviewing pending identity suggestions.
 * Shows "Is this X?" prompts for borderline matches that need user confirmation.
 * Also shows top unlabeled clusters when no suggestions are pending.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import type { PendingSuggestion } from '../../../api/recognition';
import { CollapsibleMergeQueue } from './CollapsibleMergeQueue';
import { GroupedSuggestionCard, SuggestionCard } from './SuggestionCards';
import { TopClustersSection } from './TopClustersSection';
import { useSuggestionReviewData } from './useSuggestionReviewData';

const LOW_CONFIDENCE_THRESHOLD = 0.6;

interface SuggestionReviewPanelProps {
  onLabel?: (clusterId: string) => void;
  onReview?: (clusterId: string) => void;
}

export const SuggestionReviewPanel = ({ onLabel, onReview }: SuggestionReviewPanelProps): React.JSX.Element | null => {
  const [isOpen, setIsOpen] = React.useState(true);
  const [expandedGroups, setExpandedGroups] = React.useState<Set<string>>(new Set());
  const [bulkConfidenceThreshold, setBulkConfidenceThreshold] = React.useState(LOW_CONFIDENCE_THRESHOLD);
  const contentId = React.useId();

  const {
    mergeSuggestions,
    nameSuggestions,
    reviewItems,
    assignmentCount,
    loadedAssignmentCount,
    hasInitialFailure,
    isLoading,
    isError,
    failureCount,
    tenantId,
    isAnyMutationPending,
    bulkActionClusterId,
    setBulkActionClusterId,
    bulkActionRef,
    refetchAssignment,
    refetchMerge,
    invalidateSuggestionQueries,
    invalidateMediaIdentities,
    mutations,
  } = useSuggestionReviewData();

  const toggleReviewEach = (clusterId: string): void => {
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (next.has(clusterId)) {
        next.delete(clusterId);
      } else {
        next.add(clusterId);
      }
      return next;
    });
  };

  const acceptGroupedSuggestions = async (clusterId: string, suggestions: PendingSuggestion[]): Promise<void> => {
    if (bulkActionClusterId) {
      return;
    }
    setBulkActionClusterId(clusterId);
    bulkActionRef.current = true;
    try {
      await Promise.all(suggestions.map((suggestion) => mutations.accept.mutateAsync(suggestion.id)));
      setExpandedGroups((current) => {
        if (!current.has(clusterId)) {
          return current;
        }
        const next = new Set(current);
        next.delete(clusterId);
        return next;
      });
    } finally {
      bulkActionRef.current = false;
      setBulkActionClusterId(null);
      invalidateSuggestionQueries();
      invalidateMediaIdentities();
    }
  };

  const rejectGroupedSuggestions = async (clusterId: string, suggestions: PendingSuggestion[]): Promise<void> => {
    if (bulkActionClusterId) {
      return;
    }
    setBulkActionClusterId(clusterId);
    bulkActionRef.current = true;
    try {
      await Promise.all(suggestions.map((suggestion) => mutations.reject.mutateAsync(suggestion.id)));
      setExpandedGroups((current) => {
        if (!current.has(clusterId)) {
          return current;
        }
        const next = new Set(current);
        next.delete(clusterId);
        return next;
      });
    } finally {
      bulkActionRef.current = false;
      setBulkActionClusterId(null);
      invalidateSuggestionQueries();
    }
  };

  const renderSuggestionCard = (suggestion: PendingSuggestion): React.JSX.Element => (
    <SuggestionCard
      key={`assign-${suggestion.id}`}
      suggestion={suggestion}
      lowConfidenceThreshold={LOW_CONFIDENCE_THRESHOLD}
      onAccept={() => mutations.accept.mutate(suggestion.id)}
      onReject={() => mutations.reject.mutate(suggestion.id)}
      onLabel={(clusterId) => {
        if (onLabel) {
          onLabel(clusterId ?? suggestion.suggested_cluster_id);
        }
      }}
      onReview={(clusterId) => {
        if (onReview && clusterId) {
          onReview(clusterId);
        }
      }}
      isPending={isAnyMutationPending}
    />
  );

  if (hasInitialFailure && failureCount <= 2) {
    return null;
  }

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
        <button type="button" className="button" onClick={() => void refetchAssignment().then(() => refetchMerge())}>
          {__('Retry', 'alt-context')}
        </button>
      </div>
    );
  }

  return (
    <div className={`acx-suggestion-panel${isOpen ? '' : ' acx-suggestion-panel--collapsed'}`}>
      <button
        type="button"
        className="acx-suggestion-panel__header"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-controls={contentId}
      >
        <span className={`acx-suggestion-panel__toggle-icon ${isOpen ? 'is-open' : ''}`}>▼</span>
        <span className="acx-suggestion-panel__title">
          {__('Review Suggestions', 'alt-context')}
          {assignmentCount > 0 && <span className="acx-suggestion-panel__count">{assignmentCount}</span>}
        </span>
      </button>

      {isOpen && (
        <div id={contentId} className="acx-suggestion-panel__content">
          <CollapsibleMergeQueue
            suggestions={mergeSuggestions}
            onAccept={(id) => mutations.acceptMerge.mutate(id)}
            onReject={(id) => mutations.rejectMerge.mutate(id)}
            isPending={mutations.acceptMerge.isPending || mutations.rejectMerge.isPending}
          />

          <div className="acx-suggestion-queue">
            {reviewItems.length === 0 ? (
              <p className="acx-suggestion-panel__description">{__('No suggestions to review yet.', 'alt-context')}</p>
            ) : (
              <p className="acx-suggestion-panel__description">
                {__('These faces are close matches but need your confirmation.', 'alt-context')}
              </p>
            )}

            {reviewItems.length > 0 && (
              <div className="acx-suggestion-panel__list">
                {reviewItems.map((item) =>
                  item.type === 'group' ? (
                    <GroupedSuggestionCard
                      key={`group-${item.clusterId}`}
                      clusterId={item.clusterId}
                      label={item.label}
                      suggestions={item.suggestions}
                      lowConfidenceThreshold={LOW_CONFIDENCE_THRESHOLD}
                      onAcceptAll={() => {
                        void acceptGroupedSuggestions(item.clusterId, item.suggestions);
                      }}
                      onRejectAll={() => {
                        void rejectGroupedSuggestions(item.clusterId, item.suggestions);
                      }}
                      onToggleReviewEach={() => toggleReviewEach(item.clusterId)}
                      isExpanded={expandedGroups.has(item.clusterId)}
                      isPending={isAnyMutationPending}
                    >
                      <div className="acx-suggestion-panel__list">
                        {item.suggestions.map((suggestion) => renderSuggestionCard(suggestion))}
                      </div>
                    </GroupedSuggestionCard>
                  ) : (
                    renderSuggestionCard(item.suggestion)
                  ),
                )}
              </div>
            )}

            {assignmentCount > loadedAssignmentCount && (
              <p className="acx-suggestion-panel__more">
                {__('and', 'alt-context')} {assignmentCount - loadedAssignmentCount} {__('more...', 'alt-context')}
              </p>
            )}
          </div>

          {nameSuggestions.length > 0 && (
            <div className="acx-naming-queue acx-naming-queue--suggestions">
              <h3 className="acx-suggestion-panel__section-title">{__('Suggested names', 'alt-context')}</h3>
              <p className="acx-suggestion-panel__description">
                {__('These names were suggested by the recognition engine for unlabeled clusters.', 'alt-context')}
              </p>
              <ul className="acx-suggestion-panel__list">
                {nameSuggestions.map((suggestion) => (
                  <li key={suggestion.id} className="acx-name-suggestion-card">
                    <span className="acx-name-suggestion-card__label">{suggestion.suggested_name}</span>
                    {suggestion.confidence_score !== null && suggestion.confidence_score !== undefined && (
                      <span
                        className={`acx-suggestion-confidence${suggestion.confidence_score < LOW_CONFIDENCE_THRESHOLD ? ' acx-suggestion-confidence--low' : ''}`}
                      >
                        {Math.round(suggestion.confidence_score * 100)}%
                      </span>
                    )}
                    <div className="acx-name-suggestion-card__actions">
                      <button
                        type="button"
                        className="acx-button acx-button--primary acx-button--small"
                        disabled={mutations.acceptName.isPending || mutations.rejectName.isPending}
                        onClick={() => mutations.acceptName.mutate(suggestion.id)}
                      >
                        {__('Accept', 'alt-context')}
                      </button>
                      <button
                        type="button"
                        className="acx-button acx-button--secondary acx-button--small"
                        disabled={mutations.acceptName.isPending || mutations.rejectName.isPending}
                        onClick={() => mutations.rejectName.mutate(suggestion.id)}
                      >
                        {__('Reject', 'alt-context')}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="acx-bulk-accept">
            <h3 className="acx-suggestion-panel__section-title">{__('Bulk accept', 'alt-context')}</h3>
            <p className="acx-suggestion-panel__description">
              {__('Accept all suggestions above a confidence threshold.', 'alt-context')}
            </p>
            <label className="acx-bulk-accept__threshold-label">
              <span>{__('Minimum confidence:', 'alt-context')}</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={bulkConfidenceThreshold}
                onChange={(e) => setBulkConfidenceThreshold(parseFloat(e.target.value))}
                className="acx-bulk-accept__slider"
              />
              <span className="acx-bulk-accept__threshold-value">{Math.round(bulkConfidenceThreshold * 100)}%</span>
            </label>
            <div className="acx-bulk-accept__actions">
              <button
                type="button"
                className="acx-button acx-button--secondary acx-button--small"
                disabled={mutations.bulkAccept.isPending}
                onClick={() =>
                  mutations.bulkAccept.mutate({ suggestion_type: 'assignment', min_confidence: bulkConfidenceThreshold })
                }
              >
                {mutations.bulkAccept.isPending
                  ? __('Accepting…', 'alt-context')
                  : __('Bulk accept assignments', 'alt-context')}
              </button>
              <button
                type="button"
                className="acx-button acx-button--secondary acx-button--small"
                disabled={mutations.bulkAccept.isPending}
                onClick={() =>
                  mutations.bulkAccept.mutate({ suggestion_type: 'name', min_confidence: bulkConfidenceThreshold })
                }
              >
                {mutations.bulkAccept.isPending
                  ? __('Accepting…', 'alt-context')
                  : __('Bulk accept names', 'alt-context')}
              </button>
              <button
                type="button"
                className="acx-button acx-button--secondary acx-button--small"
                disabled={mutations.bulkAccept.isPending}
                onClick={() =>
                  mutations.bulkAccept.mutate({ suggestion_type: 'merge', min_confidence: bulkConfidenceThreshold })
                }
              >
                {mutations.bulkAccept.isPending
                  ? __('Accepting…', 'alt-context')
                  : __('Bulk accept merges', 'alt-context')}
              </button>
            </div>
          </div>

          {tenantId && (
            <div className="acx-naming-queue">
              <TopClustersSection
                tenantId={tenantId}
                onLabel={(clusterId) => onLabel?.(clusterId)}
                onReview={onReview}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
};
