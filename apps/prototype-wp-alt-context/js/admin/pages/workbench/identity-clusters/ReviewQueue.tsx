/**
 * E21-5 Slice 1b — card-at-a-time review queue shell.
 *
 * Renders exactly one review card + filter chips + N-of-M + prev/next.
 * Index is controlled (lifted to ScanTabContent); filter mirrored via kind props.
 * Reuses existing per-kind cards; mutations unchanged this slice.
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import { DATA_SOURCE } from '../../../api/recognition/types';
import type { PendingMergeSuggestion, PendingNameSuggestion } from '../../../api/recognition/types';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';
import {
  filterToKindParam,
  kindParamToFilter,
  type ReviewQueueKindParam,
} from '../../../hooks/workbenchQueueUrl';
import { EmptyStateWarning } from './EmptyStateWarning';
import { MergeSuggestionCard } from './MergeSuggestionCard';
import { ReviewCardLightbox } from './ReviewCardLightbox';
import {
  clampQueueIndex,
  filterReviewQueue,
  NEXT_ACTION_CHIP_LABEL,
  NEXT_ACTION_KIND,
  nextQueueIndex,
  prevQueueIndex,
  REVIEW_QUEUE_DRAIN_MESSAGE,
  REVIEW_QUEUE_FILTER,
  type ReviewQueueFilter,
  type ReviewQueueItem,
} from './reviewQueueDriver';
import { SuggestionCard, type FaceOriginalTarget, type ReviewSuggestion } from './SuggestionCards';
import { TopClusterCard } from './TopClusterCard';
import { useSuggestionReviewData } from './useSuggestionReviewData';
import { useSuggestionReviewQueries } from './useSuggestionReviewQueries';
import { useWorkbenchFindings } from './useWorkbenchFindings';

const LOW_CONFIDENCE_THRESHOLD = 0.6;

export interface ReviewQueueHandle {
  focusCurrentCard: () => void;
}

export interface ReviewQueueProps {
  /** Controlled queue index (lifted — survives panel unmount). */
  index: number;
  onIndexChange: (index: number) => void;
  /** Controlled kind filter from URL. */
  kind: ReviewQueueKindParam;
  onKindChange: (kind: ReviewQueueKindParam) => void;
  onLabel?: (clusterId: string) => void;
  onReview?: (clusterId: string) => void;
  /** Anchor div for drain-focus (tabIndex=-1). */
  emptyStateAnchorRef?: React.RefObject<HTMLElement | null>;
}

const queueItemKey = (item: ReviewQueueItem): string => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
      return `assignment:${item.suggestionId}`;
    case NEXT_ACTION_KIND.MERGE:
      return `merge:${item.suggestionId}`;
    case NEXT_ACTION_KIND.NAME:
      return `name:${item.suggestionId}`;
    case NEXT_ACTION_KIND.CLUSTER:
      return `cluster:${item.clusterId}`;
  }
};

const flattenAssignmentSuggestions = (
  reviewItems: ReturnType<typeof useSuggestionReviewData>['reviewItems'],
): Map<string, ReviewSuggestion> => {
  const map = new Map<string, ReviewSuggestion>();
  for (const item of reviewItems) {
    if (item.type === 'group') {
      for (const suggestion of item.suggestions) {
        map.set(suggestion.suggestionId, suggestion);
      }
    } else {
      map.set(item.suggestion.suggestionId, item.suggestion);
    }
  }
  return map;
};

