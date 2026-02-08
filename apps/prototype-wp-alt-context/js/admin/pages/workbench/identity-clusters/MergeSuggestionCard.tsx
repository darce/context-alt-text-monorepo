import React from 'react';
import { __ } from '@wordpress/i18n';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import type { PendingMergeSuggestion } from '../../../api/recognition';

export interface MergeSuggestionCardProps {
  suggestion: PendingMergeSuggestion;
  onAccept: () => void;
  onReject: () => void;
  isPending: boolean;
}

export const MergeSuggestionCard = ({
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
