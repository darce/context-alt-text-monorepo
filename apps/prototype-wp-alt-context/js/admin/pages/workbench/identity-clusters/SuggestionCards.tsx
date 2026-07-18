import React from 'react';
import { __ } from '@wordpress/i18n';

import { Avatar } from '../../../../components/ui/avatar';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import type { ReviewSuggestion, SuggestionReviewItem } from './suggestionReviewItems';

export type { ReviewSuggestion, SuggestionReviewItem };

interface SuggestionCardProps {
  suggestion: ReviewSuggestion;
  onAccept: () => void;
  onReject: () => void;
  onReview?: (clusterId?: string) => void;
  isPending: boolean;
  lowConfidenceThreshold: number;
}

interface GroupedSuggestionCardProps {
  clusterId: string;
  label: string;
  suggestions: ReviewSuggestion[];
  onAcceptAll: () => void;
  onRejectAll: () => void;
  onToggleReviewEach: () => void;
  isExpanded: boolean;
  isPending: boolean;
  lowConfidenceThreshold: number;
  children?: React.ReactNode;
}

export const SuggestionCard = ({
  suggestion,
  onAccept,
  onReject,
  onReview,
  isPending,
  lowConfidenceThreshold,
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
    <div className={`acx-suggestion-card${isLowConfidence ? ' acx-suggestion-card--low-confidence' : ''}`}>
      <div className="acx-suggestion-card__faces">
        <div className="acx-suggestion-card__face">
          {identityFace ? (
            <FaceThumbnail
              mediaUrl={identityFace.mediaUrl}
              bbox={identityFace.bbox}
              size="md"
              alt={__('Candidate face', 'alt-context')}
              className="acx-suggestion-card__thumb"
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
            <FaceThumbnail
              mediaUrl={representativeFace.mediaUrl}
              bbox={representativeFace.bbox}
              size="md"
              alt={__('Cluster representative', 'alt-context')}
              className="acx-suggestion-card__thumb"
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
        >
          {__('Yes', 'alt-context')}
        </button>
        <button type="button" className="button acx-suggestion-card__reject" onClick={onReject} disabled={isPending}>
          {__('No', 'alt-context')}
        </button>
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

export const GroupedSuggestionCard = ({
  clusterId,
  label,
  suggestions,
  onAcceptAll,
  onRejectAll,
  onToggleReviewEach,
  isExpanded,
  isPending,
  lowConfidenceThreshold,
  children,
}: GroupedSuggestionCardProps): React.JSX.Element => {
  const topSimilarity = Math.max(...suggestions.map((suggestion) => suggestion.similarity));
  const matchPercent = Math.round(topSimilarity * 100);
  const visibleCandidates = suggestions.slice(0, 8);
  const extraCandidatesCount = Math.max(suggestions.length - visibleCandidates.length, 0);
  const isLowConfidence = topSimilarity < lowConfidenceThreshold;

  return (
    <div
      className={`acx-suggestion-card acx-suggestion-card--group${isLowConfidence ? ' acx-suggestion-card--low-confidence' : ''}`}
      data-cluster-id={clusterId}
    >
      <div className="acx-suggestion-card__faces">
        <div className="acx-suggestion-card__face acx-suggestion-card__face--grid">
          <div className="acx-face-grid-preview acx-face-grid-preview--candidates">
            {visibleCandidates.map((suggestion) => {
              const identityThumbUrl =
                suggestion.enrichment?.identityThumbUrl ?? suggestion.enrichment?.identityMediaUrl;
              return suggestion.enrichment?.identityMediaUrl && suggestion.enrichment?.identityBbox ? (
                <FaceThumbnail
                  key={suggestion.suggestionId}
                  mediaUrl={suggestion.enrichment.identityMediaUrl}
                  bbox={suggestion.enrichment.identityBbox}
                  size="sm"
                  alt={__('Candidate face', 'alt-context')}
                  className="acx-suggestion-card__thumb"
                />
              ) : identityThumbUrl ? (
                <Avatar
                  key={suggestion.suggestionId}
                  src={identityThumbUrl}
                  size="md"
                  alt={__('Candidate face', 'alt-context')}
                  className="acx-suggestion-card__thumb"
                />
              ) : (
                <span
                  key={suggestion.suggestionId}
                  className="acx-suggestion-card__thumb acx-suggestion-card__thumb--placeholder"
                />
              );
            })}
            {extraCandidatesCount > 0 && (
              <span className="acx-suggestion-card__thumb acx-suggestion-card__thumb--more">
                +{extraCandidatesCount}
              </span>
            )}
          </div>
          <span className="acx-suggestion-card__face-label">
            {suggestions.length} {__('candidates', 'alt-context')}
          </span>
        </div>
      </div>

      <div className="acx-suggestion-card__content">
        <p className="acx-suggestion-card__question">
          <strong>{suggestions.length}</strong> {__('candidates may be', 'alt-context')} <strong>{label}</strong>
        </p>
        <p className="acx-suggestion-card__match">
          {__('Top match', 'alt-context')} {matchPercent}%
          {isLowConfidence && (
            <span className="acx-suggestion-card__confidence-flag">{__('Low confidence', 'alt-context')}</span>
          )}
        </p>
      </div>

      <div className="acx-suggestion-card__actions">
        <button
          type="button"
          className="button button-primary acx-suggestion-card__accept"
          onClick={onAcceptAll}
          disabled={isPending}
        >
          {__('Yes all', 'alt-context')}
        </button>
        <button type="button" className="button acx-suggestion-card__reject" onClick={onRejectAll} disabled={isPending}>
          {__('No all', 'alt-context')}
        </button>
        <button
          type="button"
          className="button acx-suggestion-card__review-each"
          onClick={onToggleReviewEach}
          disabled={isPending}
        >
          {isExpanded ? __('Hide details', 'alt-context') : __('Review each', 'alt-context')}
        </button>
      </div>

      {isExpanded ? <div className="acx-suggestion-card__group-items">{children}</div> : null}
    </div>
  );
};
