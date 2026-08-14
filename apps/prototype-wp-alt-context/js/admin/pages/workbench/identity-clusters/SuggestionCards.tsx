import React from 'react';
import { __ } from '@wordpress/i18n';

import { DurableFaceThumb } from '../../../../components/ui/DurableFaceThumb';
import type { FaceThumbSource } from '../../../../components/ui/faceThumbDisplay';
import type { BoundingBox } from '../../../api/recognition/types/identity';
import { ReviewCardGroupShell } from './reviewCardGroupAccname';
import type { ReviewSuggestion, SuggestionReviewItem } from './suggestionReviewItems';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';

export type { ReviewSuggestion, SuggestionReviewItem };

export interface FaceOriginalTarget {
  mediaUrl: string;
  bbox: BoundingBox;
  label?: string;
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
  source,
  alt,
  onOpen,
}: {
  source: FaceThumbSource;
  alt: string;
  onOpen?: (target: FaceOriginalTarget) => void;
}): React.JSX.Element => {
  const thumb = (
    <DurableFaceThumb source={source} size="md" alt={alt} className="acx-suggestion-card__thumb" />
  );
  const originalUrl = source.attachmentUrl ?? source.mediaUrl;
  const bbox = source.bbox;
  if (!onOpen || !originalUrl || !bbox) {
    return thumb;
  }

  return (
    <button
      type="button"
      className="acx-face-crop-control"
      onClick={() => onOpen({ mediaUrl: originalUrl, bbox, label: alt })}
      aria-label={__('View original photo', 'alt-context')}
    >
      {thumb}
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
  const identitySource: FaceThumbSource = {
    thumbUrl: suggestion.enrichment?.identityThumbUrl,
    attachmentUrl: suggestion.enrichment?.identityAttachmentUrl,
    mediaUrl: suggestion.enrichment?.identityMediaUrl,
    bbox: suggestion.enrichment?.identityBbox,
  };
  const representativeSource: FaceThumbSource = {
    thumbUrl: suggestion.enrichment?.representativeThumbUrl,
    attachmentUrl: suggestion.enrichment?.representativeAttachmentUrl,
    mediaUrl: suggestion.enrichment?.representativeMediaUrl,
    bbox: suggestion.enrichment?.representativeBbox,
  };
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
          <FaceCropControl
            source={identitySource}
            alt={__('Candidate face', 'alt-context')}
            onOpen={onOpenOriginal}
          />
          <span className="acx-suggestion-card__face-label">{__('Candidate', 'alt-context')}</span>
        </div>

        <div className="acx-suggestion-card__face">
          <FaceCropControl source={representativeSource} alt={displayLabel} onOpen={onOpenOriginal} />
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
              ({suggestion.identityCount} {__('in cluster', 'alt-context')})
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
            title={__('Review cluster details', 'alt-context')}
          >
            {__('Review details', 'alt-context')}
          </button>
        ) : null}
      </div>
    </ReviewCardGroupShell>
  );
};
