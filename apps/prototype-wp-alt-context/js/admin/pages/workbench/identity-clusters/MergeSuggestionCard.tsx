import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { Avatar } from '../../../../components/ui/avatar';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import type { PendingMergeSuggestion } from '../../../api/recognition';
import type { FaceOriginalTarget } from './SuggestionCards';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';
import { isHumanLabeledTarget } from './suggestionProjection';
import { isValidQueueOrdinal, isValidQueueOrdinalPair } from './reviewQueueDriver';

export interface MergeSuggestionCardProps {
  suggestion: PendingMergeSuggestion;
  onAccept: () => void;
  onReject: () => void;
  onOpenOriginal?: (target: FaceOriginalTarget) => void;
  isPending: boolean;
  /** BR-47: title when Accept/Reject disabled (e.g. selected for bulk). */
  disabledReason?: string | null;
  /** Slice-2 hold/failure chrome — placed immediately after the actioned control. */
  actionAccessory?: React.ReactNode;
  actionAccessoryAfter?: 'accept' | 'reject';
  /** §7 single accent primary: mark + accent-style Accept as this card's primary (COL-03). */
  accentPrimary?: boolean;
  /**
   * BR-35: 1-based queue position. When BOTH `queuePosition` and `queueTotal` are
   * provided, ordinal text disambiguates group / Yes-No / face-control accnames.
   * Omit both (or either) for byte-identical fallback strings.
   */
  queuePosition?: number;
  /** BR-35: total items in the filtered review queue (paired with `queuePosition`). */
  queueTotal?: number;
}

const FaceCropControl = ({
  mediaUrl,
  bbox,
  alt,
  controlAriaLabel,
  onOpen,
}: {
  mediaUrl: string;
  bbox: NonNullable<PendingMergeSuggestion['cluster_a_representative_bbox']>;
  alt: string;
  controlAriaLabel: string;
  onOpen?: (target: FaceOriginalTarget) => void;
}): React.JSX.Element => {
  if (!onOpen) {
    return (
      <FaceThumbnail
        mediaUrl={mediaUrl}
        bbox={bbox}
        size="md"
        alt={alt}
        className="acx-suggestion-card__thumb"
      />
    );
  }

  return (
    <button
      type="button"
      className="acx-face-crop-control"
      onClick={() => onOpen({ mediaUrl, bbox, label: alt })}
      aria-label={controlAriaLabel}
    >
      <FaceThumbnail
        mediaUrl={mediaUrl}
        bbox={bbox}
        size="md"
        alt={alt}
        className="acx-suggestion-card__thumb"
      />
    </button>
  );
};

