/**
 * Typed view model for the Workbench live findings panel (E15-23).
 *
 * Combines assignment, merge, and name suggestions plus top unlabeled
 * clusters into one summary with a deterministic primary next action.
 * E21-5 Slice 1a: nextAction is the head of the ordered review queue.
 */

import { DATA_SOURCE, type DataSource } from '../../../api/recognition/types/dataSource';
import type { PendingMergeSuggestion, PendingNameSuggestion } from '../../../api/recognition/types';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';
import type { BoundingBox } from '../../../api/recognition/types/identity';
import { isCroppableBbox } from '../../../../components/ui/faceGeometry';
import { isDedicatedFaceThumbUrl } from '../../../../components/ui/isDedicatedFaceThumbUrl';
import type { SuggestionReviewItem } from './SuggestionCards';
import {
  buildReviewQueue,
  CLUSTER_EVIDENCE,
  clusterEvidence,
  emptyNextAction,
  NEXT_ACTION_CHIP_LABEL,
  NEXT_ACTION_KIND,
  NONE_REASON,
  queueItemToNextAction,
  type ClusterEvidence,
  type NextActionKind,
  type NoneReason,
  type ReviewQueueBand,
  type ReviewQueueFilter,
  type ReviewQueueItem,
  type WorkbenchNextAction,
} from './reviewQueueDriver';
import { isHumanLabeledTarget } from './suggestionProjection';
import { useSuggestionReviewQueries } from './useSuggestionReviewQueries';

export {
  CLUSTER_EVIDENCE,
  NEXT_ACTION_CHIP_LABEL,
  NEXT_ACTION_KIND,
  NONE_REASON,
  type ClusterEvidence,
  type NextActionKind,
  type NoneReason,
  type ReviewQueueBand,
  type ReviewQueueFilter,
  type ReviewQueueItem,
  type WorkbenchNextAction,
};

// Re-export pure driver surface for consumers that already import from this module.
export {
  buildReviewQueue,
  bulkSelectableIdsInFilters,
  clampQueueIndex,
  clusterEvidence,
  filterReviewQueue,
  filterReviewQueueByBand,
  filterReviewQueueComposite,
  intersectSelectionWithFilters,
  isZeroEvidenceCluster,
  matchesSimilarityBand,
  nextQueueIndex,
  prevQueueIndex,
  queueItemSimilarity,
  REVIEW_QUEUE_BAND,
  REVIEW_QUEUE_BAND_CHIP_LABEL,
  REVIEW_QUEUE_DRAIN_MESSAGE,
  REVIEW_QUEUE_FILTER,
  STRONG_SIMILARITY_MIN,
  queueItemToNextAction,
} from './reviewQueueDriver';

export interface WorkbenchFindingsCounts {
  assignments: number;
  merges: number;
  names: number;
  unlabeledClusters: number;
  total: number;
}

export interface WorkbenchFindingPreview {
  key: string;
  thumbUrl: string | null;
  attachmentUrl?: string | null;
  mediaUrl: string | null;
  label: string | null;
  /**
   * True when `label` is a machine suggestion / unconfirmed claim
   * (suggested_label, suggested_name, enrichment.suggestedLabel). False for
   * operator-confirmed labels and when there is no label. Cluster previews
   * never read `cluster.label` (top-unlabeled contract — see collectPreviews).
   */
  labelIsSuggested: boolean;
  /** Face crop box when the payload carried one; absent/null stays null (rg-015). */
  bbox: BoundingBox | null;
}

export interface WorkbenchFindingsQueues {
  reviewItems: SuggestionReviewItem[];
  assignmentTotal: number;
  mergeSuggestions: PendingMergeSuggestion[];
  mergeTotal: number;
  nameSuggestions: PendingNameSuggestion[];
  nameTotal: number;
  topUnlabeledClusters: TopUnlabeledCluster[];
  topUnlabeledTotal: number;
  /** Server envelope: the loaded top-unlabeled page is not the full backlog. */
  topUnlabeledTruncated: boolean;
}

