import React from 'react';
import { __ } from '@wordpress/i18n';

import { Avatar } from '../../../../components/ui/avatar';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import type { BoundingBox } from '../../../api/recognition/types/identity';
import type { ReviewSuggestion, SuggestionReviewItem } from './suggestionReviewItems';

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
}

const FaceCropControl = ({
  mediaUrl,
  bbox,
  alt,
  onOpen,
}: {
  mediaUrl: string;
  bbox: BoundingBox;
  alt: string;
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
}: SuggestionCardProps): React.JSX.Element => {
  // buildSuggestionReviewItems guarantees a human-labeled target with truthy label (UXP-3-BR-22).
  const displayLabel = suggestion.label ?? '';
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

  return (
    <div
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
            />
          ) : identityThumbUrl ? (
            <Avatar
              src={identityThumbUrl}
              size="lg"
              alt={__('Candidate face', 'alt-context')}
              className="acx-suggestion-card__thumb"
            />
          ) : (
            <span className="acx-suggestion-card__thumb acx-suggestion-card__thumb--placeholder" />
          )}
          <span className="acx-suggestion-card__face-label">{__('Candidate', 'alt-context')}</span>
        </div>

        <div className="acx-suggestion-card__face">
          {representativeFace ? (
            <FaceCropControl
              mediaUrl={representativeFace.mediaUrl}
              bbox={representativeFace.bbox}
              alt={displayLabel || __('Cluster representative', 'alt-context')}
              onOpen={onOpenOriginal}
            />
          ) : representativeThumbUrl ? (
            <Avatar
              src={representativeThumbUrl}
              size="lg"
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
          className="button button-primary acx-suggestion-card__accept"
          onClick={onAccept}
          disabled={isPending}
          title={isPending && disabledReason ? disabledReason : undefined}
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
    </div>
  );
};