export const ReviewQueue = React.forwardRef<ReviewQueueHandle, ReviewQueueProps>(
  function ReviewQueue(
    { index, onIndexChange, kind, onKindChange, onLabel, onReview, emptyStateAnchorRef },
    ref,
  ): React.JSX.Element | null {
    const findings = useWorkbenchFindings();
    const data = useSuggestionReviewData();
    const { topUnlabeledClusters } = useSuggestionReviewQueries();
    const cardRegionRef = React.useRef<HTMLDivElement>(null);
    const [lightbox, setLightbox] = React.useState<FaceOriginalTarget | null>(null);
    const [liveMessage, setLiveMessage] = React.useState('');
    const previousItemKeyRef = React.useRef<string | null>(null);
    const pendingFocusAfterRemovalRef = React.useRef(false);

    const filter: ReviewQueueFilter = kindParamToFilter(kind);
    const filteredQueue = React.useMemo(
      () => filterReviewQueue(findings.queue, filter),
      [findings.queue, filter],
    );

    const length = filteredQueue.length;
    const safeIndex = clampQueueIndex(index, length);
    // BR-06: gate clamp on all four source queries settled — partial
    // assignment+merge resolve must not wipe a restored rq= index.
    const queueSettled = findings.queueSettled;

    // Clamp restored/oversized index back to parent (PR-54).
    React.useEffect(() => {
      if (!queueSettled) {
        return;
      }
      if (length > 0 && index !== safeIndex) {
        onIndexChange(safeIndex);
      } else if (length === 0 && index !== 0) {
        onIndexChange(0);
      }
    }, [index, safeIndex, length, onIndexChange, queueSettled]);

    const currentItem = length > 0 ? filteredQueue[safeIndex] : null;
    const currentKey = currentItem ? queueItemKey(currentItem) : null;

    const assignmentById = React.useMemo(
      () => flattenAssignmentSuggestions(data.reviewItems),
      [data.reviewItems],
    );
    const mergeById = React.useMemo(() => {
      const map = new Map<string, PendingMergeSuggestion>();
      for (const suggestion of data.mergeSuggestions) {
        map.set(suggestion.id, suggestion);
      }
      return map;
    }, [data.mergeSuggestions]);
    const nameById = React.useMemo(() => {
      const map = new Map<string, PendingNameSuggestion>();
      for (const suggestion of data.nameSuggestions) {
        map.set(suggestion.id, suggestion);
      }
      return map;
    }, [data.nameSuggestions]);
    const topClustersById = React.useMemo(() => {
      const map = new Map<string, TopUnlabeledCluster>();
      for (const cluster of topUnlabeledClusters) {
        map.set(cluster.id, cluster);
      }
      return map;
    }, [topUnlabeledClusters]);

    const focusPrimaryInCard = React.useCallback((): void => {
      const root = cardRegionRef.current;
      if (!root) {
        emptyStateAnchorRef?.current?.focus({ preventScroll: true });
        return;
      }
      const primary =
        root.querySelector<HTMLElement>('.acx-suggestion-card__accept') ??
        root.querySelector<HTMLElement>('.acx-top-cluster-card__title-action') ??
        root.querySelector<HTMLElement>('.acx-button--primary') ??
        root.querySelector<HTMLElement>('button.button-primary') ??
        root.querySelector<HTMLElement>('button:not([disabled])');
      primary?.focus({ preventScroll: true });
    }, [emptyStateAnchorRef]);

    const focusCurrentCard = React.useCallback((): void => {
      if (length === 0) {
        emptyStateAnchorRef?.current?.focus({ preventScroll: true });
        return;
      }
      focusPrimaryInCard();
    }, [emptyStateAnchorRef, focusPrimaryInCard, length]);

    React.useImperativeHandle(ref, () => ({ focusCurrentCard }), [focusCurrentCard]);

    // Card transition announce + post-removal focus placement.
    React.useEffect(() => {
      if (currentKey && currentKey !== previousItemKeyRef.current) {
        if (previousItemKeyRef.current !== null) {
          setLiveMessage(
            sprintf(
              /* translators: 1: current 1-based position, 2: total */
              __('Review item %1$d of %2$d', 'alt-context'),
              safeIndex + 1,
              length,
            ),
          );
        }
        previousItemKeyRef.current = currentKey;
        if (pendingFocusAfterRemovalRef.current) {
          pendingFocusAfterRemovalRef.current = false;
          requestAnimationFrame(() => focusPrimaryInCard());
        }
        return;
      }

      if (!currentKey && previousItemKeyRef.current !== null) {
        previousItemKeyRef.current = null;
        setLiveMessage(__(REVIEW_QUEUE_DRAIN_MESSAGE, 'alt-context'));
        if (pendingFocusAfterRemovalRef.current) {
          pendingFocusAfterRemovalRef.current = false;
          requestAnimationFrame(() => {
            emptyStateAnchorRef?.current?.focus({ preventScroll: true });
          });
        }
      }
    }, [currentKey, emptyStateAnchorRef, focusPrimaryInCard, length, safeIndex]);

    const markAdvanceFocus = React.useCallback((): void => {
      pendingFocusAfterRemovalRef.current = true;
    }, []);

    const clearAdvanceFocus = React.useCallback((): void => {
      pendingFocusAfterRemovalRef.current = false;
    }, []);

    const handleFilterClick = (nextFilter: ReviewQueueFilter): void => {
      // BR-14: KIND chips toggle — active chip returns to unfiltered/all.
      if (nextFilter === filter) {
        onKindChange(filterToKindParam(REVIEW_QUEUE_FILTER.ALL));
        onIndexChange(0);
        return;
      }
      onKindChange(filterToKindParam(nextFilter));
      onIndexChange(0);
    };

    const handlePrev = (): void => {
      onIndexChange(prevQueueIndex(safeIndex, length));
    };

    const handleNext = (): void => {
      onIndexChange(nextQueueIndex(safeIndex, length));
    };

    if (data.hasInitialFailure && data.failureCount <= 2) {
      return null;
    }

    if (data.isLoading || findings.isLoading) {
      return (
        <div className="acx-review-queue acx-review-queue--loading" role="status" aria-live="polite">
          <p>{__('Loading review queue…', 'alt-context')}</p>
        </div>
      );
    }

    if (data.isError && findings.isError) {
      return (
        <div className="acx-review-queue acx-review-queue--error">
          <p>{__('Failed to load suggestions.', 'alt-context')}</p>
          <button
            type="button"
            className="button"
            onClick={() => void data.refetchAssignment().then(() => data.refetchMerge())}
          >
            {__('Retry', 'alt-context')}
          </button>
        </div>
      );
    }

    const showUnavailableWarning =
      length === 0 && data.assignmentDataSource === DATA_SOURCE.UNAVAILABLE;
    const showEndpointErrorWarning =
      length === 0 && data.assignmentDataSource === DATA_SOURCE.ENDPOINT_ERROR;

    return (
      <div className="acx-review-queue">
        <header className="acx-review-queue__header">
          <h3 className="acx-review-queue__title">{__('Review Suggestions', 'alt-context')}</h3>
          {length > 0 ? (
            <span className="acx-review-queue__count" aria-hidden="true">
              {length}
            </span>
          ) : null}
        </header>

        <div className="acx-review-queue__chrome">
          <div className="acx-review-queue__chips" role="group" aria-label={__('Filter review queue', 'alt-context')}>
            <button
              type="button"
              className={`acx-review-queue__chip${filter === REVIEW_QUEUE_FILTER.ASSIGNMENT ? ' is-active' : ''}`}
              aria-pressed={filter === REVIEW_QUEUE_FILTER.ASSIGNMENT}
              onClick={() => handleFilterClick(REVIEW_QUEUE_FILTER.ASSIGNMENT)}
            >
              {NEXT_ACTION_CHIP_LABEL[NEXT_ACTION_KIND.ASSIGNMENT]}
            </button>
            <button
              type="button"
              className={`acx-review-queue__chip${filter === REVIEW_QUEUE_FILTER.MERGE ? ' is-active' : ''}`}
              aria-pressed={filter === REVIEW_QUEUE_FILTER.MERGE}
              onClick={() => handleFilterClick(REVIEW_QUEUE_FILTER.MERGE)}
            >
              {NEXT_ACTION_CHIP_LABEL[NEXT_ACTION_KIND.MERGE]}
            </button>
          </div>

          <div className="acx-review-queue__nav">
            <span className="acx-review-queue__position" aria-live="polite">
              {length === 0
                ? __('0 of 0', 'alt-context')
                : sprintf(
                    /* translators: 1: current 1-based position, 2: total */
                    __('%1$d of %2$d', 'alt-context'),
                    safeIndex + 1,
                    length,
                  )}
            </span>
            <button
              type="button"
              className="acx-review-queue__nav-button"
              onClick={handlePrev}
              disabled={length === 0 || safeIndex <= 0}
              aria-label={__('Previous review item', 'alt-context')}
            >
              {__('Previous', 'alt-context')}
            </button>
            <button
              type="button"
              className="acx-review-queue__nav-button"
              onClick={handleNext}
              disabled={length === 0 || safeIndex >= length - 1}
              aria-label={__('Next review item', 'alt-context')}
            >
              {__('Next', 'alt-context')}
            </button>
          </div>
        </div>

        <div className="acx-review-queue__live" role="status" aria-live="polite">
          {liveMessage}
        </div>

        <div ref={cardRegionRef} className="acx-review-queue__card-region">
          {showUnavailableWarning ? (
            <EmptyStateWarning
              title={__('Suggestion service not configured', 'alt-context')}
              message={__(
                'Check the recognition service connection, then retry loading suggestions.',
                'alt-context',
              )}
              onRetry={() => void data.refetchAssignment().then(() => data.refetchMerge())}
            />
          ) : showEndpointErrorWarning ? (
            <EmptyStateWarning
              title={__('Suggestion service error', 'alt-context')}
              message={__(
                'The recognition service responded with an error. Retry now or check the service logs.',
                'alt-context',
              )}
              onRetry={() => void data.refetchAssignment().then(() => data.refetchMerge())}
            />
          ) : length === 0 || !currentItem ? (
            <p className="acx-review-queue__empty">{__(REVIEW_QUEUE_DRAIN_MESSAGE, 'alt-context')}</p>
          ) : (
            <CurrentCard
              item={currentItem}
              assignmentById={assignmentById}
              mergeById={mergeById}
              nameById={nameById}
              topClustersById={topClustersById}
              isPending={data.isAnyMutationPending}
              mutations={data.mutations}
              onReview={onReview}
              onLabel={onLabel}
              onOpenOriginal={(target) => setLightbox(target)}
              markAdvanceFocus={markAdvanceFocus}
              clearAdvanceFocus={clearAdvanceFocus}
            />
          )}
        </div>

        {lightbox ? (
          <ReviewCardLightbox
            open
            onOpenChange={(open) => {
              if (!open) {
                setLightbox(null);
              }
            }}
            mediaUrl={lightbox.mediaUrl}
            bbox={lightbox.bbox}
            label={lightbox.label}
          />
        ) : null}
      </div>
    );
  },
);

