import React from 'react';
import { __ } from '@wordpress/i18n';

import { Avatar } from '../../../../components/ui/avatar';
import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import type { PendingSuggestion } from '../../../api/recognition';

interface SuggestionCardProps {
  suggestion: PendingSuggestion;
  onAccept: () => void;
  onReject: () => void;
  onLabel: (clusterId?: string) => void;
  onReview?: (clusterId?: string) => void;
  isPending: boolean;
  lowConfidenceThreshold: number;
}

interface GroupedSuggestionCardProps {
  clusterId: string;
  label: string;
  suggestions: PendingSuggestion[];
  onAcceptAll: () => void;
  onRejectAll: () => void;
  onToggleReviewEach: () => void;
  isExpanded: boolean;
  isPending: boolean;
  lowConfidenceThreshold: number;
  children?: React.ReactNode;
}

export type SuggestionReviewItem =
  | {
      type: 'single';
      score: number;
      suggestion: PendingSuggestion;
    }
  | {
      type: 'group';
      clusterId: string;
      score: number;
      label: string;
      suggestions: PendingSuggestion[];
    };

export const SuggestionCard = ({
  suggestion,
  onAccept,
  onReject,
  onLabel,
  onReview,
  isPending,
  lowConfidenceThreshold,
}: SuggestionCardProps): React.JSX.Element => {
  const matchPercent = Math.round(suggestion.representative_similarity * 100);
  const isLowConfidence = suggestion.representative_similarity < lowConfidenceThreshold;
  const suggestedLabel = suggestion.suggested_label;
  const hasLabel = Boolean(suggestion.cluster_label ?? suggestedLabel);
  const displayLabel = suggestion.cluster_label ?? suggestedLabel ?? __('Unnamed cluster', 'alt-context');
  const identityFace =
    suggestion.identity_media_url && suggestion.identity_bbox
      ? { mediaUrl: suggestion.identity_media_url, bbox: suggestion.identity_bbox }
      : null;
  const representativeFace =
    suggestion.representative_media_url && suggestion.representative_bbox
      ? { mediaUrl: suggestion.representative_media_url, bbox: suggestion.representative_bbox }
      : null;
  const identityThumbUrl = suggestion.identity_thumb_url ?? suggestion.identity_media_url ?? null;
  const representativeThumbUrl = suggestion.representative_thumb_url ?? suggestion.representative_media_url ?? null;

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
          {hasLabel ? (
            <>
              {__('Is this', 'alt-context')} <strong>{displayLabel}</strong>?
              {suggestedLabel && !suggestion.cluster_label && (
                <span className="acx-badge acx-badge--inferred" title={__('Inferred label', 'alt-context')}>
                  {suggestion.suggested_label_source === 'similar_cluster'
                    ? __('Similar to labeled', 'alt-context')
                    : suggestion.suggested_label_source === 'identity'
                      ? __('Identity match', 'alt-context')
                      : suggestion.suggested_label_source === 'roster'
                        ? __('Roster match', 'alt-context')
                        : __('Suggested', 'alt-context')}
                </span>
              )}
            </>
          ) : (
            <strong>{__('Name this person', 'alt-context')}</strong>
          )}
        </p>
        <p className="acx-suggestion-card__match">
          {matchPercent}% {__('match', 'alt-context')}
          {suggestion.cluster_identity_count && (
            <span className="acx-suggestion-card__count">
              {' '}
              ({suggestion.cluster_identity_count} {__('in cluster', 'alt-context')})
            </span>
          )}
          {isLowConfidence && (
            <span className="acx-suggestion-card__confidence-flag">{__('Low confidence', 'alt-context')}</span>
          )}
        </p>
      </div>

      <div className="acx-suggestion-card__actions">
        {hasLabel ? (
          <>
            <button
              type="button"
              className="button button-primary acx-suggestion-card__accept"
              onClick={onAccept}
              disabled={isPending}
            >
              {__('Yes', 'alt-context')}
            </button>
            <button
              type="button"
              className="button acx-suggestion-card__reject"
              onClick={onReject}
              disabled={isPending}
            >
              {__('No', 'alt-context')}
            </button>
          </>
        ) : (
          <button
            type="button"
            className="button button-primary acx-suggestion-card__label"
            onClick={() => onLabel(suggestion.suggested_cluster_id)}
            disabled={isPending}
          >
            {__('Name Person', 'alt-context')}
          </button>
        )}
        {onReview ? (
          <button
            type="button"
            className="button button-link acx-suggestion-card__review"
            onClick={() => onReview(suggestion.suggested_cluster_id)}
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
  const topSimilarity = Math.max(...suggestions.map((suggestion) => suggestion.representative_similarity));
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
              const identityThumbUrl = suggestion.identity_thumb_url ?? suggestion.identity_media_url;
              return suggestion.identity_media_url && suggestion.identity_bbox ? (
                <FaceThumbnail
                  key={suggestion.id}
                  mediaUrl={suggestion.identity_media_url}
                  bbox={suggestion.identity_bbox}
                  size="sm"
                  alt={__('Candidate face', 'alt-context')}
                  className="acx-suggestion-card__thumb"
                />
              ) : identityThumbUrl ? (
                <Avatar
                  key={suggestion.id}
                  src={identityThumbUrl}
                  size="md"
                  alt={__('Candidate face', 'alt-context')}
                  className="acx-suggestion-card__thumb"
                />
              ) : (
                <span
                  key={suggestion.id}
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