export interface WorkbenchFindingsSourceState {
  assignmentDataSource: DataSource | undefined;
  nameDataSource: DataSource | undefined;
  topUnlabeledDataSource: DataSource | undefined;
  isLoading: boolean;
  isError: boolean;
  /** Projection outage on top-unlabeled — distinct from primary-queue isError. */
  isTopUnlabeledError: boolean;
  /** Outage on the assignment queue alone — distinct from the all-queues isError. */
  isAssignmentError: boolean;
  /** All four queue-source queries finished initial load (data or error). */
  queueSettled: boolean;
}

export interface WorkbenchFindingsViewModel {
  counts: WorkbenchFindingsCounts;
  previews: WorkbenchFindingPreview[];
  /**
   * Loaded-page-only count of clusters gated out of the queue
   * (identity_count === 0 or no representatives). Page-scoped repair signal —
   * do not subtract it from counts.unlabeledClusters / total, which stay
   * honest to the server envelope. Repair-row and queue-drain logic key off
   * this loaded-page count (E21-20-REV1-01).
   */
  zeroEvidenceClusterCount: number;
  /**
   * True when the top-unlabeled envelope reports truncated. Repair copy must
   * qualify the page-local zero count (E21-20-REV2-04).
   */
  topUnlabeledTruncated: boolean;
  hasFindings: boolean;
  isLoading: boolean;
  isError: boolean;
  /**
   * True when the top-unlabeled query failed. Must not be laundered into empty
   * findings or a measured unlabeled count of 0 (UI-03 / UI-06, RLSE-05).
   * Required: an omitted flag silently restores the laundered-empty behaviour.
   */
  isTopUnlabeledError: boolean;
  /**
   * True when the assignment queue failed while other sources returned data.
   * Without it, a lone assignment 500 leaves hasAnyData true and isError false,
   * so the panel renders the "No findings yet" all-clear while the primary
   * review queue is down (E21-20-REV2-01).
   */
  isAssignmentError: boolean;
  isUnavailable: boolean;
  isReadOnly: boolean;
  /**
   * True only when every queue source query has finished its initial load
   * (has data or errored). Partial resolve must not look settled — clamp/index
   * restore depends on the full queue (BR-06).
   */
  queueSettled: boolean;
  /** Head of the ordered review queue (same as queue[0] when non-empty). */
  nextAction: WorkbenchNextAction;
  /**
   * Full ordered, unfiltered review queue (groups flattened per-suggestion).
   * Filter with `filterReviewQueue(queue, filter)` — not applied here so existing
   * consumers of nextAction keep default priority semantics.
   */
  queue: ReviewQueueItem[];
}

const PREVIEW_LIMIT = 6;

const sortClustersBySize = (clusters: TopUnlabeledCluster[]): TopUnlabeledCluster[] =>
  [...clusters].sort((a, b) => b.identity_count - a.identity_count);

const selectNextAction = (
  queue: readonly ReviewQueueItem[],
  state: { isLoading: boolean; isError: boolean; isUnavailable: boolean },
): WorkbenchNextAction => {
  if (queue.length > 0) {
    return queueItemToNextAction(queue[0]);
  }
  if (state.isLoading) {
    return emptyNextAction(NONE_REASON.LOADING);
  }
  if (state.isError) {
    return emptyNextAction(NONE_REASON.ERROR);
  }
  if (state.isUnavailable) {
    return emptyNextAction(NONE_REASON.UNAVAILABLE);
  }
  return emptyNextAction(NONE_REASON.EMPTY);
};

/**
 * Capture key must match what the strip actually renders (HAI-17):
 * 1. Dedicated face-thumb URL → key on that thumb (two face-thumbs = two faces).
 * 2. Else mediaUrl → the photograph; croppable bboxes stay distinct (two people
 *    in a group shot). Non-croppable / null / zero-extent sentinels share one
 *    key — they render the same uncropped pixels (isCroppableBbox is canonical).
 * 3. Else key on thumbUrl.
 */