interface CurrentCardProps {
  item: ReviewQueueItem;
  assignmentById: Map<string, ReviewSuggestion>;
  mergeById: Map<string, PendingMergeSuggestion>;
  nameById: Map<string, PendingNameSuggestion>;
  topClustersById: Map<string, TopUnlabeledCluster>;
  isPending: boolean;
  mutations: ReturnType<typeof useSuggestionReviewData>['mutations'];
  onReview?: (clusterId: string) => void;
  onLabel?: (clusterId: string) => void;
  onOpenOriginal: (target: FaceOriginalTarget) => void;
  markAdvanceFocus: () => void;
  clearAdvanceFocus: () => void;
}

const CurrentCard = ({
  item,
  assignmentById,
  mergeById,
  nameById,
  topClustersById,
  isPending,
  mutations,
  onReview,
  onLabel,
  onOpenOriginal,
  markAdvanceFocus,
  clearAdvanceFocus,
}: CurrentCardProps): React.JSX.Element | null => {
  // BR-13: drop stale pending-focus when the mutation fails so a later key
  // change (e.g. Next) does not surprise-focus.
  const mutateWithAdvanceFocus = <TVariables,>(
    mutate: (variables: TVariables, options?: { onError?: () => void }) => void,
    variables: TVariables,
  ): void => {
    markAdvanceFocus();
    mutate(variables, { onError: clearAdvanceFocus });
  };

  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT: {
      const suggestion = assignmentById.get(item.suggestionId);
      if (!suggestion) {
        return (
          <p className="acx-review-queue__empty">{__('This suggestion is no longer available.', 'alt-context')}</p>
        );
      }
      const remainingInRun = item.runSize - item.runIndex - 1;
      const runHint =
        item.runSize > 1 && remainingInRun > 0 && item.label
          ? sprintf(
              /* translators: 1: remaining count after this card, 2: person label */
              __('%1$d more for %2$s', 'alt-context'),
              remainingInRun,
              item.label,
            )
          : null;
      return (
        <>
          {runHint ? <p className="acx-review-queue__run-hint">{runHint}</p> : null}
          <SuggestionCard
            suggestion={suggestion}
            lowConfidenceThreshold={LOW_CONFIDENCE_THRESHOLD}
            onAccept={() => {
              mutateWithAdvanceFocus(mutations.accept.mutate, suggestion.suggestionId);
            }}
            onReject={() => {
              mutateWithAdvanceFocus(mutations.reject.mutate, suggestion.suggestionId);
            }}
            onReview={(clusterId) => {
              if (onReview && clusterId) {
                onReview(clusterId);
              }
            }}
            onOpenOriginal={onOpenOriginal}
            isPending={isPending}
          />
        </>
      );
    }
    case NEXT_ACTION_KIND.MERGE: {
      const suggestion = mergeById.get(item.suggestionId);
      if (!suggestion) {
        return (
          <p className="acx-review-queue__empty">{__('This suggestion is no longer available.', 'alt-context')}</p>
        );
      }
      return (
        <MergeSuggestionCard
          suggestion={suggestion}
          onAccept={() => {
            mutateWithAdvanceFocus(mutations.acceptMerge.mutate, suggestion.id);
          }}
          onReject={() => {
            mutateWithAdvanceFocus(mutations.rejectMerge.mutate, suggestion.id);
          }}
          onOpenOriginal={onOpenOriginal}
          isPending={mutations.acceptMerge.isPending || mutations.rejectMerge.isPending}
        />
      );
    }
    case NEXT_ACTION_KIND.NAME: {
      const suggestion = nameById.get(item.suggestionId);
      if (!suggestion) {
        return (
          <p className="acx-review-queue__empty">{__('This suggestion is no longer available.', 'alt-context')}</p>
        );
      }
      const isLow =
        suggestion.confidence_score !== null &&
        suggestion.confidence_score !== undefined &&
        suggestion.confidence_score < LOW_CONFIDENCE_THRESHOLD;
      return (
        <div
          className="acx-suggestion-card acx-name-suggestion-card"
          data-testid="acx-review-card"
          data-review-kind="name"
        >
          <div className="acx-suggestion-card__content">
            <p className="acx-suggestion-card__question">
              {__('Suggested name:', 'alt-context')} <strong>{suggestion.suggested_name}</strong>
            </p>
            {suggestion.confidence_score !== null && suggestion.confidence_score !== undefined ? (
              <p className="acx-suggestion-card__match">
                <span
                  className={`acx-suggestion-confidence${isLow ? ' acx-suggestion-confidence--low' : ''}`}
                >
                  {Math.round(suggestion.confidence_score * 100)}%
                </span>
              </p>
            ) : null}
          </div>
          <div className="acx-name-suggestion-card__actions acx-suggestion-card__actions">
            <button
              type="button"
              className="button button-primary acx-suggestion-card__accept"
              disabled={mutations.acceptName.isPending || mutations.rejectName.isPending}
              onClick={() => {
                mutateWithAdvanceFocus(mutations.acceptName.mutate, suggestion.id);
              }}
            >
              {__('Accept', 'alt-context')}
            </button>
            <button
              type="button"
              className="button acx-suggestion-card__reject"
              disabled={mutations.acceptName.isPending || mutations.rejectName.isPending}
              onClick={() => {
                mutateWithAdvanceFocus(mutations.rejectName.mutate, suggestion.id);
              }}
            >
              {__('Reject', 'alt-context')}
            </button>
          </div>
        </div>
      );
    }
    case NEXT_ACTION_KIND.CLUSTER: {
      const cluster = topClustersById.get(item.clusterId);
      if (!cluster) {
        return (
          <p className="acx-review-queue__empty">{__('This cluster is no longer available.', 'alt-context')}</p>
        );
      }
      return (
        <div data-testid="acx-review-card" data-review-kind="cluster">
          <TopClusterCard
            cluster={cluster}
            onLabel={(clusterId) => onLabel?.(clusterId)}
            onReview={onReview}
          />
        </div>
      );
    }
    default:
      return null;
  }
};
