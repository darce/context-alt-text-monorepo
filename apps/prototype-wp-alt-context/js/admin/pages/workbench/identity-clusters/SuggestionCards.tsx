import React from 'react';
import { __ } from '@wordpress/i18n';

import { Avatar } from '../../../../components/ui/avatar';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import { isPositiveMediaId } from '../../../../components/ui/faceGeometry';
import type { BoundingBox } from '../../../api/recognition/types/identity';
import { ReviewCardGroupShell } from './reviewCardGroupAccname';
import { REPRESENTATIVE_VOCABULARY } from './representativeVocabulary';
import type { ReviewSuggestion, SuggestionReviewItem } from './suggestionReviewItems';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';

export type { ReviewSuggestion, SuggestionReviewItem };

export interface FaceOriginalTarget {
  mediaUrl: string;
  bbox: BoundingBox;
  label?: string;
  mediaId?: number;
  identityId?: string;
  clusterId?: string;
  runSize?: number;
}

interface SuggestionCardProps {
  suggestion: ReviewSuggestion;
  onAccept: () => void;
  onReject: () => void;
  onReview?: (clusterId?: string) => void;
  /** Opens click-to-original lightbox for a face crop (E21-5 ②). */
  onOpenOriginal?: (target: FaceOriginalTarget) => void;
  isPending: boolean;
  /** BR-47: title when Accept/Reject disabled (e.g. selected for bulk). */
  disabledReason?: string | null;
  lowConfidenceThreshold: number;
  /** Slice-2 hold/failure chrome — placed immediately after the actioned control. */
  actionAccessory?: React.ReactNode;
  actionAccessoryAfter?: 'accept' | 'reject';
  /**
   * §7 single accent primary: when true, Accept is this card's accent-primary and
   * carries the `data-acx-accent-primary` marker + accent chrome (COL-03). The
   * ReviewQueue only sets this on the mounted current card, so exactly one marker
   * is present per rendered viewport.
   */
  accentPrimary?: boolean;
  /**
   * BR-41: 1-based queue position. When BOTH `queuePosition` and `queueTotal` are
   * valid integers >= 1, ordinal text folds into the group accname.
   */
  queuePosition?: number;
  /** BR-41: filtered queue length paired with `queuePosition`. */
  queueTotal?: number;
}

/** buildSuggestionReviewItems only emits human-labeled targets (truthy trimmed label). */
function assertTruthyLabel(label: string | null | undefined): asserts label is string {
  if (typeof label !== 'string' || label.trim().length === 0) {
    throw new Error('SuggestionCard requires a truthy suggestion.label');
  }
}

