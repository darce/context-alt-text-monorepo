/**
 * Panel for reviewing pending identity suggestions.
 * Shows "Is this X?" prompts for borderline matches that need user confirmation.
 * Also shows top unlabeled clusters when no suggestions are pending.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  fetchPendingSuggestions,
  fetchPendingMergeSuggestions,
  acceptSuggestion,
  acceptMergeSuggestion,
  rejectSuggestion,
  rejectMergeSuggestion,
  type PendingSuggestion,
} from '../../../api/recognition';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import { TopClustersSection } from './TopClustersSection';
import { getConfig } from '../../../api/config';
import { CollapsibleMergeQueue } from './CollapsibleMergeQueue';

const LOW_CONFIDENCE_THRESHOLD = 0.6;
const SUGGESTION_PAGE_SIZE = 25;

interface SuggestionCardProps {
  suggestion: PendingSuggestion;
  onAccept: () => void;
  onReject: () => void;
  onLabel: (clusterId?: string) => void;
  onReview?: (clusterId?: string) => void;
  isPending: boolean;
}

interface GroupedSuggestionCardProps {
  clusterId: string;
  label: string;
  suggestions: PendingSuggestion[];
  onAcceptAll: () => void;
  onToggleReviewEach: () => void;
  isExpanded: boolean;
  isPending: boolean;
  children?: React.ReactNode;
}

type SuggestionReviewItem =
  | {
      type: 'single';
      score: number;
      suggestion: PendingSuggestion;
    }
  | {
      type: 'group';
      clusterId: string;
      score: number;
      label: string;
      suggestions: PendingSuggestion[];
    };

/**
 * Single suggestion card with "Is this X?" prompt.
 */
