import React from 'react';
import { __ } from '@wordpress/i18n';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import type { PendingMergeSuggestion } from '../../../api/recognition';
import type { FaceOriginalTarget } from './SuggestionCards';
import { ACCENT_PRIMARY_ATTR } from '../mediaFooterCtaState';

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
}

const FaceCropControl = ({
  mediaUrl,
  bbox,
  alt,
  onOpen,
}: {
  mediaUrl: string;
  bbox: NonNullable<PendingMergeSuggestion['cluster_a_representative_bbox']>;
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
    <div
      className="acx-suggestion-card acx-suggestion-card--merge"
      data-testid="acx-review-card"
      data-review-kind="merge"
    >
      <div className="acx-suggestion-card__faces">
        <div className="acx-suggestion-card__face">
          {hasClusterAFace ? (
            <FaceCropControl
              mediaUrl={suggestion.cluster_a_representative_media_url!}
              bbox={suggestion.cluster_a_representative_bbox!}
              alt={clusterALabel}
              onOpen={onOpenOriginal}
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
            <FaceCropControl
              mediaUrl={suggestion.cluster_b_representative_media_url!}
              bbox={suggestion.cluster_b_representative_bbox!}
              alt={clusterBLabel}
              onOpen={onOpenOriginal}
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
      </div>
    </div>
  );
};