const previewCaptureKey = (preview: WorkbenchFindingPreview): string => {
  if (isDedicatedFaceThumbUrl(preview.thumbUrl) && preview.thumbUrl) {
    return `ft:${preview.thumbUrl}`;
  }
  if (preview.mediaUrl) {
    const bbox = preview.bbox;
    const bboxKey = isCroppableBbox(bbox)
      ? `${bbox.x}:${bbox.y}:${bbox.width}:${bbox.height}`
      : '';
    return `m:${preview.mediaUrl}|b:${bboxKey}`;
  }
  return `t:${preview.thumbUrl ?? ''}`;
};

const photographIdentity = (preview: WorkbenchFindingPreview): string =>
  preview.mediaUrl ?? previewCaptureKey(preview);

/** Drop exact capture-key repeats; distinct croppable bboxes stay distinct. */
const dedupePreviewsByCapture = (previews: WorkbenchFindingPreview[]): WorkbenchFindingPreview[] => {
  const seen = new Set<string>();
  const unique: WorkbenchFindingPreview[] = [];
  for (const preview of previews) {
    const captureKey = previewCaptureKey(preview);
    if (seen.has(captureKey)) {
      continue;
    }
    seen.add(captureKey);
    unique.push(preview);
  }
  return unique;
};

/**
 * WHY (HAI-17): when PREVIEW_LIMIT binds, prefer distinct photographs (capture
 * times and conditions) over same-photo extras. Pass 1 takes unseen photographs
 * in original order; pass 2 fills remaining slots from skipped rows. Relative
 * order within each pass is preserved — never sort.
 */
const selectDiversePreviews = (
  previews: WorkbenchFindingPreview[],
  limit: number,
): WorkbenchFindingPreview[] => {
  const pass1: WorkbenchFindingPreview[] = [];
  const skipped: WorkbenchFindingPreview[] = [];
  const seenPhotos = new Set<string>();

  for (const preview of previews) {
    const photoId = photographIdentity(preview);
    if (!seenPhotos.has(photoId) && pass1.length < limit) {
      pass1.push(preview);
      seenPhotos.add(photoId);
    } else {
      skipped.push(preview);
    }
  }

  if (pass1.length >= limit) {
    return pass1;
  }

  const filled = [...pass1];
  for (const preview of skipped) {
    if (filled.length >= limit) {
      break;
    }
    filled.push(preview);
  }
  return filled;
};