const SuggestionCard = ({
  suggestion,
  onAccept,
  onReject,
  onLabel,
  onReview,
  isPending,
}: SuggestionCardProps): React.JSX.Element => {
  const matchPercent = Math.round(suggestion.representative_similarity * 100);
  const isLowConfidence = suggestion.representative_similarity < LOW_CONFIDENCE_THRESHOLD;
  const suggestedLabel = suggestion.suggested_label;
  const hasLabel = Boolean(suggestion.cluster_label ?? suggestedLabel);
  const displayLabel = suggestion.cluster_label ?? suggestedLabel ?? __('Unnamed cluster', 'alt-context');
  const identityFace = suggestion.identity_media_url && suggestion.identity_bbox
    ? { mediaUrl: suggestion.identity_media_url, bbox: suggestion.identity_bbox }
    : null;
  // We use cluster_thumbnails if available, otherwise fallback to representative
  const clusterThumbnails = suggestion.cluster_thumbnails ?? [];
  const showGrid = clusterThumbnails.length > 1;
  const representativeFace = suggestion.representative_media_url && suggestion.representative_bbox
    ? { mediaUrl: suggestion.representative_media_url, bbox: suggestion.representative_bbox }
    : null;

  // Review Cluster navigation
  // Note: We don't have direct navigation prop, assumes window.location or similar for MVP,
  // or onLabel triggered for specific UI.
  // The requirement says "Add 'Review cluster' entry point... actual navigation or modal opening".
  // For MVP, since we don't have a modal provider context here, we can reuse `onLabel` if it opens the cluster view,
  // or add a secondary action.
  // `onLabel` opens "ClusterLabelingPanel" as per comments later in file.
  // We can treat "Review Cluster" as "Open Cluster View".
  // Let's add a "Review" button if onLabel is present.

  return (
    <div className={`acx-suggestion-card${isLowConfidence ? ' acx-suggestion-card--low-confidence' : ''}`}>
      <div className="acx-suggestion-card__faces">
        <div className="acx-suggestion-card__face">
          {identityFace ? (
            <FaceThumbnail
              mediaUrl={identityFace.mediaUrl}
              bbox={identityFace.bbox}
              size="md"
              alt={__('Candidate face', 'alt-context')}
              className="acx-suggestion-card__thumb"
            />
          ) : (
            <span className="acx-suggestion-card__thumb acx-suggestion-card__thumb--placeholder" />
          )}
          <span className="acx-suggestion-card__face-label">{__('Candidate', 'alt-context')}</span>
        </div>

        <div className={`acx-suggestion-card__face ${showGrid ? 'acx-suggestion-card__face--grid' : ''}`}>
          {showGrid ? (
            <div className="acx-face-grid-preview acx-face-grid-preview--cluster">
              {clusterThumbnails.slice(0, 4).map((url, idx) => (
                <img key={idx} src={url} alt="" className="acx-face-grid-preview__image" />
              ))}
            </div>
          ) : representativeFace ? (
            <FaceThumbnail
              mediaUrl={representativeFace.mediaUrl}
              bbox={representativeFace.bbox}
              size="md"
              alt={__('Cluster representative', 'alt-context')}
              className="acx-suggestion-card__thumb"
            />
          ) : (
            <span className="acx-suggestion-card__thumb acx-suggestion-card__thumb--placeholder" />
          )}
          <span className="acx-suggestion-card__face-label">{displayLabel}</span>
        </div>
      </div>
      <div className="acx-suggestion-card__content">
        <p className="acx-suggestion-card__question">
          {hasLabel ? (
            <>
              {__('Is this', 'alt-context')} <strong>{displayLabel}</strong>?
              {suggestedLabel && !suggestion.cluster_label && (
                <span className="acx-badge acx-badge--inferred" title={__('Inferred label', 'alt-context')}>
                  {suggestion.suggested_label_source === 'similar_cluster'
                    ? __('Similar to labeled', 'alt-context')
                    : suggestion.suggested_label_source === 'identity'
                      ? __('Identity match', 'alt-context')
                      : suggestion.suggested_label_source === 'roster'
                        ? __('Roster match', 'alt-context')
                        : __('Suggested', 'alt-context')}
                </span>
              )}
            </>
          ) : (
            <strong>{__('Name this person', 'alt-context')}</strong>
          )}
        </p>
        <p className="acx-suggestion-card__match">
          {matchPercent}% {__('match', 'alt-context')}
          {suggestion.cluster_identity_count && (
            <span className="acx-suggestion-card__count">
              {' '}
              ({suggestion.cluster_identity_count} {__('in cluster', 'alt-context')})
            </span>
          )}
          {isLowConfidence && (
            <span className="acx-suggestion-card__confidence-flag">
              {__('Low confidence', 'alt-context')}
            </span>
          )}
        </p>
      </div>

      <div className="acx-suggestion-card__actions">
        {hasLabel ? (
          <>
            <button
              type="button"
              className="button button-primary acx-suggestion-card__accept"
              onClick={onAccept}
              disabled={isPending}
            >
              {__('Yes', 'alt-context')}
            </button>
            <button
              type="button"
              className="button acx-suggestion-card__reject"
              onClick={onReject}
              disabled={isPending}
            >
              {__('No', 'alt-context')}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="button button-primary acx-suggestion-card__label"
            onClick={() => onLabel(suggestion.suggested_cluster_id)}
            disabled={isPending}
          >
            {__('Name Person', 'alt-context')}
          </button>
        )}
        {onReview ? (
          <button
            type="button"
            className="button button-link acx-suggestion-card__review"
            onClick={() => onReview(suggestion.suggested_cluster_id)}
            title={__('Review cluster details', 'alt-context')}
          >
            {__('Review details', 'alt-context')}
          </button>
        ) : null}
      </div>
    </div>
  );
};

