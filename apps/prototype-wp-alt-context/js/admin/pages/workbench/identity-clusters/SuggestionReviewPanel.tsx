/**
 * Panel for reviewing pending identity suggestions.
 * Shows "Is this X?" prompts for borderline matches that need user confirmation.
 * Also shows top unlabeled clusters when no suggestions are pending.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  acceptMergeSuggestion,
  acceptSuggestion,
  fetchPendingMergeSuggestions,
  fetchPendingSuggestions,
  rejectMergeSuggestion,
  rejectSuggestion,
  type PendingSuggestionsResponse,
  type PendingSuggestion,
} from '../../../api/recognition';
import { getConfig } from '../../../api/config';
import { CollapsibleMergeQueue } from './CollapsibleMergeQueue';
import { GroupedSuggestionCard, SuggestionCard } from './SuggestionCards';
import { buildSuggestionReviewItems } from './suggestionReviewItems';
import { TopClustersSection } from './TopClustersSection';

const LOW_CONFIDENCE_THRESHOLD = 0.6;
const SUGGESTION_PAGE_SIZE = 25;

interface SuggestionReviewPanelProps {
  onLabel?: (clusterId: string) => void;
  onReview?: (clusterId: string) => void;
}

export const SuggestionReviewPanel = ({ onLabel, onReview }: SuggestionReviewPanelProps): React.JSX.Element | null => {
  const queryClient = useQueryClient();
  const [isOpen, setIsOpen] = React.useState(true);
  const [expandedGroups, setExpandedGroups] = React.useState<Set<string>>(new Set());
  const [bulkActionClusterId, setBulkActionClusterId] = React.useState<string | null>(null);
  const bulkActionRef = React.useRef(false);
  const contentId = React.useId();

  const removePendingSuggestionFromCache = React.useCallback(
    (suggestionId: string) => {
      queryClient.setQueryData<PendingSuggestionsResponse | undefined>(queryKeys.suggestions.pending(), (current) => {
        if (!current) {
          return current;
        }
        const filtered = current.suggestions.filter((suggestion) => suggestion.id !== suggestionId);
        if (filtered.length === current.suggestions.length) {
          return current;
        }
        return {
          ...current,
          suggestions: filtered,
          total: Math.max(0, current.total - 1),
        };
      });
    },
    [queryClient],
  );

  const invalidateSuggestionQueries = React.useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
  }, [queryClient]);

  const {
    data: assignmentData,
    isLoading: isAssignmentLoading,
    isError: isAssignmentError,
    refetch: refetchAssignment,
    failureCount: assignmentFailureCount,
  } = useQuery({
    queryKey: queryKeys.suggestions.pending(),
    queryFn: () => fetchPendingSuggestions(SUGGESTION_PAGE_SIZE, 0),
    refetchInterval: false,
    retry: false,
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
    refetchInterval: false,
    retry: false,
  });

  const acceptMutation = useMutation({
    mutationFn: acceptSuggestion,
    onMutate: async (suggestionId: string) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.suggestions.pending() });
      const previous = queryClient.getQueryData<PendingSuggestionsResponse>(queryKeys.suggestions.pending());
      removePendingSuggestionFromCache(suggestionId);
      return { previous };
    },
    onError: (error, _suggestionId, context) => {
      console.warn('[SuggestionReviewPanel] accept failed, restoring cache:', error);
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.suggestions.pending(), context.previous);
      }
    },
    onSettled: () => {
      if (!bulkActionRef.current) {
        invalidateSuggestionQueries();
        void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      }
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

  const rejectMutation = useMutation({
    mutationFn: rejectSuggestion,
    onMutate: async (suggestionId: string) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.suggestions.pending() });
      const previous = queryClient.getQueryData<PendingSuggestionsResponse>(queryKeys.suggestions.pending());
      removePendingSuggestionFromCache(suggestionId);
      return { previous };
    },
    onError: (error, _suggestionId, context) => {
      console.warn('[SuggestionReviewPanel] reject failed, restoring cache:', error);
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.suggestions.pending(), context.previous);
      }
    },
    onSuccess: (_data, suggestionId) => {
      removePendingSuggestionFromCache(suggestionId);
    },
    onSettled: () => {
      if (!bulkActionRef.current) {
        invalidateSuggestionQueries();
      }
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
  const reviewItems = React.useMemo(() => buildSuggestionReviewItems(assignmentSuggestions), [assignmentSuggestions]);

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
    bulkActionClusterId !== null;

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
      bulkActionRef.current = false;
      setBulkActionClusterId(null);
      invalidateSuggestionQueries();
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
    }
  };

  const rejectGroupedSuggestions = async (clusterId: string, suggestions: PendingSuggestion[]): Promise<void> => {
    if (bulkActionClusterId) {
      return;
    }
    setBulkActionClusterId(clusterId);
    bulkActionRef.current = true;
    try {
      await Promise.all(suggestions.map((suggestion) => rejectMutation.mutateAsync(suggestion.id)));
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