const collectPreviews = (
  queues: WorkbenchFindingsQueues,
  sortedClusters: TopUnlabeledCluster[],
): WorkbenchFindingPreview[] => {
  const previews: WorkbenchFindingPreview[] = [];

  for (const item of queues.reviewItems) {
    const suggestion = item.type === 'group' ? item.suggestions[0] : item.suggestion;
    const confirmedLabel = suggestion.label ?? null;
    const suggestedLabel = suggestion.enrichment?.suggestedLabel ?? null;
    const label =
      item.type === 'group'
        ? item.label || null
        : (confirmedLabel ?? suggestedLabel ?? null);
    const labelIsSuggested = Boolean(label) && confirmedLabel == null;
    previews.push({
      key: `assignment-${suggestion.suggestionId}`,
      thumbUrl: suggestion.enrichment?.identityThumbUrl ?? null,
      attachmentUrl: suggestion.enrichment?.identityAttachmentUrl ?? null,
      mediaUrl: suggestion.enrichment?.identityMediaUrl ?? null,
      label,
      labelIsSuggested,
      bbox: suggestion.enrichment?.identityBbox ?? null,
    });
  }

  for (const merge of queues.mergeSuggestions) {
    const rawLabel = merge.cluster_a_label;
    // WHY (A11Y-02 / HAI-01): cluster_a_label is the raw cluster.label column —
    // the backend applies no confirmation gate — so it may be a machine auto-label.
    const label = isHumanLabeledTarget(rawLabel) ? (rawLabel ?? null) : null;
    previews.push({
      key: `merge-${merge.id}`,
      thumbUrl: merge.cluster_a_representative_thumb_url ?? null,
      attachmentUrl: merge.cluster_a_representative_attachment_url ?? null,
      mediaUrl: merge.cluster_a_representative_media_url ?? null,
      label,
      labelIsSuggested: false,
      bbox: merge.cluster_a_representative_bbox ?? null,
    });
  }

  for (const name of queues.nameSuggestions) {
    const representative = name.representatives?.[0];
    const label = name.suggested_name || null;
    previews.push({
      key: `name-${name.id}`,
      thumbUrl: representative?.thumb_url ?? null,
      attachmentUrl: representative?.attachment_url ?? null,
      mediaUrl: representative?.media_url ?? null,
      label,
      // suggested_name is always a machine suggestion.
      labelIsSuggested: Boolean(label),
      bbox: representative?.bbox ?? null,
    });
  }

  for (const cluster of sortedClusters) {
    const representative = cluster.representatives[0];
    // WHY (A11Y-02 / HAI-01): top-unlabeled contract — `label` is null or a
    // machine placeholder, never a person's name. Do not read cluster.label;
    // only suggested_label may surface (hedged via labelIsSuggested).
    const label = cluster.suggested_label ?? null;
    previews.push({
      key: `cluster-${cluster.id}`,
      thumbUrl: representative?.thumb_url ?? null,
      attachmentUrl: representative?.attachment_url ?? null,
      mediaUrl: representative?.media_url ?? null,
      label,
      labelIsSuggested: Boolean(label),
      bbox: representative?.bbox ?? null,
    });
  }

  // Exact-capture dedupe, then diversity-first cap (HAI-17).
  return selectDiversePreviews(
    dedupePreviewsByCapture(
      previews.filter(
        (preview) => preview.thumbUrl !== null || preview.mediaUrl !== null || preview.attachmentUrl != null,
      ),
    ),
    PREVIEW_LIMIT,
  );
};

export const buildWorkbenchFindings = (
  queues: WorkbenchFindingsQueues,
  state: WorkbenchFindingsSourceState,
): WorkbenchFindingsViewModel => {
  const sortedClusters = sortClustersBySize(queues.topUnlabeledClusters);
  const evidenceClusters = sortedClusters.filter(
    (cluster) => clusterEvidence(cluster) === CLUSTER_EVIDENCE.PRESENT,
  );
  const zeroEvidenceClusterCount = sortedClusters.length - evidenceClusters.length;
  // Server envelope stays honest: page-local zeros are a repair signal, not a
  // deduction from the unlabeled total (E21-20-REV1-01).
  const unlabeledClusters = queues.topUnlabeledTotal;
  const counts: WorkbenchFindingsCounts = {
    assignments: queues.assignmentTotal,
    merges: queues.mergeTotal,
    names: queues.nameTotal,
    unlabeledClusters,
    total: queues.assignmentTotal + queues.mergeTotal + queues.nameTotal + unlabeledClusters,
  };

  // WHY: assignment + top-unlabeled are the canonical availability signals; merge/name
  // outages degrade gracefully to a partial summary instead of hiding the panel.
  const isUnavailable =
    state.assignmentDataSource === DATA_SOURCE.UNAVAILABLE || state.topUnlabeledDataSource === DATA_SOURCE.UNAVAILABLE;
  const isReadOnly =
    state.assignmentDataSource === DATA_SOURCE.BACKEND_PROXY ||
    state.nameDataSource === DATA_SOURCE.BACKEND_PROXY ||
    state.topUnlabeledDataSource === DATA_SOURCE.BACKEND_PROXY;

  const queue = buildReviewQueue({
    reviewItems: queues.reviewItems,
    mergeSuggestions: queues.mergeSuggestions,
    nameSuggestions: queues.nameSuggestions,
    sortedClusters: evidenceClusters,
  });

  // WHY: a top-unlabeled 500 with an empty primary queue is still a failure, not
  // an empty backlog — selectNextAction must prefer ERROR over EMPTY (UI-03).
  const isError = state.isError || (state.isTopUnlabeledError && counts.total === 0);

  return {
    counts,
    previews: collectPreviews(queues, evidenceClusters),
    zeroEvidenceClusterCount,
    topUnlabeledTruncated: queues.topUnlabeledTruncated,
    hasFindings: counts.total > 0,
    isLoading: state.isLoading,
    isError,
    isTopUnlabeledError: state.isTopUnlabeledError,
    isAssignmentError: state.isAssignmentError,
    isUnavailable,
    isReadOnly,
    queueSettled: state.queueSettled,
    queue,
    nextAction: selectNextAction(queue, {
      isLoading: state.isLoading,
      isError,
      isUnavailable,
    }),
  };
};

