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
  type PendingMergeSuggestion,
} from '../../../api/recognition';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import { TopClustersSection } from './TopClustersSection';
import { getConfig } from '../../../api/config';

interface SuggestionCardProps {
  suggestion: PendingSuggestion;
  onAccept: () => void;
  onReject: () => void;
  onLabel: (clusterId?: string) => void;
  onReview?: (clusterId?: string) => void;
  isPending: boolean;
}

interface MergeSuggestionCardProps {
  suggestion: PendingMergeSuggestion;
  onAccept: () => void;
  onReject: () => void;
  isPending: boolean;
}

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
  const suggestedLabel = suggestion.suggested_label;
  const hasLabel = Boolean(suggestion.cluster_label ?? suggestedLabel);
  const displayLabel = suggestion.cluster_label ?? suggestedLabel ?? __('Unnamed cluster', 'alt-context');

  const hasIdentityFace = Boolean(suggestion.identity_media_url && suggestion.identity_bbox);
  // We use cluster_thumbnails if available, otherwise fallback to representative
  const clusterThumbnails = suggestion.cluster_thumbnails ?? [];
  const showGrid = clusterThumbnails.length > 1;

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
    <div className="acx-suggestion-card">
      <div className="acx-suggestion-card__faces">
        <div className="acx-suggestion-card__face">
          {hasIdentityFace ? (
            <FaceThumbnail
              mediaUrl={suggestion.identity_media_url!}
              bbox={suggestion.identity_bbox!}
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
            <div
              className="acx-face-grid-preview"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(2, 1fr)',
                gap: '2px',
                width: 'var(--acx-thumb-size-md, 80px)',
                height: 'var(--acx-thumb-size-md, 80px)',
                overflow: 'hidden',
                borderRadius: '4px',
              }}
            >
              {clusterThumbnails.slice(0, 4).map((url, idx) => (
                <img key={idx} src={url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              ))}
            </div>
          ) : suggestion.representative_media_url ? (
            <FaceThumbnail
              mediaUrl={suggestion.representative_media_url}
              bbox={suggestion.representative_bbox!}
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

const MergeSuggestionCard = ({
  suggestion,
  onAccept,
  onReject,
  isPending,
}: MergeSuggestionCardProps): React.JSX.Element => {
  const matchPercent = Math.round(suggestion.similarity * 100);
  const clusterALabel = suggestion.cluster_a_label ?? __('Unnamed cluster', 'alt-context');
  const clusterBLabel = suggestion.cluster_b_label ?? __('Unnamed cluster', 'alt-context');
  const hasClusterAFace = Boolean(
    suggestion.cluster_a_representative_media_url && suggestion.cluster_a_representative_bbox,
  );
  const hasClusterBFace = Boolean(
    suggestion.cluster_b_representative_media_url && suggestion.cluster_b_representative_bbox,
  );
  const clusterACount = suggestion.cluster_a_identity_count;
  const clusterBCount = suggestion.cluster_b_identity_count;

  return (
    <div className="acx-suggestion-card acx-suggestion-card--merge">
      <div className="acx-suggestion-card__faces">
        <div className="acx-suggestion-card__face">
          {hasClusterAFace ? (
            <FaceThumbnail
              mediaUrl={suggestion.cluster_a_representative_media_url!}
              bbox={suggestion.cluster_a_representative_bbox!}
              size="md"
              alt={__('Cluster representative', 'alt-context')}
              className="acx-suggestion-card__thumb"
            />
          ) : (
            <span className="acx-suggestion-card__thumb acx-suggestion-card__thumb--placeholder" />
          )}
          <span className="acx-suggestion-card__face-label">
            {clusterALabel}
            {clusterACount ? ` (${clusterACount})` : ''}
          </span>
        </div>
        <div className="acx-suggestion-card__face">
          {hasClusterBFace ? (
            <FaceThumbnail
              mediaUrl={suggestion.cluster_b_representative_media_url!}
              bbox={suggestion.cluster_b_representative_bbox!}
              size="md"
              alt={__('Cluster representative', 'alt-context')}
              className="acx-suggestion-card__thumb"
            />
          ) : (
            <span className="acx-suggestion-card__thumb acx-suggestion-card__thumb--placeholder" />
          )}
          <span className="acx-suggestion-card__face-label">
            {clusterBLabel}
            {clusterBCount ? ` (${clusterBCount})` : ''}
          </span>
        </div>
      </div>
      <div className="acx-suggestion-card__content">
        <p className="acx-suggestion-card__question">{__('Are these the same person?', 'alt-context')}</p>
        <p className="acx-suggestion-card__match">
          {matchPercent}% {__('match', 'alt-context')}
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
export const SuggestionReviewPanel = ({
  onLabel,
  onReview,
}: {
  onLabel?: (clusterId: string) => void;
  onReview?: (clusterId: string) => void;
}): React.JSX.Element | null => {
  const queryClient = useQueryClient();
  // Fetch pending suggestions
  const {
    data: assignmentData,
    isLoading: isAssignmentLoading,
    isError: isAssignmentError,
    refetch: refetchAssignment,
    failureCount: assignmentFailureCount,
  } = useQuery({
    queryKey: queryKeys.suggestions.pending(),
    queryFn: () => fetchPendingSuggestions(10, 0),
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

  const assignmentSuggestions = assignmentData?.suggestions ?? [];
  const mergeSuggestions = mergeData?.suggestions ?? [];
  const reviewItems = [
    ...assignmentSuggestions.map((suggestion) => ({
      type: 'assignment' as const,
      score: suggestion.representative_similarity,
      suggestion,
    })),
    ...mergeSuggestions.map((suggestion) => ({
      type: 'merge' as const,
      score: suggestion.similarity,
      suggestion,
    })),
  ].sort((a, b) => b.score - a.score);
  const totalCount = (assignmentData?.total ?? 0) + (mergeData?.total ?? 0);
  const isLoading = (isAssignmentLoading && !assignmentData) || (isMergeLoading && !mergeData);
  const isError = isAssignmentError && isMergeError && !assignmentData && !mergeData;
  const failureCount = Math.max(assignmentFailureCount, mergeFailureCount);

  if (isLoading) {
    return (
      <div className="acx-suggestion-panel acx-suggestion-panel--loading">
        <p>{__('Loading suggestions...', 'alt-context')}</p>
      </div>
    );
  }

  // On cold start / empty DB, errors are expected (no tenant, no suggestions yet).
  // Only show error UI if user explicitly retries. Initial errors are silent.
  if (isError) {
    // Cold start: hide panel entirely on initial load failure
    // This avoids showing scary "Failed to load" on empty DBs
    if (failureCount <= 2) {
      return null;
    }
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

  // Get tenant ID for top clusters query
  const tenantId = getConfig().tenant_id;

  // When no suggestions, show top unlabeled clusters instead
  if (reviewItems.length === 0) {
    return (
      <div className="acx-suggestion-panel acx-suggestion-panel--empty">
        <h3 className="acx-suggestion-panel__title">{__('Review Suggestions', 'alt-context')}</h3>
        {tenantId ? (
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
        ) : (
          <p className="acx-suggestion-panel__description">{__('No suggestions to review yet.', 'alt-context')}</p>
        )}
      </div>
    );
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
        {reviewItems.map((item) =>
          item.type === 'assignment' ? (
            <SuggestionCard
              key={`assign-${item.suggestion.id}`}
              suggestion={item.suggestion}
              onAccept={() => acceptMutation.mutate(item.suggestion.id)}
              onReject={() => rejectMutation.mutate(item.suggestion.id)}
              onLabel={(clusterId) => {
                if (onLabel) {
                  // PendingSuggestion has suggested_cluster_id (target) and identity_id (candidate).
                  // If we want to label the CLUSTER, we use suggested_cluster_id.
                  onLabel(clusterId ?? item.suggestion.suggested_cluster_id);
                }
              }}
              onReview={(clusterId) => {
                if (onReview && clusterId) {
                  onReview(clusterId);
                }
              }}
              isPending={
                acceptMutation.isPending ||
                rejectMutation.isPending ||
                acceptMergeMutation.isPending ||
                rejectMergeMutation.isPending
              }
            />
          ) : (
            <MergeSuggestionCard
              key={`merge-${item.suggestion.id}`}
              suggestion={item.suggestion}
              onAccept={() => acceptMergeMutation.mutate(item.suggestion.id)}
              onReject={() => rejectMergeMutation.mutate(item.suggestion.id)}
              isPending={
                acceptMutation.isPending ||
                rejectMutation.isPending ||
                acceptMergeMutation.isPending ||
                rejectMergeMutation.isPending
              }
            />
          ),
        )}
      </div>

      {totalCount > reviewItems.length && (
        <p className="acx-suggestion-panel__more">
          {__('and', 'alt-context')} {totalCount - reviewItems.length} {__('more...', 'alt-context')}
        </p>
      )}
    </div>
  );
};