const FaceCropControl = ({
  mediaUrl,
  bbox,
  alt,
  onOpen,
  mediaId,
  identityId,
}: {
  mediaUrl: string;
  bbox: BoundingBox;
  alt: string;
  onOpen?: (target: FaceOriginalTarget) => void;
  mediaId?: number;
  identityId?: string;
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

  const openOriginal = (): void => {
    const target: FaceOriginalTarget = { mediaUrl, bbox, label: alt };
    if (isPositiveMediaId(mediaId)) {
      target.mediaId = mediaId;
    }
    if (typeof identityId === 'string' && identityId.length > 0) {
      target.identityId = identityId;
    }
    onOpen(target);
  };

  return (
    <button
      type="button"
      className="acx-face-crop-control"
      onClick={openOriginal}
      aria-label={__('View original photo', 'alt-context')}
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

export const SuggestionCard = ({
  suggestion,
  onAccept,
  onReject,
  onReview,
  onOpenOriginal,
  isPending,
  disabledReason = null,
  lowConfidenceThreshold,
  actionAccessory = null,
  actionAccessoryAfter = 'accept',
  accentPrimary = false,
  queuePosition,
  queueTotal,
}: SuggestionCardProps): React.JSX.Element => {
  // BR-22: no empty-label / Unnamed / suggestedLabel-badge / !hasLabel branches — label is required.
  assertTruthyLabel(suggestion.label);
  const displayLabel = suggestion.label;
  const matchPercent = Math.round(suggestion.similarity * 100);
  const isLowConfidence = suggestion.similarity < lowConfidenceThreshold;
  const identityFace =
    suggestion.enrichment?.identityMediaUrl && suggestion.enrichment?.identityBbox
      ? { mediaUrl: suggestion.enrichment.identityMediaUrl, bbox: suggestion.enrichment.identityBbox }
      : null;
  const representativeFace =
    suggestion.enrichment?.representativeMediaUrl && suggestion.enrichment?.representativeBbox
      ? {
          mediaUrl: suggestion.enrichment.representativeMediaUrl,
          bbox: suggestion.enrichment.representativeBbox,
        }
      : null;
  const identityThumbUrl = suggestion.enrichment?.identityThumbUrl ?? suggestion.enrichment?.identityMediaUrl ?? null;
  const representativeThumbUrl =
    suggestion.enrichment?.representativeThumbUrl ?? suggestion.enrichment?.representativeMediaUrl ?? null;
  const groupLabelId = `acx-assignment-pos-${suggestion.suggestionId}`;

  return (
    <ReviewCardGroupShell
      kind="assignment"
      labelId={groupLabelId}
      queuePosition={queuePosition}
      queueTotal={queueTotal}
      className={`acx-suggestion-card${isLowConfidence ? ' acx-suggestion-card--low-confidence' : ''}`}
      data-testid="acx-review-card"
      data-review-kind="assignment"
    >
      <div className="acx-suggestion-card__faces">
        <div className="acx-suggestion-card__face">
          {identityFace ? (
            <FaceCropControl
              mediaUrl={identityFace.mediaUrl}
              bbox={identityFace.bbox}
              alt={__('Candidate face', 'alt-context')}
              onOpen={onOpenOriginal}
              mediaId={suggestion.enrichment?.identityMediaId ?? undefined}
              identityId={suggestion.identityId}
            />
          ) : identityThumbUrl ? (
            <Avatar
              src={identityThumbUrl}
              size="lg"
              alt={__('Candidate face', 'alt-context')}
              className="acx-suggestion-card__thumb"
            />
          ) : (
            <Avatar
              size="lg"
              className="acx-suggestion-card__thumb"
              missingLabel={REPRESENTATIVE_VOCABULARY.imageUnavailable}
            />
          )}
          <span className="acx-suggestion-card__face-label">{__('Candidate', 'alt-context')}</span>
        </div>

        <div className="acx-suggestion-card__face">
          {representativeFace ? (
            <FaceCropControl
              mediaUrl={representativeFace.mediaUrl}
              bbox={representativeFace.bbox}
              alt={displayLabel}
              onOpen={onOpenOriginal}
            />
          ) : representativeThumbUrl ? (
            <Avatar
              src={representativeThumbUrl}
              size="lg"
              alt={displayLabel}
              className="acx-suggestion-card__thumb"
            />
          ) : (
            <Avatar
              size="lg"
              className="acx-suggestion-card__thumb"
              missingLabel={REPRESENTATIVE_VOCABULARY.imageUnavailable}
            />
          )}
          <span className="acx-suggestion-card__face-label">{displayLabel}</span>
        </div>
      </div>
      <div className="acx-suggestion-card__content">
        <p className="acx-suggestion-card__question">
          {__('Is this', 'alt-context')} <strong>{displayLabel}</strong>?
        </p>
        <p className="acx-suggestion-card__match">
          {matchPercent}% {__('match', 'alt-context')}
          {suggestion.identityCount && (
            <span className="acx-suggestion-card__count">
              {' '}
              ({suggestion.identityCount} {__('faces', 'alt-context')})
            </span>
          )}
          {isLowConfidence && (
            <span className="acx-suggestion-card__confidence-flag">{__('Low confidence', 'alt-context')}</span>
          )}
        </p>
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
        >
          {__('No', 'alt-context')}
        </button>
        {actionAccessoryAfter === 'reject' ? actionAccessory : null}
        {onReview ? (
          <button
            type="button"
            className="button button-link acx-suggestion-card__review"
            onClick={() => onReview(suggestion.clusterId)}
            title={__('Review these faces', 'alt-context')}
          >
            {__('Review details', 'alt-context')}
          </button>
        ) : null}
      </div>
    </ReviewCardGroupShell>
  );
};