const GroupedSuggestionCard = ({
  clusterId,
  label,
  suggestions,
  onAcceptAll,
  onToggleReviewEach,
  isExpanded,
  isPending,
  children,
}: GroupedSuggestionCardProps): React.JSX.Element => {
  const topSimilarity = Math.max(...suggestions.map((suggestion) => suggestion.representative_similarity));
  const matchPercent = Math.round(topSimilarity * 100);
  const visibleCandidates = suggestions.slice(0, 8);
  const extraCandidatesCount = Math.max(suggestions.length - visibleCandidates.length, 0);
  const isLowConfidence = topSimilarity < LOW_CONFIDENCE_THRESHOLD;

  return (
    <div
      className={`acx-suggestion-card acx-suggestion-card--group${isLowConfidence ? ' acx-suggestion-card--low-confidence' : ''}`}
      data-cluster-id={clusterId}
    >
      <div className="acx-suggestion-card__faces">
        <div className="acx-suggestion-card__face acx-suggestion-card__face--grid">
          <div className="acx-face-grid-preview acx-face-grid-preview--candidates">
            {visibleCandidates.map((suggestion) =>
              suggestion.identity_media_url && suggestion.identity_bbox ? (
                <FaceThumbnail
                  key={suggestion.id}
                  mediaUrl={suggestion.identity_media_url}
                  bbox={suggestion.identity_bbox}
                  size="sm"
                  alt={__('Candidate face', 'alt-context')}
                  className="acx-suggestion-card__thumb"
                />
              ) : (
                <span key={suggestion.id} className="acx-suggestion-card__thumb acx-suggestion-card__thumb--placeholder" />
              ),
            )}
            {extraCandidatesCount > 0 && (
              <span className="acx-suggestion-card__thumb acx-suggestion-card__thumb--more">
                +{extraCandidatesCount}
              </span>
            )}
          </div>
          <span className="acx-suggestion-card__face-label">
            {suggestions.length} {__('candidates', 'alt-context')}
          </span>
        </div>
      </div>

      <div className="acx-suggestion-card__content">
        <p className="acx-suggestion-card__question">
          <strong>{suggestions.length}</strong> {__('candidates may be', 'alt-context')} <strong>{label}</strong>
        </p>
        <p className="acx-suggestion-card__match">
          {__('Top match', 'alt-context')} {matchPercent}%
          {isLowConfidence && (
            <span className="acx-suggestion-card__confidence-flag">
              {__('Low confidence', 'alt-context')}
            </span>
          )}
        </p>
      </div>

      <div className="acx-suggestion-card__actions">
        <button
          type="button"
          className="button button-primary acx-suggestion-card__accept"
          onClick={onAcceptAll}
          disabled={isPending}
        >
          {__('Yes all', 'alt-context')}
        </button>
        <button
          type="button"
          className="button acx-suggestion-card__review-each"
          onClick={onToggleReviewEach}
          disabled={isPending}
        >
          {isExpanded ? __('Hide details', 'alt-context') : __('Review each', 'alt-context')}
        </button>
      </div>

      {isExpanded ? (
        <div className="acx-suggestion-card__group-items">
          {children}
        </div>
      ) : null}
    </div>
  );
};

/**
 * Panel showing all pending suggestions for user review.
 */