export const MergeSuggestionCard = ({
  suggestion,
  onAccept,
  onReject,
  onOpenOriginal,
  isPending,
  disabledReason = null,
  actionAccessory = null,
  actionAccessoryAfter = 'accept',
  accentPrimary = false,
  queuePosition,
  queueTotal,
}: MergeSuggestionCardProps): React.JSX.Element => {
  const matchPercent = Math.round(suggestion.similarity * 100);
  // WHY (A11Y-02 / HAI-01): cluster_*_label is the raw cluster.label column — no
  // confirmation gate — so auto `cluster-*` must not name a face on screen or in alt.
  // Use trimming isHumanLabeledTarget (not isMeaningfulMergeLabel) so whitespace-padded
  // auto-labels are gated the same as bare ones.
  const humanLabelA = isHumanLabeledTarget(suggestion.cluster_a_label)
    ? suggestion.cluster_a_label
    : null;
  const humanLabelB = isHumanLabeledTarget(suggestion.cluster_b_label)
    ? suggestion.cluster_b_label
    : null;
  const clusterALabel = humanLabelA ?? __('Unnamed cluster', 'alt-context');
  const clusterBLabel = humanLabelB ?? __('Unnamed cluster', 'alt-context');
  // BR-30: per-side alt differentiators for auto labels; human names stay unchanged.
  const clusterAAlt =
    humanLabelA ??
    sprintf(__('Detected face (%s)', 'alt-context'), __('first cluster', 'alt-context'));
  const clusterBAlt =
    humanLabelB ??
    sprintf(__('Detected face (%s)', 'alt-context'), __('second cluster', 'alt-context'));
  // BR-35/BR-40/TS41-1: only when the ordinal pair is valid (ints >= 1 and position <= total).
  // Otherwise keep today's no-ordinal / question-only labels.
  // Pair predicate narrows position; single-guard on total restores dual narrowing for sprintf.
  const hasQueueOrdinal =
    isValidQueueOrdinalPair(queuePosition, queueTotal) && isValidQueueOrdinal(queueTotal);
  const faceControlALabel = hasQueueOrdinal
    ? sprintf(
        /* translators: 1: face side (e.g. "first face"), 2: 1-based position, 3: queue total */
        __('View original photo, %1$s, suggestion %2$d of %3$d', 'alt-context'),
        __('first face', 'alt-context'),
        queuePosition,
        queueTotal,
      )
    : sprintf(
        __('View original photo, %s', 'alt-context'),
        __('first face', 'alt-context'),
      );
  const faceControlBLabel = hasQueueOrdinal
    ? sprintf(
        /* translators: 1: face side (e.g. "second face"), 2: 1-based position, 3: queue total */
        __('View original photo, %1$s, suggestion %2$d of %3$d', 'alt-context'),
        __('second face', 'alt-context'),
        queuePosition,
        queueTotal,
      )
    : sprintf(
        __('View original photo, %s', 'alt-context'),
        __('second face', 'alt-context'),
      );
  const hasClusterAFace = Boolean(
    suggestion.cluster_a_representative_media_url && suggestion.cluster_a_representative_bbox,
  );
  const hasClusterBFace = Boolean(
    suggestion.cluster_b_representative_media_url && suggestion.cluster_b_representative_bbox,
  );
  const clusterACount = suggestion.cluster_a_identity_count;
  const clusterBCount = suggestion.cluster_b_identity_count;

  // BR-30: per-card context so co-rendered Yes/No pairs resolve distinctly via
  // aria-describedby (keeps accessible name = visible "Yes"/"No" for label-in-name).
  // DOM ids may key on suggestion.id; accessible text never includes raw cluster-* labels.
  const questionId = `acx-merge-q-${suggestion.id}`;
  const contextId = `acx-merge-ctx-${suggestion.id}`;
  const positionId = `acx-merge-pos-${suggestion.id}`;
  const sideAContext = humanLabelA ?? __('first cluster', 'alt-context');
  const sideBContext = humanLabelB ?? __('second cluster', 'alt-context');
  const matchContext = `${matchPercent}% ${__('match', 'alt-context')}`;
  const baseCardContext = sprintf(
    /* translators: 1: first side label, 2: second side label, 3: match percent label (e.g. "87% match") */
    __('%1$s and %2$s, %3$s', 'alt-context'),
    sideAContext,
    sideBContext,
    matchContext,
  );
  // BR-35: fold ordinal into describedby target so Yes/No descriptions stay unique
  // across equal-match cards (group name alone is not enough for button descriptions).
  const cardContext = hasQueueOrdinal
    ? sprintf(
        /* translators: 1: side/match context, 2: 1-based position, 3: queue total */
        __('%1$s, suggestion %2$d of %3$d', 'alt-context'),
        baseCardContext,
        queuePosition,
        queueTotal,
      )
    : baseCardContext;
  const positionLabel = hasQueueOrdinal
    ? sprintf(
        /* translators: 1: 1-based position, 2: queue total */
        __('Merge suggestion %1$d of %2$d', 'alt-context'),
        queuePosition,
        queueTotal,
      )
    : null;
  const groupLabelledBy = positionLabel ? `${positionId} ${questionId}` : questionId;

  return (
    <div
      className="acx-suggestion-card acx-suggestion-card--merge"
      data-testid="acx-review-card"
      data-review-kind="merge"
      role="group"
      aria-labelledby={groupLabelledBy}
      aria-describedby={contextId}
    >
      <div className="acx-suggestion-card__faces">
        <div className="acx-suggestion-card__face">
          {hasClusterAFace ? (
            <FaceCropControl
              mediaUrl={suggestion.cluster_a_representative_media_url!}
              bbox={suggestion.cluster_a_representative_bbox!}
              alt={clusterAAlt}
              controlAriaLabel={faceControlALabel}
              onOpen={onOpenOriginal}
            />
          ) : (
            <Avatar size="md" className="acx-suggestion-card__thumb" />
          )}
          <span className="acx-suggestion-card__face-label">
            {clusterALabel}
            {clusterACount ? ` (${clusterACount})` : ''}
          </span>
        </div>
        <div className="acx-suggestion-card__face">
          {hasClusterBFace ? (
            <FaceCropControl
              mediaUrl={suggestion.cluster_b_representative_media_url!}
              bbox={suggestion.cluster_b_representative_bbox!}
              alt={clusterBAlt}
              controlAriaLabel={faceControlBLabel}
              onOpen={onOpenOriginal}
            />
          ) : (
            <Avatar size="md" className="acx-suggestion-card__thumb" />
          )}
          <span className="acx-suggestion-card__face-label">
            {clusterBLabel}
            {clusterBCount ? ` (${clusterBCount})` : ''}
          </span>
        </div>
      </div>
      <div className="acx-suggestion-card__content">
        {positionLabel ? (
          <span id={positionId} className="screen-reader-text">
            {positionLabel}
          </span>
        ) : null}
        <p id={questionId} className="acx-suggestion-card__question">
          {__('Are these the same person?', 'alt-context')}
        </p>
        <p className="acx-suggestion-card__match">
          {matchPercent}% {__('match', 'alt-context')}
        </p>
        <span id={contextId} className="screen-reader-text">
          {cardContext}
        </span>
      </div>

      <div className="acx-suggestion-card__actions">
        <button
          type="button"
          className={
            accentPrimary
              ? 'button button-primary acx-suggestion-card__accept acx-accent-primary-action'
              : 'button button-primary acx-suggestion-card__accept'
          }
          onClick={onAccept}
          disabled={isPending}
          title={isPending && disabledReason ? disabledReason : undefined}
          aria-describedby={`${questionId} ${contextId}`}
          {...(accentPrimary ? { [ACCENT_PRIMARY_ATTR]: true } : {})}
        >
          {__('Yes', 'alt-context')}
        </button>
        {actionAccessoryAfter === 'accept' ? actionAccessory : null}
        <button
          type="button"
          className="button acx-suggestion-card__reject"
          onClick={onReject}
          disabled={isPending}
          title={isPending && disabledReason ? disabledReason : undefined}
          aria-describedby={`${questionId} ${contextId}`}
        >
          {__('No', 'alt-context')}
        </button>
        {actionAccessoryAfter === 'reject' ? actionAccessory : null}
      </div>
    </div>
  );
};
