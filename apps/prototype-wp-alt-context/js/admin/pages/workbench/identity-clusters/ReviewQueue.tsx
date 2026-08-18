/**
 * E21-5 Slice 1b–6 — card-at-a-time review queue + hold + person-commit + multi-select bulk + bands.
 *
 * Renders exactly one review card + KIND/band filter chips + N-of-M + prev/next + selection tray.
 * Index + selection are controlled (lifted to ScanTabContent); kind/band mirrored via props/`rq=`.
 * Accept/reject rides the Slice-2 hold/flush/gated-advance mutation choreography.
 * Person-commit (Slice 3) is flush-then-immediate; no undo window.
 * Multi-select bulk (Slice 5): sequential per-id accepts, PR-30 state machine, PR-38 labels.
 * Band chips (Slice 6 ④): preset similarity filters; bulk preview/commit = selection ∩ filters (M2).
 */

import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import { AlertTriangle } from 'lucide-react';

import { DATA_SOURCE } from '../../../api/recognition/types';
import type { PendingMergeSuggestion, PendingNameSuggestion } from '../../../api/recognition/types';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';
import {
  bandParamToBand,
  bandToBandParam,
  filterToKindParam,
  kindParamToFilter,
  type ReviewQueueBandParam,
  type ReviewQueueKindParam,
} from '../../../hooks/workbenchQueueUrl';
import { UserFacingErrorNotice } from '../../../components/ui/UserFacingErrorNotice';
import { EmptyStateWarning } from './EmptyStateWarning';
import { QUERY_RETRY_COPY, QueryRetryButton, settledRefetchFailed } from './queryRetry';
import { MergeSuggestionCard } from './MergeSuggestionCard';
import { PersonCommitControl } from './PersonCommitControl';
import {
  PERSON_COMMIT_FAILURE_COPY,
  PERSON_COMMIT_SUCCESS_COPY,
  VIEW_IN_ROSTER_COPY,
  VIEW_IN_ROSTER_HREF,
} from './personCommitCopy';
import { shouldShowPersonCommit, isPersonCommitPrimaryKind } from './personCommitVisibility';
import { ReviewCardLightbox } from './ReviewCardLightbox';
import {
  clampQueueIndex,
  filterReviewQueueComposite,
  intersectSelectionWithFilters,
  NEXT_ACTION_CHIP_LABEL,
  NEXT_ACTION_KIND,
  nextQueueIndex,
  prevQueueIndex,
  REVIEW_QUEUE_BAND,
  REVIEW_QUEUE_BAND_CHIP_LABEL,
  REVIEW_QUEUE_DRAIN_MESSAGE,
  REVIEW_QUEUE_FILTER,
  SELECTION_SPLIT_MESSAGE,
  type ReviewQueueBand,
  type ReviewQueueFilter,
  type ReviewQueueItem,
} from './reviewQueueDriver';
import { gatedClusterCopy } from './representativeVocabulary';
import { SuggestionCard, type FaceOriginalTarget, type ReviewSuggestion } from './SuggestionCards';
import { ReviewCardGroupShell } from './reviewCardGroupAccname';
import { TopClusterCard } from './TopClusterCard';
import {
  BULK_COMMIT_PHASE,
  useBulkReviewCommit,
  type BulkCommitItem,
} from './useBulkReviewCommit';
import { useMergeSurvivors } from './MergeSurvivorContext';
import { useSelectedClusterTruncation } from './useSelectedClusterTruncation';
import { useSuggestionReviewData } from './useSuggestionReviewData';
import {
  COMMIT_HOLD_PHASE,
  HOLD_COMMITTING_STATUS_COPY,
  HOLD_STATUS_COPY,
  PERSON_COMMIT_PHASE,
  type CommitHoldPhase,
  type PersonCommitRequest,
  type PersonCommitResult,
  type PersonCommitState,
  type ScheduleCommitResult,
  type SuggestionCommitKind,
} from './useSuggestionReviewMutations';
import { useSuggestionReviewQueries } from './useSuggestionReviewQueries';
import { useAriaAnnounce } from './useAriaAnnounce';
import { useLiveReviewTarget } from './useLiveReviewTarget';
import { useWorkbenchFindings } from './useWorkbenchFindings';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';

/**
 * Filtered-empty copy — visual + AT share one string.
 * [COG-03] not a true drain when filters hide work; [A11Y-06] second channel.
 */
const REVIEW_QUEUE_FILTERED_EMPTY_MESSAGE = 'No items match the current filters.';

/** Top-unlabeled projection outage copy — one canonical string for visual + AT. */
const REVIEW_QUEUE_TOP_UNLABELED_ERROR_MESSAGE = 'Unable to load unlabeled groups.';

/** Empty-queue position copy when the projection outage makes the count unmeasurable. */
const REVIEW_QUEUE_POSITION_UNAVAILABLE_MESSAGE = 'Position unavailable';

/** Visual count when the full loaded page is in view (no kind/band chip). */
export const REVIEW_QUEUE_COUNT_PAGE = '%d left to review on this page';
/** Visual count when a kind or strength-band chip is active. */
export const REVIEW_QUEUE_COUNT_FILTERED = '%d shown';
/** aria-live position line — carries the loaded-page / filtered scope (A11Y-21). */
export const REVIEW_QUEUE_POSITION_PAGE = '%1$d of %2$d on this page';
export const REVIEW_QUEUE_POSITION_FILTERED = '%1$d of %2$d shown';

export const REVIEW_QUEUE_LABEL_SAVED_ANNOUNCE = 'Name saved. Back to review suggestions.';

/** Cluster id for person-commit chrome / orphaned status surface (item.clusterId authoritative). */
const itemClusterId = (item: ReviewQueueItem): string | null => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
    case NEXT_ACTION_KIND.NAME:
    case NEXT_ACTION_KIND.CLUSTER:
      return item.clusterId;
    case NEXT_ACTION_KIND.MERGE:
      return null;
  }
};

const isEnabledFocusTarget = (el: HTMLElement | null): el is HTMLElement => {
  if (!el) {
    return false;
  }
  if (el.hasAttribute('disabled') || (el as HTMLButtonElement).disabled) {
    return false;
  }
  if (el.getAttribute('aria-disabled') === 'true') {
    return false;
  }
  return true;
};

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
  /** Controlled band filter from URL (`rq=` band enum). */
  band: ReviewQueueBandParam;
  onBandChange: (band: ReviewQueueBandParam) => void;
  /**
   * PR-31: id-keyed selection set lifted to ScanTabContent (survives panel
   * unmount). Default empty; controlled prop pair into bulk hooks.
   */
  selectedIds: ReadonlySet<string>;
  onSelectedIdsChange: (next: Set<string>) => void;
  onLabel?: (clusterId: string) => void;
  onReview?: (clusterId: string) => void;
  /** Anchor div for drain-focus (tabIndex=-1). */
  emptyStateAnchorRef?: React.RefObject<HTMLElement | null>;
  /**
   * §7 / BR-75/BR-82: reports whether the queue currently owns the viewport's single
   * accent primary — either the review card's marked primary (accept / person-commit
   * Confirm) or the bulk-commit button (BR-82) is rendered AND marked. ScanTabContent
   * uses this — NOT findings totals — to drive footer demotion, so the SAME signal
   * that places the queue's `data-acx-accent-primary` marker also demotes the footer
   * CTAs → exactly one accent primary per rendered viewport.
   */
  onCardPrimaryPresenceChange?: (present: boolean) => void;
}

/** Suggestion id for bulk-selectable queue items; null for CLUSTER (no accept POST). */
const itemSuggestionId = (item: ReviewQueueItem): string | null => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
    case NEXT_ACTION_KIND.MERGE:
    case NEXT_ACTION_KIND.NAME:
      return item.suggestionId;
    case NEXT_ACTION_KIND.CLUSTER:
      return null;
  }
};

/** Target cluster for truncation gate — merge has none; plain accepts without cluster are ungated. */
const itemTargetClusterId = (item: ReviewQueueItem): string | null => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
      return item.clusterId;
    case NEXT_ACTION_KIND.NAME:
      return item.clusterId;
    case NEXT_ACTION_KIND.MERGE:
    case NEXT_ACTION_KIND.CLUSTER:
      return null;
  }
};

const itemBulkLabel = (item: ReviewQueueItem): string | null => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
      return item.label;
    case NEXT_ACTION_KIND.NAME:
      return null;
    case NEXT_ACTION_KIND.MERGE:
    case NEXT_ACTION_KIND.CLUSTER:
      return null;
  }
};