export const SuggestionReviewPanel = ({
  onLabel,
  onReview,
}: {
  onLabel?: (clusterId: string) => void;
  onReview?: (clusterId: string) => void;
}): React.JSX.Element | null => {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = React.useState(true);
  const [expandedGroups, setExpandedGroups] = React.useState<Set<string>>(new Set());
  const [bulkAcceptClusterId, setBulkAcceptClusterId] = React.useState<string | null>(null);
  const contentId = React.useId();
  // Fetch pending suggestions
  const {
    data: assignmentData,
    isLoading: isAssignmentLoading,
    isError: isAssignmentError,
    refetch: refetchAssignment,
    failureCount: assignmentFailureCount,
  } = useQuery({
    queryKey: queryKeys.suggestions.pending(),
    queryFn: () => fetchPendingSuggestions(SUGGESTION_PAGE_SIZE, 0),
    refetchInterval: (query) => (query.state.status === 'error' ? false : 30000),
    retry: 1,
  });

  const {
    data: mergeData,
    isLoading: isMergeLoading,
    isError: isMergeError,
    refetch: refetchMerge,
    failureCount: mergeFailureCount,
  } = useQuery({
    queryKey: queryKeys.suggestions.mergePending(),
    queryFn: () => fetchPendingMergeSuggestions(10, 0),
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

  const acceptMergeMutation = useMutation({
    mutationFn: acceptMergeSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
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

  const rejectMergeMutation = useMutation({
    mutationFn: rejectMergeSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
    },
  });

  const assignmentSuggestions = assignmentData?.suggestions;
  const mergeSuggestions = mergeData?.suggestions ?? [];

  const reviewItems = React.useMemo<SuggestionReviewItem[]>(() => {
    const sortedSuggestions = [...(assignmentSuggestions ?? [])].sort(
      (a, b) => b.representative_similarity - a.representative_similarity,
    );
    const suggestionsByCluster = new Map<string, PendingSuggestion[]>();

    for (const suggestion of sortedSuggestions) {
      const existing = suggestionsByCluster.get(suggestion.suggested_cluster_id);
      if (existing) {
        existing.push(suggestion);
      } else {
        suggestionsByCluster.set(suggestion.suggested_cluster_id, [suggestion]);
      }
    }

    const items: SuggestionReviewItem[] = [];
    for (const [clusterId, suggestions] of suggestionsByCluster.entries()) {
      const firstSuggestion = suggestions[0];
      const label = firstSuggestion.cluster_label ?? firstSuggestion.suggested_label ?? '';

      if (suggestions.length > 1 && label) {
        items.push({
          type: 'group',
          clusterId,
          label,
          suggestions,
          score: Math.max(...suggestions.map((suggestion) => suggestion.representative_similarity)),
        });
        continue;
      }

      for (const suggestion of suggestions) {
        items.push({
          type: 'single',
          score: suggestion.representative_similarity,
          suggestion,
        });
      }
    }

    return items.sort((a, b) => b.score - a.score);
  }, [assignmentSuggestions]);

  const assignmentCount = assignmentData?.total ?? 0;
  const loadedAssignmentCount = assignmentSuggestions?.length ?? 0;

  const hasNoSuggestionData = !assignmentData && !mergeData;
  const hasInitialFailure = (assignmentFailureCount > 0 || mergeFailureCount > 0) && hasNoSuggestionData;
  const isLoading = !hasInitialFailure && ((isAssignmentLoading && !assignmentData) || (isMergeLoading && !mergeData));
  const isError = isAssignmentError && isMergeError && hasNoSuggestionData;
  const failureCount = Math.max(assignmentFailureCount, mergeFailureCount);
  const tenantId = getConfig().tenant_id;
  const isAnyMutationPending =
    acceptMutation.isPending ||
    rejectMutation.isPending ||
    acceptMergeMutation.isPending ||
    rejectMergeMutation.isPending ||
    bulkAcceptClusterId !== null;

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
    if (bulkAcceptClusterId) {
      return;
    }
    setBulkAcceptClusterId(clusterId);
    try {
      await Promise.all(suggestions.map((suggestion) => acceptMutation.mutateAsync(suggestion.id)));
      setExpandedGroups((current) => {
        if (!current.has(clusterId)) {
          return current;
        }
        const next = new Set(current);
        next.delete(clusterId);
        return next;
      });
    } finally {
      setBulkAcceptClusterId(null);
    }
  };

  const renderSuggestionCard = (suggestion: PendingSuggestion): React.JSX.Element => (
    <SuggestionCard
      key={`assign-${suggestion.id}`}
      suggestion={suggestion}
      onAccept={() => acceptMutation.mutate(suggestion.id)}
      onReject={() => rejectMutation.mutate(suggestion.id)}
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

  // On cold start / empty DB, errors are expected (no tenant, no suggestions yet).
  // Keep the surface calm by hiding the panel after first failure instead of showing a spinner forever.
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
    // Only show error after explicit retry attempts
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
          {/* Collapsible Merge Queue */}
          <CollapsibleMergeQueue
            suggestions={mergeSuggestions}
            onAccept={(id) => acceptMergeMutation.mutate(id)}
            onReject={(id) => rejectMergeMutation.mutate(id)}
            isPending={acceptMergeMutation.isPending || rejectMergeMutation.isPending}
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
                      onAcceptAll={() => {
                        void acceptGroupedSuggestions(item.clusterId, item.suggestions);
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

          {/* Top Clusters (Naming Queue) - Always visible if tenantId exists */}
          {tenantId && (
            <div className="acx-naming-queue">
              <TopClustersSection
                tenantId={tenantId}
                onLabel={(clusterId) => {
                  if (onLabel) {
                    onLabel(clusterId);
                  }
                }}
                onReview={(clusterId) => {
                  if (onReview) {
                    onReview(clusterId);
                  }
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
};