/** Settled = finished initial load (data present, empty success, error, or disabled). */
const isQuerySettled = (query: { isLoading: boolean; isError: boolean; data: unknown }): boolean =>
  Boolean(query.data) || query.isError || !query.isLoading;

export const useWorkbenchFindings = (): WorkbenchFindingsViewModel => {
  const {
    assignmentQuery,
    mergeQuery,
    nameQuery,
    topUnlabeledQuery,
    assignmentDataSource,
    assignmentSuggestions,
    mergeSuggestions,
    nameSuggestions,
    nameDataSource,
    topUnlabeledClusters,
    topUnlabeledTotal,
    topUnlabeledTruncated,
    topUnlabeledDataSource,
    reviewItems,
  } = useSuggestionReviewQueries();

  const hasAnyData = Boolean(assignmentQuery.data ?? mergeQuery.data ?? nameQuery.data ?? topUnlabeledQuery.data);
  const isLoading =
    !hasAnyData &&
    (assignmentQuery.isLoading || mergeQuery.isLoading || nameQuery.isLoading || topUnlabeledQuery.isLoading);
  // WHY: surface a hard error only when nothing rendered at all; partial query
  // failures degrade gracefully to whatever findings did load.
  const isError = !hasAnyData && assignmentQuery.isError && mergeQuery.isError;
  // Separate flag so a top-unlabeled 500 is visible even when primary queues
  // returned empty success (UI-03 / UI-06) without blanking partial findings.
  const isTopUnlabeledError = topUnlabeledQuery.isError;
  // REV2-01: same class as isTopUnlabeledError. An assignment-only outage keeps
  // hasAnyData true (merge/name/top-unlabeled succeeded empty), so isError stays
  // false and the panel would otherwise announce an all-clear over a dead queue.
  const isAssignmentError = assignmentQuery.isError;
  // BR-06: every source must settle before clamp/index restore — partial
  // assignment+merge data must not look like a complete empty/short queue.
  const queueSettled =
    isQuerySettled(assignmentQuery) &&
    isQuerySettled(mergeQuery) &&
    isQuerySettled(nameQuery) &&
    isQuerySettled(topUnlabeledQuery);

  // COR-3 (rg-015): no authoritative backlog total exists; count loaded items.
  const assignmentTotal = assignmentSuggestions?.length ?? 0;
  const mergeTotal = mergeSuggestions.length;
  const nameTotal = nameSuggestions.length;
  const resolvedTopUnlabeledTotal = topUnlabeledTotal ?? topUnlabeledClusters.length;

  return buildWorkbenchFindings(
    {
      reviewItems,
      assignmentTotal,
      mergeSuggestions,
      mergeTotal,
      nameSuggestions,
      nameTotal,
      topUnlabeledClusters,
      topUnlabeledTotal: resolvedTopUnlabeledTotal,
      topUnlabeledTruncated,
    },
    {
      assignmentDataSource,
      nameDataSource,
      topUnlabeledDataSource,
      isLoading,
      isError,
      isTopUnlabeledError,
      isAssignmentError,
      queueSettled,
    },
  );
};