const itemCommitKind = (item: ReviewQueueItem): SuggestionCommitKind | null => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
      return 'accept';
    case NEXT_ACTION_KIND.MERGE:
      return 'acceptMerge';
    case NEXT_ACTION_KIND.NAME:
      return 'acceptName';
    case NEXT_ACTION_KIND.CLUSTER:
      return null;
  }
};

const itemPreviewLabel = (item: ReviewQueueItem): string => {
  switch (item.kind) {
    case NEXT_ACTION_KIND.ASSIGNMENT:
      return item.label ?? __('Close match', 'alt-context');
    case NEXT_ACTION_KIND.MERGE:
      return __('Possible duplicate', 'alt-context');
    case NEXT_ACTION_KIND.NAME:
      return __('Suggested name', 'alt-context');
    case NEXT_ACTION_KIND.CLUSTER:
      return __('Unlabeled group', 'alt-context');
  }
};

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
    {
      index,
      onIndexChange,
      kind,
      onKindChange,
      band,
      onBandChange,
      selectedIds,
      onSelectedIdsChange,
      onLabel,
      onReview,
      emptyStateAnchorRef,
      onCardPrimaryPresenceChange,
    },
    ref,
  ): React.JSX.Element | null {
    const findings = useWorkbenchFindings();
    const data = useSuggestionReviewData();
    const { topUnlabeledClusters } = useSuggestionReviewQueries();
    const { resolveSurvivor } = useMergeSurvivors();
    const cardRegionRef = React.useRef<HTMLDivElement>(null);
    const [lightbox, setLightbox] = React.useState<FaceOriginalTarget | null>(null);
    // [REF-19] single AT-announce module; [A11Y-06] status second channel — BR-68/HARM-02
    // seq-keyed sink so repeat-identical strings still re-fire (plain useState Object.is bail-out).
    const { message: liveMessage, seq: liveSeq, announce: setLiveMessage } = useAriaAnnounce();
    const [selectionOpen, setSelectionOpen] = React.useState(false);
    /** User confirmed bulk while truncation-gated (UI-06 total-N confirm). */
    const [truncationConfirmed, setTruncationConfirmed] = React.useState(false);
    // REV4-02: RQ v5 isLoading stays false while an already-errored query
    // refetches; track retry locally and inspect settled isError.
    const [retrying, setRetrying] = React.useState(false);
    const [retryFailed, setRetryFailed] = React.useState(false);
    const previousItemKeyRef = React.useRef<string | null>(null);
    const pendingFocusAfterRemovalRef = React.useRef(false);

    const filter: ReviewQueueFilter = kindParamToFilter(kind);
    const activeBand: ReviewQueueBand = bandParamToBand(band);
    // KIND ∩ band (④ composition = intersection).
    const filteredQueue = React.useMemo(
      () => filterReviewQueueComposite(findings.queue, filter, activeBand),
      [findings.queue, filter, activeBand],
    );

    const queueBySuggestionId = React.useMemo(() => {
      const map = new Map<string, ReviewQueueItem>();
      for (const item of findings.queue) {
        const sid = itemSuggestionId(item);
        if (sid) {
          map.set(sid, item);
        }
      }
      return map;
    }, [findings.queue]);

    /**
     * M2: bulk preview/commit resolves only selection ∩ active filters.
     * Ids selected while unfiltered stay selected, but commit/preview ignore
     * those outside the current KIND ∩ band view.
     */
    const filteredSelectedIds = React.useMemo(
      () => intersectSelectionWithFilters(selectedIds, findings.queue, filter, activeBand),
      [selectedIds, findings.queue, filter, activeBand],
    );

    const resolveBulkItems = React.useCallback(
      (ids: readonly string[]): BulkCommitItem[] => {
        // Guard: only ids still visible under active filters (M2).
        const allowed = new Set(
          intersectSelectionWithFilters(ids, findings.queue, filter, activeBand),
        );
        const items: BulkCommitItem[] = [];
        for (const id of ids) {
          if (!allowed.has(id)) {
            continue;
          }
          const item = queueBySuggestionId.get(id);
          if (!item) {
            continue;
          }
          const commitKind = itemCommitKind(item);
          if (!commitKind) {
            continue;
          }
          items.push({
            suggestionId: id,
            commitKind,
            label: itemBulkLabel(item),
          });
        }
        return items;
      },
      [queueBySuggestionId, findings.queue, filter, activeBand],
    );

    const bulk = useBulkReviewCommit({
      selectedIds,
      onSelectedIdsChange,
      resolveItems: resolveBulkItems,
      flushHeldSingle: data.flushHeld,
      commitOne: data.commitOneNow,
      heldSingleSuggestionId: data.hold.suggestionId,
      setBulkActionActive: data.setBulkActionActive,
      onBulkSequenceSettled: () => {
        data.invalidateSuggestionQueries();
        data.invalidateMediaIdentities();
      },
      isBulkActiveRef: data.isBulkActiveRef,
      awaitBulkIdleOrFlushRef: data.awaitBulkIdleOrFlushRef,
    });

    // BR-59: the truncation gate targets only the clusters the commit can fire —
    // the filter-intersected selection, not the full selectedIds set.
    const selectedTargetClusterIds = React.useMemo(() => {
      const ids: string[] = [];
      for (const sid of filteredSelectedIds) {
        const item = queueBySuggestionId.get(sid);
        if (!item) {
          continue;
        }
        const clusterId = itemTargetClusterId(item);
        if (clusterId) {
          ids.push(clusterId);
        }
      }
      return ids;
    }, [queueBySuggestionId, filteredSelectedIds]);

    const truncation = useSelectedClusterTruncation(selectedTargetClusterIds);

    // Drop selected ids that left the projection; announce count update.
    const pruneMissingIds = bulk.pruneMissingIds;
    React.useEffect(() => {
      const present = new Set<string>();
      for (const item of findings.queue) {
        const sid = itemSuggestionId(item);
        if (sid) {
          present.add(sid);
        }
      }
      const dropped = pruneMissingIds(present);
      if (dropped > 0) {
        setLiveMessage(
          sprintf(
            /* translators: %d: number of items removed from selection */
            __('%d selected item(s) no longer available — selection updated.', 'alt-context'),
            dropped,
          ),
        );
      }
    }, [findings.queue, pruneMissingIds, setLiveMessage]);

    // BR-63: when the selection extends beyond the active KIND ∩ band view,
    // render/announce the split count; otherwise keep the simple count.
    const selectionCountMessage =
      selectedIds.size !== filteredSelectedIds.length
        ? sprintf(
            /* translators: 1: total selected review items, 2: selected items within active filters */
            __(SELECTION_SPLIT_MESSAGE, 'alt-context'),
            selectedIds.size,
            filteredSelectedIds.length,
          )
        : sprintf(
            /* translators: %d: number of selected review items */
            __('%d selected', 'alt-context'),
            selectedIds.size,
          );

    // BR-54/BR-63: announce tray count changes (select/deselect, filter split)
    // via polite live region. Ref-compare skips the mount announce.
    const prevSelectionMessageRef = React.useRef(selectionCountMessage);
    React.useEffect(() => {
      const prev = prevSelectionMessageRef.current;
      prevSelectionMessageRef.current = selectionCountMessage;
      if (prev === selectionCountMessage) {
        return;
      }
      setLiveMessage(selectionCountMessage);
    }, [selectionCountMessage, setLiveMessage]);

    // Reset truncation confirm when selection or gate changes.
    React.useEffect(() => {
      setTruncationConfirmed(false);
    }, [selectedIds, truncation.isTruncationGated]);

    const length = filteredQueue.length;
    // [COG-03] design to the goal filter — false "all caught up" when filters hide work.
    const filtersActive = filter !== REVIEW_QUEUE_FILTER.ALL || activeBand !== REVIEW_QUEUE_BAND.ALL;
    const filteredEmptyWithWork = length === 0 && filtersActive && findings.queue.length > 0;
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

    // Lightweight open-target guard on the head card's cluster (when present).
    // Announce retirement; do NOT fight projection-driven index advance (removal ≠ retirement).
    const headClusterId = currentItem ? itemClusterId(currentItem) : null;
    const { status: headLiveStatus, error: headLiveError } = useLiveReviewTarget(headClusterId, {
      resolveSurvivor: (retiredId) => resolveSurvivor(retiredId),
      onAnnounce: (message) => setLiveMessage(message),
      // Queue does not own a bound review pane — projection re-derivation advances the card.
      onRebind: undefined,
      onClose: undefined,
    });

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

    // BR-27: per-kind primary — NAME/CLUSTER prefer person-commit (combobox when confirm
    // disabled); skip disabled elements before falling back; never land on body.
    const focusPrimaryInCard = React.useCallback((): void => {
      const root = cardRegionRef.current;
      if (!root) {
        emptyStateAnchorRef?.current?.focus({ preventScroll: true });
        return;
      }

      const preferPersonCommit =
        currentItem?.kind === NEXT_ACTION_KIND.NAME ||
        currentItem?.kind === NEXT_ACTION_KIND.CLUSTER;

      const personCommitSelectors = [
        '.acx-person-commit__confirm:not([disabled])',
        '.acx-person-commit [role="combobox"]:not([disabled])',
        '.acx-person-commit button:not([disabled])',
        '.acx-person-commit a[href]',
      ] as const;
      const acceptSelectors = [
        '.acx-suggestion-card__accept:not([disabled])',
        '.acx-top-cluster-card__title-action:not([disabled])',
        '.acx-top-cluster-card__review-btn:not([disabled])',
        '.acx-button--primary:not([disabled])',
        'button.button-primary:not([disabled])',
        'button:not([disabled])',
      ] as const;

      const selectors = preferPersonCommit
        ? [...personCommitSelectors, ...acceptSelectors]
        : [...acceptSelectors, ...personCommitSelectors];

      for (const selector of selectors) {
        const candidate = root.querySelector<HTMLElement>(selector);
        if (isEnabledFocusTarget(candidate)) {
          candidate.focus({ preventScroll: true });
          return;
        }
      }
      emptyStateAnchorRef?.current?.focus({ preventScroll: true });
    }, [currentItem?.kind, emptyStateAnchorRef]);

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
        // UI-04: drain copy is for a successful empty only — projection failure
        // must announce the error, not "all caught up" (RLSE-05 / A11Y).
        // [rg-003] the outage must not silence the filtered-empty announcement:
        // when filters hide real work, AT hears both the failure and the hint
        // that an escape hatch exists, matching the visual (both are rendered).
        if (data.isTopUnlabeledError) {
          const errorCopy = __(REVIEW_QUEUE_TOP_UNLABELED_ERROR_MESSAGE, 'alt-context');
          setLiveMessage(
            filteredEmptyWithWork
              ? `${errorCopy} ${__(REVIEW_QUEUE_FILTERED_EMPTY_MESSAGE, 'alt-context')}`
              : errorCopy,
          );
        } else if (filteredEmptyWithWork) {
          // [COG-03]/[A11Y-06] AT parity with visual: filtered-empty ≠ true drain.
          setLiveMessage(__(REVIEW_QUEUE_FILTERED_EMPTY_MESSAGE, 'alt-context'));
        } else if (findings.zeroEvidenceClusterCount > 0) {
          // REV2-09: the queue is genuinely empty — keep the drain confirmation
          // and name the gated clusters that still need a resync.
          setLiveMessage(
            `${__(REVIEW_QUEUE_DRAIN_MESSAGE, 'alt-context')} ${gatedClusterCopy(
              findings.zeroEvidenceClusterCount,
              findings.topUnlabeledTruncated,
            )}`,
          );
        } else {
          setLiveMessage(__(REVIEW_QUEUE_DRAIN_MESSAGE, 'alt-context'));
        }
        if (pendingFocusAfterRemovalRef.current) {
          pendingFocusAfterRemovalRef.current = false;
          requestAnimationFrame(() => {
            emptyStateAnchorRef?.current?.focus({ preventScroll: true });
          });
        }
      }
    }, [
      currentKey,
      data.isTopUnlabeledError,
      emptyStateAnchorRef,
      filteredEmptyWithWork,
      findings.zeroEvidenceClusterCount,
      findings.topUnlabeledTruncated,
      focusPrimaryInCard,
      length,
      safeIndex,
      setLiveMessage,
    ]);

    const markAdvanceFocus = React.useCallback((): void => {
      pendingFocusAfterRemovalRef.current = true;
    }, []);

    const clearAdvanceFocus = React.useCallback((): void => {
      pendingFocusAfterRemovalRef.current = false;
    }, []);

    /**
     * BR-16: leaving a held card (prev/next/filter) flushes the hold first.
     * Advance is gated on success; failure re-surfaces on the held card.
     * Slice-5: also flush/wait bulk hold/sequence before navigating (PR-30).
     */
    const navigateAfterFlush = React.useCallback(
      (navigate: () => void): void => {
        clearAdvanceFocus();
        // BR-29: leave succeeded/failed person-commit surface when leaving the card.
        data.clearPersonCommitSuccess();

        const afterSingleFlush = (
          result: ScheduleCommitResult | null | undefined,
        ): void => {
          if (result == null || result.outcome === 'committed') {
            if (result?.outcome === 'committed') {
              setLiveMessage(__('Saved. Moving to next review item.', 'alt-context'));
            }
            navigate();
            return;
          }
          if (result.outcome === 'failed') {
            setLiveMessage(
              result.kind.startsWith('reject')
                ? __('Reject failed. Retry to try again.', 'alt-context')
                : __('Accept failed. Retry to try again.', 'alt-context'),
            );
          }
        };

        // Bulk active: flush/wait sequence first, then any single hold, then navigate.
        if (bulk.isBulkActive) {
          void bulk.awaitBulkIdleOrFlush().then(() => {
            if (data.hold.phase === COMMIT_HOLD_PHASE.HOLDING) {
              void data.flushHeld().then(afterSingleFlush);
              return;
            }
            navigate();
          });
          return;
        }

        // Original single-hold fast path (BR-16) — sync check, no bulk await.
        if (data.hold.phase !== COMMIT_HOLD_PHASE.HOLDING) {
          navigate();
          return;
        }
        void data.flushHeld().then(afterSingleFlush);
      },
      [bulk, clearAdvanceFocus, data, setLiveMessage],
    );

    // BR-52: fetch error fails closed — confirm cannot clear an error gate.
    const truncationBlocksCommit =
      selectedIds.size > 0 &&
      (truncation.isError ||
        (truncation.isTruncationGated && !truncationConfirmed && !truncation.isError));
    const truncationReason = truncation.isError
      ? __('Could not verify group sizes. Retry before accepting selected items.', 'alt-context')
      : truncation.isTruncationGated
        ? sprintf(
            /* translators: 1: total members, 2: hidden count beyond first page */
            __(
              'Selection includes groups with %1$d total faces (%2$d not shown). Expand or confirm before accepting.',
              'alt-context',
            ),
            truncation.gatedTotal,
            truncation.gatedHiddenCount,
          )
        : null;

    // M2: preview enumerates the filter-intersected selection only.
    const selectedPreviewItems = React.useMemo(() => {
      const rows: { id: string; label: string }[] = [];
      for (const id of filteredSelectedIds) {
        const item = queueBySuggestionId.get(id);
        if (!item) {
          continue;
        }
        rows.push({ id, label: itemPreviewLabel(item) });
      }
      return rows;
    }, [queueBySuggestionId, filteredSelectedIds]);

    // BR-30: when person-commit fails/succeeds after the card advanced away, surface
    // alert/status in queue chrome (card-scoped phase never mounts).
    const currentClusterId = currentItem ? itemClusterId(currentItem) : null;
    const personCommitSurfacedOnCard =
      data.personCommit.clusterId != null && data.personCommit.clusterId === currentClusterId;
    const showQueuePersonCommitFallback =
      (data.personCommit.phase === PERSON_COMMIT_PHASE.FAILED || data.personCommit.phase === PERSON_COMMIT_PHASE.SUCCEEDED) &&
      data.personCommit.clusterId != null &&
      !personCommitSurfacedOnCard;

    const handleFilterClick = (nextFilter: ReviewQueueFilter): void => {
      navigateAfterFlush(() => {
        // BR-14: KIND chips toggle — active chip returns to unfiltered/all.
        if (nextFilter === filter) {
          onKindChange(filterToKindParam(REVIEW_QUEUE_FILTER.ALL));
          onIndexChange(0);
          return;
        }
        onKindChange(filterToKindParam(nextFilter));
        onIndexChange(0);
      });
    };

    const handleBandClick = (nextBand: ReviewQueueBand): void => {
      navigateAfterFlush(() => {
        // Band chips toggle like KIND chips — active → all.
        if (nextBand === activeBand) {
          onBandChange(bandToBandParam(REVIEW_QUEUE_BAND.ALL));
          onIndexChange(0);
          return;
        }
        onBandChange(bandToBandParam(nextBand));
        onIndexChange(0);
      });
    };

    const handlePrev = (): void => {
      navigateAfterFlush(() => {
        onIndexChange(prevQueueIndex(safeIndex, length));
      });
    };

    const handleNext = (): void => {
      navigateAfterFlush(() => {
        onIndexChange(nextQueueIndex(safeIndex, length));
      });
    };

    const retrySuggestionQueries = (): void => {
      if (retrying) {
        return;
      }
      setRetrying(true);
      setRetryFailed(false);
      // REV2-08: name suggestions feed counts.names and the review queue.
      void Promise.all([
        data.refetchAssignment(),
        data.refetchMerge(),
        data.refetchName(),
        data.refetchTopUnlabeled(),
      ])
        .catch(() => undefined)
        .then((results) => {
          setRetrying(false);
          setRetryFailed(settledRefetchFailed(results));
        });
    };

    // §7 render-branch flags, hoisted above the early returns so the card-primary
    // presence signal is computed in every state (BR-75).
    const showUnavailableWarning =
      length === 0 && data.assignmentDataSource === DATA_SOURCE.UNAVAILABLE;
    const showEndpointErrorWarning =
      length === 0 && data.assignmentDataSource === DATA_SOURCE.ENDPOINT_ERROR;
    // REV6-01: retryFailed is local. A sibling findings-panel retry can
    // recover the same four queries without touching this latch. Reset
    // when the query-error boolean is false. Key on that boolean, not
    // isErrorBranch — isErrorBranch includes retryFailed and would clear
    // a genuine failure the instant it is set. Re-run when the unavailable
    // / endpoint-error mask drops so a latched retryFailed cannot leak
    // onto a recovered queue (suggestionQueriesErrored stays false on
    // the UNAVAILABLE path).
    const suggestionQueriesErrored = data.isError && findings.isError;
    React.useEffect(() => {
      if (!suggestionQueriesErrored) {
        setRetryFailed(false);
      }
    }, [suggestionQueriesErrored, showUnavailableWarning, showEndpointErrorWarning]);
    // Criterion 4: suppress head-card body once the open cluster is known retired.
    const suppressRetiredHead =
      headClusterId != null && (headLiveStatus === 'retired' || headLiveStatus === 'rebound');

    // Hide the queue only while a source is still failing-to-load without a
    // settled assignment+merge error. RQ v5 failureCount stays 1 when
    // retry:false, so a `failureCount <= 2` gate made the error Retry dead
    // (REV4-02). Once data.isError is set, show the error branch. Stay on
    // that surface while a local retry is in-flight — refetch can clear
    // query isError before it settles. REV5-02: unavailable / endpoint-error
    // EmptyStateWarning stays mounted across retry so the focused Retry is
    // not swapped for the generic error-branch control.
    const isErrorBranch =
      !showUnavailableWarning &&
      !showEndpointErrorWarning &&
      (retrying || retryFailed || (data.isError && findings.isError));
    const isInitialFailureBranch =
      data.hasInitialFailure && !data.isError && !isErrorBranch;
    const isLoadingBranch = data.isLoading || findings.isLoading;

    // The current queue item resolves to a real card (its suggestion/cluster is in
    // the by-id map) — guards the rare projection race where an item is queued but
    // its detail row is not yet loaded (CurrentCard would render a bodyless "no
    // longer available" note with no primary action).
    const currentCardResolvable = ((): boolean => {
      if (!currentItem) {
        return false;
      }
      switch (currentItem.kind) {
        case NEXT_ACTION_KIND.ASSIGNMENT:
          return assignmentById.has(currentItem.suggestionId);
        case NEXT_ACTION_KIND.MERGE:
          return mergeById.has(currentItem.suggestionId);
        case NEXT_ACTION_KIND.NAME:
          return nameById.has(currentItem.suggestionId);
        case NEXT_ACTION_KIND.CLUSTER:
          return topClustersById.has(currentItem.clusterId);
      }
    })();

    // BR-81: for NAME/CLUSTER the accent marker rides the person-commit Confirm, which
    // is replaced by a markerless success surface once the commit succeeds. CLUSTER
    // lingers in `topClustersById` until the async invalidation refetch, so across that
    // window `currentCardResolvable` stays true while NO marked primary renders —
    // presence must be false there so the footer re-owns the single accent.
    const personCommitSucceededOnCurrentCard =
      currentItem !== null &&
      isPersonCommitPrimaryKind(currentItem.kind) &&
      data.personCommit.phase === PERSON_COMMIT_PHASE.SUCCEEDED &&
      (data.personCommit.clusterId === null ||
        data.personCommit.clusterId === currentClusterId);

    // BR-75: a single accent-primary card action is on screen iff CurrentCard's real
    // branch renders its marked primary. This is the SAME condition that mounts the
    // marker, so the footer demotion it drives cannot disagree with the card marker.
    const cardPrimaryPresent =
      !isInitialFailureBranch &&
      !isLoadingBranch &&
      !isErrorBranch &&
      !showUnavailableWarning &&
      !showEndpointErrorWarning &&
      length > 0 &&
      currentItem !== null &&
      !suppressRetiredHead &&
      currentCardResolvable &&
      !personCommitSucceededOnCurrentCard;

    // BR-82: when the bulk-commit button is on screen with a committable, non-ambiguous
    // selection it is the viewport's single accent primary (the user is committing the
    // selection); the per-card primary steps down to neutral. While the selection is
    // truncation-ambiguous the bulk commit is never the accent (COL-03 / UI-06 §7.7),
    // so the card keeps it. Guarded so exactly one element carries the accent.
    const bulkCommitOwnsAccent =
      selectionOpen && filteredSelectedIds.length > 0 && !truncationBlocksCommit;

    // The queue owns the viewport's single accent primary when either the card marker
    // renders or the bulk commit does — this is what drives footer demotion.
    const queueOwnsAccentPrimary = cardPrimaryPresent || bulkCommitOwnsAccent;

    // BR-80: report presence in a layout effect (fires before paint) so the footer
    // demotion and the card/bulk marker commit in the SAME visual frame — no transient
    // frame of two accents (card + still-primary footer) on entry, nor zero on drain.
    React.useLayoutEffect(() => {
      onCardPrimaryPresenceChange?.(queueOwnsAccentPrimary);
    }, [queueOwnsAccentPrimary, onCardPrimaryPresenceChange]);
    // Report absence on unmount (e.g. a panel replaces the queue) so a stale "present"
    // never lingers in the parent's footer-demotion state. Layout-effect cleanup runs
    // before paint so the footer re-owns the accent in the same frame the panel mounts.
    React.useLayoutEffect(
      () => () => {
        onCardPrimaryPresenceChange?.(false);
      },
      [onCardPrimaryPresenceChange],
    );

    if (isErrorBranch) {
      return (
        <div className="acx-review-queue acx-review-queue--error">
          <div role="status" aria-live="polite">
            <p id="acx-review-queue-error" className="acx-review-queue__status">
              {retrying ? null : (
                <>
                  <AlertTriangle aria-hidden="true" className="acx-review-queue__status-icon" size={16} />
                  {retryFailed
                    ? __(QUERY_RETRY_COPY.RETRY_FAILED_SUGGESTIONS, 'alt-context')
                    : __(QUERY_RETRY_COPY.LOAD_FAILED_SUGGESTIONS, 'alt-context')}
                </>
              )}
            </p>
          </div>
          <QueryRetryButton
            describedBy="acx-review-queue-error"
            retrying={retrying}
            retryingLabel={__(QUERY_RETRY_COPY.RETRYING_SUGGESTIONS, 'alt-context')}
            statusId="acx-review-queue-retrying"
            statusClassName="acx-review-queue__status"
            onClick={retrySuggestionQueries}
            className="button"
          />
        </div>
      );
    }

    if (isInitialFailureBranch) {
      return null;
    }

    if (isLoadingBranch) {
      return (
        <div className="acx-review-queue acx-review-queue--loading" role="status" aria-live="polite">
          <p>{__('Loading review queue…', 'alt-context')}</p>
        </div>
      );
    }

    return (
      <div className="acx-review-queue" data-live-target-status={headLiveStatus}>
        {headLiveStatus === 'auth_expired' ? (
          <UserFacingErrorNotice
            className="acx-review-queue__auth-expired"
            error={headLiveError}
            fallback={__('Unable to verify this review target.', 'alt-context')}
          />
        ) : null}
        <header className="acx-review-queue__header">
          <h3 id="acx-workbench-queue-heading" className="acx-review-queue__title">
            {__('Review Suggestions', 'alt-context')}
          </h3>
          {length > 0 ? (
            <span className="acx-review-queue__count" aria-hidden="true">
              {sprintf(
                filtersActive
                  ? _n(REVIEW_QUEUE_COUNT_FILTERED, REVIEW_QUEUE_COUNT_FILTERED, length, 'alt-context')
                  : _n(REVIEW_QUEUE_COUNT_PAGE, REVIEW_QUEUE_COUNT_PAGE, length, 'alt-context'),
                length,
              )}
            </span>
          ) : null}
        </header>

        <div className="acx-review-queue__chrome">
          <div className="acx-review-queue__chip-groups">
            <div
              className="acx-review-queue__chips"
              role="group"
              aria-label={__('Filter review queue', 'alt-context')}
            >
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
            {/* ④ band chips — second group; pure similarity predicate (post-eligibility). */}
            <div
              className="acx-review-queue__chips acx-review-queue__chips--band"
              role="group"
              aria-label={__('Filter by match strength', 'alt-context')}
            >
              <button
                type="button"
                className={`acx-review-queue__chip${activeBand === REVIEW_QUEUE_BAND.STRONG ? ' is-active' : ''}`}
                aria-pressed={activeBand === REVIEW_QUEUE_BAND.STRONG}
                onClick={() => handleBandClick(REVIEW_QUEUE_BAND.STRONG)}
              >
                {REVIEW_QUEUE_BAND_CHIP_LABEL[REVIEW_QUEUE_BAND.STRONG]}
              </button>
              <button
                type="button"
                className={`acx-review-queue__chip${activeBand === REVIEW_QUEUE_BAND.WEAKER ? ' is-active' : ''}`}
                aria-pressed={activeBand === REVIEW_QUEUE_BAND.WEAKER}
                onClick={() => handleBandClick(REVIEW_QUEUE_BAND.WEAKER)}
              >
                {REVIEW_QUEUE_BAND_CHIP_LABEL[REVIEW_QUEUE_BAND.WEAKER]}
              </button>
            </div>
          </div>

          <div className="acx-review-queue__nav">
            <span className="acx-review-queue__position" aria-live="polite">
              {length === 0
                ? data.isTopUnlabeledError
                  ? // [A11Y] a bare em dash announces as punctuation and loses the
                    // position entirely; state the unmeasurable count explicitly.
                    __(REVIEW_QUEUE_POSITION_UNAVAILABLE_MESSAGE, 'alt-context')
                  : __('0 of 0', 'alt-context')
                : sprintf(
                    /* translators: 1: current 1-based position, 2: loaded count on this page or in the active filter */
                    __(
                      filtersActive ? REVIEW_QUEUE_POSITION_FILTERED : REVIEW_QUEUE_POSITION_PAGE,
                      'alt-context',
                    ),
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

          {/* G3 selection tray — chrome, not a review card (PA-14 one-card invariant). */}
          <div
            className="acx-review-queue__selection-tray"
            data-testid="acx-review-selection-tray"
          >
            <span className="acx-review-queue__selection-count">
              {selectionCountMessage}
            </span>
            <button
              type="button"
              className="acx-review-queue__selection-review"
              disabled={selectedIds.size === 0}
              aria-expanded={selectionOpen}
              onClick={() => setSelectionOpen((open) => !open)}
            >
              {__('Review selection', 'alt-context')}
            </button>
          </div>
        </div>

        {selectionOpen && selectedIds.size > 0 ? (
          <div
            className="acx-review-queue__selection-panel"
            data-testid="acx-review-selection-panel"
          >
            <ul className="acx-review-queue__selection-preview">
              {selectedPreviewItems.map((row) => (
                <li key={row.id} className="acx-review-queue__selection-preview-row">
                  <span className="acx-review-queue__selection-preview-label">{row.label}</span>
                </li>
              ))}
            </ul>

            {truncationReason ? (
              <p className="acx-review-queue__truncation-reason" role="status">
                {truncationReason}
              </p>
            ) : null}

            {truncation.isError ? (
              <button
                type="button"
                className="button acx-review-queue__truncation-retry"
                data-testid="acx-truncation-retry"
                onClick={() => truncation.refetch()}
              >
                {__('Retry', 'alt-context')}
              </button>
            ) : null}

            {truncationBlocksCommit && !truncation.isError ? (
              <button
                type="button"
                className="button acx-review-queue__truncation-confirm"
                onClick={() => setTruncationConfirmed(true)}
              >
                {sprintf(
                  /* translators: 1: total members across gated clusters, 2: hidden count */
                  __('Confirm %1$d total (%2$d not shown)', 'alt-context'),
                  truncation.gatedTotal,
                  truncation.gatedHiddenCount,
                )}
              </button>
            ) : null}

            <button
              type="button"
              // BR-82: the bulk commit carries the accent chrome + single-primary marker
              // only when it owns the accent (committable, non-ambiguous selection);
              // otherwise it renders neutral so it is never a second chromatic primary.
              className={
                bulkCommitOwnsAccent
                  ? 'button button-primary acx-review-queue__bulk-commit acx-accent-primary-action'
                  : 'button acx-review-queue__bulk-commit'
              }
              data-testid="acx-bulk-commit"
              disabled={
                filteredSelectedIds.length === 0 ||
                bulk.isBulkActive ||
                bulk.bulkInitiatePending ||
                truncationBlocksCommit ||
                truncation.isLoading
              }
              title={truncationBlocksCommit ? (truncationReason ?? undefined) : undefined}
              {...(bulkCommitOwnsAccent ? { [ACCENT_PRIMARY_ATTR]: true } : {})}
              onClick={() => {
                void bulk.initiateBulk();
              }}
            >
              {bulk.commitLabelForSelection}
            </button>
          </div>
        ) : null}

        {bulk.bulk.phase === BULK_COMMIT_PHASE.HOLDING || bulk.bulk.phase === BULK_COMMIT_PHASE.COMMITTING ? (
          <div
            className="acx-review-queue__hold acx-review-queue__bulk-hold"
            role="status"
            aria-live="polite"
            data-testid="acx-bulk-hold"
            onFocusCapture={() => bulk.setBulkHoldPaused(true)}
            onBlurCapture={(event) => {
              const related = event.relatedTarget;
              if (!(related instanceof Node) || !event.currentTarget.contains(related)) {
                bulk.setBulkHoldPaused(false);
              }
            }}
            onPointerEnter={() => bulk.setBulkHoldPaused(true)}
            onPointerLeave={() => bulk.setBulkHoldPaused(false)}
          >
            <span className="acx-review-queue__hold-message">{bulk.bulkHoldAnnounce}</span>
            {bulk.bulk.phase === BULK_COMMIT_PHASE.HOLDING ? (
              <button
                type="button"
                className="button acx-review-queue__undo"
                onClick={() => bulk.undoBulk()}
              >
                {__('Undo', 'alt-context')}
              </button>
            ) : null}
          </div>
        ) : null}

        {bulk.bulk.phase === BULK_COMMIT_PHASE.PARTIAL_FAILED && bulk.bulk.partialFailure ? (
          <div
            className="acx-review-queue__failure acx-review-queue__bulk-failure"
            role="alert"
            data-testid="acx-bulk-partial-failure"
          >
            <p className="acx-review-queue__failure-message">{bulk.bulk.partialFailure.message}</p>
            <button
              type="button"
              className="button acx-review-queue__retry"
              onClick={() => {
                void bulk.retryBulk();
              }}
            >
              {__('Retry', 'alt-context')}
            </button>
          </div>
        ) : null}

        <div
          key={liveSeq}
          className="acx-review-queue__live"
          role="status"
          aria-live="polite"
          data-announce-seq={liveSeq}
        >
          {liveMessage}
        </div>

        {showQueuePersonCommitFallback && data.personCommit.phase === PERSON_COMMIT_PHASE.FAILED ? (
          <div
            className="acx-review-queue__person-commit-fallback acx-person-commit__failure"
            role="alert"
            data-testid="acx-person-commit-queue-fallback"
          >
            <p className="acx-person-commit__failure-message">
              {data.personCommit.errorMessage ?? __(PERSON_COMMIT_FAILURE_COPY, 'alt-context')}
            </p>
            <button
              type="button"
              className="button acx-person-commit__retry"
              onClick={() => {
                void data.retryPersonCommit();
              }}
              disabled={data.personCommitPending}
            >
              {__('Retry', 'alt-context')}
            </button>
          </div>
        ) : null}
        {showQueuePersonCommitFallback && data.personCommit.phase === PERSON_COMMIT_PHASE.SUCCEEDED ? (
          <div
            className="acx-review-queue__person-commit-fallback acx-person-commit--success"
            role="status"
            data-testid="acx-person-commit-queue-fallback"
          >
            <p className="acx-person-commit__success-message">
              {__(PERSON_COMMIT_SUCCESS_COPY, 'alt-context')}
            </p>
            <a className="acx-person-commit__roster-link" href={VIEW_IN_ROSTER_HREF}>
              {__(VIEW_IN_ROSTER_COPY, 'alt-context')}
            </a>
          </div>
        ) : null}

        <div ref={cardRegionRef} className="acx-review-queue__card-region">
          {showUnavailableWarning ? (
            <EmptyStateWarning
              title={__('Suggestion service not configured', 'alt-context')}
              message={__(
                'Check the recognition service connection, then retry loading suggestions.',
                'alt-context',
              )}
              onRetry={retrySuggestionQueries}
              retrying={retrying}
            />
          ) : showEndpointErrorWarning ? (
            <EmptyStateWarning
              title={__('Suggestion service error', 'alt-context')}
              message={__(
                'The recognition service responded with an error. Retry now or check the service logs.',
                'alt-context',
              )}
              onRetry={retrySuggestionQueries}
              retrying={retrying}
            />
          ) : length === 0 || !currentItem ? (
            // [rg-003] the outage and the Clear-filters escape hatch coexist: a
            // top-unlabeled 500 must never remove a primary control that reaches
            // real pending work. Only the true-drain copy is suppressed by it.
            <>
              {data.isTopUnlabeledError ? (
                // RLSE-05: top-unlabeled 500 must not read as an empty/caught-up queue.
                <div
                  className="acx-review-queue__error"
                  role="alert"
                  data-testid="acx-review-queue-top-unlabeled-error"
                >
                  <p>{__(REVIEW_QUEUE_TOP_UNLABELED_ERROR_MESSAGE, 'alt-context')}</p>
                  <button
                    type="button"
                    className="button"
                    onClick={() => void data.refetchTopUnlabeled()}
                  >
                    {__('Retry', 'alt-context')}
                  </button>
                </div>
              ) : null}
              {filteredEmptyWithWork ? (
                // [COG-03] filters hide work; [NAV-07] escape hatch; [INT-06] clear label; [rg-003]
                <div className="acx-review-queue__empty">
                  <p>{__(REVIEW_QUEUE_FILTERED_EMPTY_MESSAGE, 'alt-context')}</p>
                  <button
                    type="button"
                    className="button"
                    onClick={() => {
                      onKindChange(filterToKindParam(REVIEW_QUEUE_FILTER.ALL));
                      onBandChange(bandToBandParam(REVIEW_QUEUE_BAND.ALL));
                    }}
                  >
                    {__('Clear filters', 'alt-context')}
                  </button>
                </div>
              ) : data.isTopUnlabeledError ? null : (
                <>
                  <p className="acx-review-queue__empty">
                    {__(REVIEW_QUEUE_DRAIN_MESSAGE, 'alt-context')}
                  </p>
                  {findings.zeroEvidenceClusterCount > 0 ? (
                    <div className="acx-review-queue__repair" data-testid="acx-review-queue-repair">
                      <p id="acx-review-queue-repair-copy">
                        <AlertTriangle aria-hidden="true" size={16} />
                        {gatedClusterCopy(
                          findings.zeroEvidenceClusterCount,
                          findings.topUnlabeledTruncated,
                        )}
                      </p>
                      <button
                        type="button"
                        className="button"
                        onClick={() => void data.refetchTopUnlabeled()}
                        aria-describedby="acx-review-queue-repair-copy"
                      >
                        {__('Resync', 'alt-context')}
                      </button>
                    </div>
                  ) : null}
                </>
              )}
            </>
          ) : suppressRetiredHead ? (
            <p className="acx-review-queue__retired" data-testid="acx-review-queue-retired-head">
              {liveMessage ?? __('This review target is no longer available.', 'alt-context')}
            </p>
          ) : (
            <>
              {data.isTopUnlabeledError &&
              !(
                currentItem.kind === NEXT_ACTION_KIND.CLUSTER &&
                !topClustersById.has(currentItem.clusterId)
              ) ? (
                <div
                  className="acx-review-queue__error"
                  role="alert"
                  data-testid="acx-review-queue-top-unlabeled-error"
                >
                  <p>{__(REVIEW_QUEUE_TOP_UNLABELED_ERROR_MESSAGE, 'alt-context')}</p>
                  <button
                    type="button"
                    className="button"
                    onClick={() => void data.refetchTopUnlabeled()}
                  >
                    {__('Retry', 'alt-context')}
                  </button>
                </div>
              ) : null}
            <CurrentCard
              item={currentItem}
              // BR-82: the card primary steps down to neutral while the bulk commit owns
              // the accent, so exactly one element carries the accent per viewport.
              accentPrimary={!bulkCommitOwnsAccent}
              // BR-35: same 1-based numbers as the visible position span; omit when the
              // REVIEW_QUEUE_POSITION_UNAVAILABLE outage path makes count unmeasurable
              // (length===0 — CurrentCard is not mounted then, but keep the gate explicit).
              queuePosition={length > 0 ? safeIndex + 1 : undefined}
              queueTotal={length > 0 ? length : undefined}
              assignmentById={assignmentById}
              mergeById={mergeById}
              nameById={nameById}
              topClustersById={topClustersById}
              isTopUnlabeledError={data.isTopUnlabeledError}
              onRetryTopUnlabeled={() => void data.refetchTopUnlabeled()}
              isCardPending={(suggestionId, kinds) =>
                // BR-47: selected cards cannot open a single hold (bulk exclusion).
                data.isCardPending(suggestionId, kinds) ||
                bulk.isBulkActive ||
                bulk.isIdInBulkSelection(suggestionId)
              }
              cardActionsDisabledReason={
                itemSuggestionId(currentItem) &&
                bulk.isIdInBulkSelection(itemSuggestionId(currentItem)!)
                  ? __(
                      'Deselect this item to accept or reject it individually.',
                      'alt-context',
                    )
                  : bulk.isBulkActive
                    ? __('Bulk accept in progress.', 'alt-context')
                    : null
              }
              hold={data.hold}
              retryPending={data.retryPending}
              personCommit={data.personCommit}
              personCommitPending={data.personCommitPending}
              isBulkActive={bulk.isBulkActive || bulk.bulkInitiatePending}
              onReview={onReview}
              onLabel={onLabel}
              onOpenOriginal={(target) => setLightbox(target)}
              markAdvanceFocus={markAdvanceFocus}
              clearAdvanceFocus={clearAdvanceFocus}
              announce={setLiveMessage}
              scheduleAccept={data.scheduleAccept}
              scheduleReject={data.scheduleReject}
              scheduleAcceptMerge={data.scheduleAcceptMerge}
              scheduleRejectMerge={data.scheduleRejectMerge}
              scheduleAcceptName={data.scheduleAcceptName}
              scheduleRejectName={data.scheduleRejectName}
              schedulePersonCommit={data.schedulePersonCommit}
              retryPersonCommit={data.retryPersonCommit}
              undoHold={data.undoHold}
              retryFailure={data.retryFailure}
              setHoldPaused={data.setHoldPaused}
              isSelected={
                itemSuggestionId(currentItem)
                  ? bulk.isIdSelected(itemSuggestionId(currentItem)!)
                  : false
              }
              isSelectDisabled={
                !itemSuggestionId(currentItem) ||
                !bulk.isIdSelectable(itemSuggestionId(currentItem)!)
              }
              onToggleSelect={
                itemSuggestionId(currentItem)
                  ? () => bulk.toggleSelect(itemSuggestionId(currentItem)!)
                  : undefined
              }
            />
            </>
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
  /**
   * §7: when true, this mounted card's single per-kind primary (accept for
   * ASSIGNMENT/MERGE, person-commit Confirm for NAME/CLUSTER) carries the
   * `data-acx-accent-primary` marker + accent chrome. BR-82: false while the
   * bulk-commit button owns the accent, so the card steps down to neutral and
   * exactly one element carries the accent per viewport.
   */
  accentPrimary: boolean;
  /**
   * BR-35: 1-based queue position from the same state as the visible
   * `%1$d of %2$d` chrome. Omit (with `queueTotal`) when position is unavailable.
   */
  queuePosition?: number;
  /** BR-35: filtered queue length paired with `queuePosition`. */
  queueTotal?: number;
  assignmentById: Map<string, ReviewSuggestion>;
  mergeById: Map<string, PendingMergeSuggestion>;
  nameById: Map<string, PendingNameSuggestion>;
  topClustersById: Map<string, TopUnlabeledCluster>;
  /** Projection outage on top-unlabeled — distinct from retired-cluster empty. */
  isTopUnlabeledError: boolean;
  onRetryTopUnlabeled: () => void;
  isCardPending: (suggestionId: string, kinds: readonly SuggestionCommitKind[]) => boolean;
  /** BR-47: title/reason when Accept/Reject disabled due to selection or bulk. */
  cardActionsDisabledReason: string | null;
  hold: ReturnType<typeof useSuggestionReviewData>['hold'];
  retryPending: boolean;
  personCommit: PersonCommitState;
  personCommitPending: boolean;
  /** BR-48: disable person-commit while bulk hold/sequence is active. */
  isBulkActive: boolean;
  onReview?: (clusterId: string) => void;
  onLabel?: (clusterId: string) => void;
  onOpenOriginal: (target: FaceOriginalTarget) => void;
  markAdvanceFocus: () => void;
  clearAdvanceFocus: () => void;
  /** C-05: live-region announce for a refused action (single failed-slot occupied). */
  announce: (message: string) => void;
  scheduleAccept: (suggestionId: string) => Promise<ScheduleCommitResult>;
  scheduleReject: (suggestionId: string) => Promise<ScheduleCommitResult>;
  scheduleAcceptMerge: (suggestionId: string) => Promise<ScheduleCommitResult>;
  scheduleRejectMerge: (suggestionId: string) => Promise<ScheduleCommitResult>;
  scheduleAcceptName: (suggestionId: string) => Promise<ScheduleCommitResult>;
  scheduleRejectName: (suggestionId: string) => Promise<ScheduleCommitResult>;
  schedulePersonCommit: (request: PersonCommitRequest) => Promise<PersonCommitResult>;
  retryPersonCommit: () => Promise<PersonCommitResult> | null;
  undoHold: () => void;
  retryFailure: () => Promise<ScheduleCommitResult> | null;
  setHoldPaused: (paused: boolean) => void;
  isSelected: boolean;
  isSelectDisabled: boolean;
  onToggleSelect?: () => void;
}

/** Per-card Select affordance (PA-14) — accumulates into the lifted selection set. */
const SelectToggle = ({
  selected,
  disabled,
  onToggle,
}: {
  selected: boolean;
  disabled: boolean;
  onToggle?: () => void;
}): React.JSX.Element | null => {
  if (!onToggle) {
    return null;
  }
  return (
    <button
      type="button"
      className={`acx-review-queue__select${selected ? ' is-selected' : ''}`}
      data-testid="acx-review-select"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onToggle}
    >
      {selected ? __('Selected', 'alt-context') : __('Select', 'alt-context')}
    </button>
  );
};

const holdMatchesCard = (
  hold: CurrentCardProps['hold'],
  kinds: readonly SuggestionCommitKind[],
  suggestionId: string,
): boolean =>
  hold.suggestionId === suggestionId && hold.kind !== null && kinds.includes(hold.kind);

/** Hold region: status announce + Undo; countdown pauses on focus/hover (A11Y-16). */
export const CommitHoldRegion = ({
  phase,
  errorMessage,
  onUndo,
  onRetry,
  onPausedChange,
  retryPending = false,
}: {
  phase: Exclude<CommitHoldPhase, typeof COMMIT_HOLD_PHASE.IDLE>;
  errorMessage: string | null;
  onUndo: () => void;
  onRetry: () => void;
  onPausedChange: (paused: boolean) => void;
  retryPending?: boolean;
}): React.JSX.Element => {
  if (phase === COMMIT_HOLD_PHASE.FAILED) {
    return (
      <div className="acx-review-queue__failure" role="alert">
        <p className="acx-review-queue__failure-message">
          {errorMessage ?? __('Save failed. Retry to try again.', 'alt-context')}
        </p>
        <button
          type="button"
          className="button acx-review-queue__retry"
          onClick={onRetry}
          disabled={retryPending}
        >
          {__('Retry', 'alt-context')}
        </button>
      </div>
    );
  }

  const holdMessage =
    phase === COMMIT_HOLD_PHASE.COMMITTING ? HOLD_COMMITTING_STATUS_COPY : HOLD_STATUS_COPY;

  return (
    <div
      className="acx-review-queue__hold"
      role="status"
      aria-live="polite"
      onFocusCapture={() => onPausedChange(true)}
      onBlurCapture={(event) => {
        const related = event.relatedTarget;
        if (!(related instanceof Node) || !event.currentTarget.contains(related)) {
          onPausedChange(false);
        }
      }}
      onPointerEnter={() => onPausedChange(true)}
      onPointerLeave={() => onPausedChange(false)}
    >
      <span className="acx-review-queue__hold-message">{__(holdMessage, 'alt-context')}</span>
      {phase === COMMIT_HOLD_PHASE.HOLDING ? (
        <button type="button" className="button acx-review-queue__undo" onClick={onUndo}>
          {__('Undo', 'alt-context')}
        </button>
      ) : null}
    </div>
  );
};

const CurrentCard = ({
  item,
  accentPrimary,
  queuePosition,
  queueTotal,
  assignmentById,
  mergeById,
  nameById,
  topClustersById,
  isTopUnlabeledError,
  onRetryTopUnlabeled,
  isCardPending,
  cardActionsDisabledReason,
  hold,
  retryPending,
  personCommit,
  personCommitPending,
  isBulkActive,
  onReview,
  onLabel,
  onOpenOriginal,
  markAdvanceFocus,
  clearAdvanceFocus,
  announce,
  scheduleAccept,
  scheduleReject,
  scheduleAcceptMerge,
  scheduleRejectMerge,
  scheduleAcceptName,
  scheduleRejectName,
  schedulePersonCommit,
  retryPersonCommit,
  undoHold,
  retryFailure,
  setHoldPaused,
  isSelected,
  isSelectDisabled,
  onToggleSelect,
}: CurrentCardProps): React.JSX.Element | null => {
  // Arm focus before the POST so removal→key-change can place it; clear on
  // undo/failure (BR-13) so a later key change does not surprise-focus.
  const runScheduled = (schedule: () => Promise<ScheduleCommitResult>): void => {
    markAdvanceFocus();
    void schedule().then((result) => {
      if (result.outcome !== 'committed') {
        clearAdvanceFocus();
      }
      // C-05: the single failed-item slot refused this action because another item's
      // save is still failed. Announce it instead of a silent no-op (the click would
      // otherwise look dead and invite a retry/double-click).
      if (result.outcome === 'not_attempted_prior_failed') {
        announce(__('Retry the item that failed to save before reviewing another.', 'alt-context'));
      }
    });
  };

  const holdRegionFor = (kinds: readonly SuggestionCommitKind[], suggestionId: string) => {
    if (!holdMatchesCard(hold, kinds, suggestionId)) {
      return null;
    }
    if (hold.phase === COMMIT_HOLD_PHASE.IDLE) {
      return null;
    }
    return (
      <CommitHoldRegion
        phase={
          hold.phase === COMMIT_HOLD_PHASE.FAILED
            ? COMMIT_HOLD_PHASE.FAILED
            : hold.phase === COMMIT_HOLD_PHASE.COMMITTING
              ? COMMIT_HOLD_PHASE.COMMITTING
              : COMMIT_HOLD_PHASE.HOLDING
        }
        errorMessage={hold.errorMessage}
        onUndo={undoHold}
        onRetry={() => {
          void retryFailure()?.then((result) => {
            if (result.outcome === 'committed') {
              markAdvanceFocus();
            } else {
              clearAdvanceFocus();
            }
          });
        }}
        onPausedChange={setHoldPaused}
        retryPending={retryPending}
      />
    );
  };

  const personCommitFor = (
    clusterId: string | null | undefined,
    kind: ReviewQueueItem['kind'],
    options?: { suggestedCreateName?: string | null },
  ): React.ReactNode => {
    if (!shouldShowPersonCommit(kind, clusterId) || !clusterId) {
      return null;
    }
    // Only surface phase UI for this card's cluster (or idle — show chrome).
    const phaseForCard =
      personCommit.clusterId === null || personCommit.clusterId === clusterId
        ? personCommit.phase
        : PERSON_COMMIT_PHASE.IDLE;
    const errorForCard =
      personCommit.clusterId === clusterId ? personCommit.errorMessage : null;
    const isPrimary = isPersonCommitPrimaryKind(kind);
    return (
      <PersonCommitControl
        clusterId={clusterId}
        isPrimary={isPrimary}
        // §7: person-commit confirm is the accent primary only when it is the card's
        // primary kind (NAME/CLUSTER) — never doubled with an accept button.
        accentPrimary={accentPrimary && isPrimary}
        phase={phaseForCard}
        errorMessage={errorForCard}
        // Stay interactive during accept hold — schedulePersonCommit flushes first.
        // BR-25: disable on schedule (personCommitPending), not only phase==='committing'.
        // BR-48: disable while bulk hold/sequence is active (ordering via awaitBulk).
        disabled={
          personCommit.phase === PERSON_COMMIT_PHASE.COMMITTING || personCommitPending || isBulkActive
        }
        suggestedCreateName={options?.suggestedCreateName}
        onCommit={(request) => {
          // BR-27: person-commit success may remove the NAME card — arm advance focus.
          void schedulePersonCommit(request).then((result) => {
            if (result.outcome === 'committed') {
              markAdvanceFocus();
            } else if (result.outcome === 'not_attempted_prior_failed') {
              // C-05: refused because an accept/reject failure is unresolved.
              announce(__('Retry the item that failed to save before assigning a person.', 'alt-context'));
            }
          });
        }}
        onRetry={() => {
          void retryPersonCommit()?.then((result) => {
            if (result?.outcome === 'committed') {
              markAdvanceFocus();
            }
          });
        }}
        onJustLabel={onLabel}
      />
    );
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
      const assignmentKinds = ['accept', 'reject'] as const;
      const assignmentHold = holdRegionFor(assignmentKinds, suggestion.suggestionId);
      // BR-34: item.clusterId authoritative — no suggestion.clusterId fallback (null-hide matrix).
      return (
        <>
          {runHint ? <p className="acx-review-queue__run-hint">{runHint}</p> : null}
          <SelectToggle
            selected={isSelected}
            disabled={isSelectDisabled}
            onToggle={onToggleSelect}
          />
          <SuggestionCard
            suggestion={suggestion}
            accentPrimary={accentPrimary}
            // BR-41: pass ordinal only when both are defined (position chrome available).
            queuePosition={queuePosition}
            queueTotal={queueTotal}
            lowConfidenceThreshold={LOW_CONFIDENCE_THRESHOLD}
            onAccept={() => {
              runScheduled(() => scheduleAccept(suggestion.suggestionId));
            }}
            onReject={() => {
              runScheduled(() => scheduleReject(suggestion.suggestionId));
            }}
            onReview={(clusterId) => {
              if (onReview && clusterId) {
                onReview(clusterId);
              }
            }}
            onOpenOriginal={onOpenOriginal}
            isPending={isCardPending(suggestion.suggestionId, assignmentKinds)}
            disabledReason={cardActionsDisabledReason}
            actionAccessory={assignmentHold}
            actionAccessoryAfter={hold.kind === 'reject' ? 'reject' : 'accept'}
          />
          {personCommitFor(item.clusterId, NEXT_ACTION_KIND.ASSIGNMENT)}
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
      const mergeKinds = ['acceptMerge', 'rejectMerge'] as const;
      const mergeHold = holdRegionFor(mergeKinds, suggestion.id);
      return (
        <>
          <SelectToggle
            selected={isSelected}
            disabled={isSelectDisabled}
            onToggle={onToggleSelect}
          />
          <MergeSuggestionCard
            suggestion={suggestion}
            accentPrimary={accentPrimary}
            // BR-35: pass ordinal only when both are defined (position chrome available).
            queuePosition={queuePosition}
            queueTotal={queueTotal}
            onAccept={() => {
              runScheduled(() => scheduleAcceptMerge(suggestion.id));
            }}
            onReject={() => {
              runScheduled(() => scheduleRejectMerge(suggestion.id));
            }}
            onOpenOriginal={onOpenOriginal}
            isPending={isCardPending(suggestion.id, mergeKinds)}
            disabledReason={cardActionsDisabledReason}
            actionAccessory={mergeHold}
            actionAccessoryAfter={hold.kind === 'acceptMerge' ? 'accept' : 'reject'}
          />
          {/* MERGE: never person-commit (matrix). */}
        </>
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
      const nameKinds = ['acceptName', 'rejectName'] as const;
      const nameHold = holdRegionFor(nameKinds, suggestion.id);
      const afterAccept = hold.kind === 'acceptName' || hold.kind === null;
      // BR-29 belt: disable accept/reject while person-commit succeeded for this cluster.
      const namePersonCommitDone =
        personCommit.phase === PERSON_COMMIT_PHASE.SUCCEEDED && personCommit.clusterId === item.clusterId;
      const namePending =
        isCardPending(suggestion.id, nameKinds) || namePersonCommitDone || personCommitPending;
      return (
        <ReviewCardGroupShell
          kind="name"
          labelId={`acx-name-pos-${suggestion.id}`}
          // BR-41: pass ordinal only when both are defined (position chrome available).
          queuePosition={queuePosition}
          queueTotal={queueTotal}
          className="acx-suggestion-card acx-name-suggestion-card"
          data-testid="acx-review-card"
          data-review-kind="name"
        >
          <SelectToggle
            selected={isSelected}
            disabled={isSelectDisabled}
            onToggle={onToggleSelect}
          />
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
          {personCommitFor(item.clusterId, NEXT_ACTION_KIND.NAME, {
            suggestedCreateName: suggestion.suggested_name,
          })}
          <div className="acx-name-suggestion-card__actions acx-suggestion-card__actions">
            <button
              type="button"
              className="button acx-suggestion-card__accept"
              disabled={namePending}
              title={namePending && cardActionsDisabledReason ? cardActionsDisabledReason : undefined}
              onClick={() => {
                runScheduled(() => scheduleAcceptName(suggestion.id));
              }}
            >
              {__('Accept suggestion', 'alt-context')}
            </button>
            {afterAccept ? nameHold : null}
            <button
              type="button"
              className="button acx-suggestion-card__reject"
              disabled={namePending}
              title={namePending && cardActionsDisabledReason ? cardActionsDisabledReason : undefined}
              onClick={() => {
                runScheduled(() => scheduleRejectName(suggestion.id));
              }}
            >
              {__('Reject', 'alt-context')}
            </button>
            {!afterAccept ? nameHold : null}
          </div>
        </ReviewCardGroupShell>
      );
    }
    case NEXT_ACTION_KIND.CLUSTER: {
      const cluster = topClustersById.get(item.clusterId);
      if (!cluster) {
        // RLSE-05: projection 500 must not read as "cluster retired".
        if (isTopUnlabeledError) {
          return (
            <div
              className="acx-review-queue__error"
              role="alert"
              data-testid="acx-review-queue-top-unlabeled-error"
            >
              <p>{__(REVIEW_QUEUE_TOP_UNLABELED_ERROR_MESSAGE, 'alt-context')}</p>
              <button type="button" className="button" onClick={onRetryTopUnlabeled}>
                {__('Retry', 'alt-context')}
              </button>
            </div>
          );
        }
        return (
          <p className="acx-review-queue__empty">{__('This cluster is no longer available.', 'alt-context')}</p>
        );
      }
      return (
        <>
          {/* isReadOnly: person-commit is primary; label demoted to tertiary below. */}
          <TopClusterCard
            cluster={cluster}
            onLabel={() => undefined}
            isReadOnly
            onReview={onReview}
            // BR-41: pass ordinal only when both are defined (position chrome available).
            queuePosition={queuePosition}
            queueTotal={queueTotal}
          />
          {personCommitFor(item.clusterId, NEXT_ACTION_KIND.CLUSTER, {
            suggestedCreateName: cluster.suggested_label,
          })}
        </>
      );
    }
    default:
      return null;
  }
};
