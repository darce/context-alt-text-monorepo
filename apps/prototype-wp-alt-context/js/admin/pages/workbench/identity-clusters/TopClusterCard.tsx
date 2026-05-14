/**
 * Individual cluster card with face thumbnails and label actions.
 */

import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import { FaceThumbnail } from '../../../../components/ui/FaceThumbnail';
import { Avatar } from '../../../../components/ui/avatar';
import type { BoundingBox } from '../../../api/recognition/types/identity';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';

const resolveRepresentativeThumbUrl = (
  representative: TopUnlabeledCluster['representatives'][number],
): string | null => {
  const rawUrl = representative.thumb_url ?? null;
  if (typeof rawUrl !== 'string' || rawUrl.trim() === '') {
    return null;
  }
  return rawUrl;
};

const resolveRepresentativeCrop = (
  representative: TopUnlabeledCluster['representatives'][number],
): { mediaUrl: string; bbox: BoundingBox } | null => {
  const mediaUrl = representative.media_url;
  const bbox = representative.bbox;
  if (typeof mediaUrl !== 'string' || mediaUrl.trim() === '' || !bbox) {
    return null;
  }

  const x = Number(bbox.x);
  const y = Number(bbox.y);
  const width = Number(bbox.width);
  const height = Number(bbox.height);

  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(width) || !Number.isFinite(height)) {
    return null;
  }
  if (width <= 0 || height <= 0) {
    return null;
  }

  return {
    mediaUrl,
    bbox: { x, y, width, height },
  };
};

const getMostRepresentative = (
  representatives: TopUnlabeledCluster['representatives'],
): TopUnlabeledCluster['representatives'][number] | null => {
  if (!Array.isArray(representatives) || representatives.length === 0) {
    return null;
  }

  return representatives.reduce((best, current) => {
    if (!best) {
      return current;
    }
    if (current.is_pinned && !best.is_pinned) {
      return current;
    }
    return best;
  }, representatives[0] ?? null);
};

interface TopClusterCardProps {
  cluster: TopUnlabeledCluster;
  onLabel: (clusterId: string) => void;
  onReview?: (clusterId: string) => void;
  isReadOnly?: boolean;
  onConfirmSuggestedLabel?: (
    clusterId: string,
    suggestedLabel: string,
    suggestedTargetClusterId?: string | null,
  ) => void;
  onDismiss?: (clusterId: string) => void;
  isConfirming?: boolean;
  isDismissing?: boolean;
}

export const TopClusterCard = ({
  cluster,
  onLabel,
  onReview,
  isReadOnly = false,
  onConfirmSuggestedLabel,
  onDismiss,
  isConfirming = false,
  isDismissing = false,
}: TopClusterCardProps): React.JSX.Element => {
  const gridSizePx = 80;
  const gapPx = 2;
  const maxThumbs = 4;
  const faceCount = cluster.identity_count;
  const suggestedLabel =
    typeof cluster.suggested_label === 'string' && cluster.suggested_label.trim() !== ''
      ? cluster.suggested_label.trim()
      : null;
  const title = suggestedLabel
    ? `${__('Is this', 'alt-context')} ${suggestedLabel}?`
    : __('Name this person', 'alt-context');
  const representative = getMostRepresentative(cluster.representatives ?? []);
  const reps = suggestedLabel
    ? representative
      ? [representative]
      : []
    : (cluster.representatives ?? []).slice(0, maxThumbs);
  const columnCount = reps.length <= 1 ? 1 : 2;
  const cellSize = (gridSizePx - gapPx * (columnCount - 1)) / columnCount;
  const gridClassName =
    columnCount === 1 ? 'acx-top-cluster-card__grid acx-top-cluster-card__grid--single' : 'acx-top-cluster-card__grid';
  const isBusy = isDismissing || isConfirming;
  const unavailableImageLabel = __('Representative image unavailable', 'alt-context');

  const handleConfirmSuggestedLabelClick = () => {
    if (!suggestedLabel || !onConfirmSuggestedLabel) {
      return;
    }
    onConfirmSuggestedLabel(cluster.id, suggestedLabel, cluster.suggested_target_cluster_id);
  };

  const handleRejectSuggestedLabelClick = () => {
    if (onDismiss) {
      onDismiss(cluster.id);
      return;
    }
    onLabel(cluster.id);
  };

  return (
    <div className="acx-top-cluster-card">
      <div className="acx-top-cluster-card__faces">
        {reps.length > 0 ? (
          <div className={gridClassName}>
            {reps.map((rep) => {
              const cropData = resolveRepresentativeCrop(rep);
              const thumbUrl = resolveRepresentativeThumbUrl(rep);
              return (
                <div key={rep.id} className="acx-top-cluster-card__thumb acx-top-cluster-card__thumb--frame">
                  {thumbUrl ? (
                    <Avatar
                      src={thumbUrl}
                      sizePx={cellSize}
                      shape="square"
                      alt=""
                      className="acx-top-cluster-card__thumb-image"
                    />
                  ) : cropData ? (
                    <FaceThumbnail
                      mediaUrl={cropData.mediaUrl}
                      bbox={cropData.bbox}
                      sizePx={cellSize}
                      shape="square"
                      alt=""
                      className="acx-top-cluster-card__thumb-image"
                    />
                  ) : (
                    <span
                      className="acx-top-cluster-card__thumb-image acx-top-cluster-card__thumb-image--unavailable"
                      role="img"
                      aria-label={unavailableImageLabel}
                    >
                      <span className="acx-top-cluster-card__thumb-fallback-label">{__('No image', 'alt-context')}</span>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <span className="acx-top-cluster-card__thumb acx-top-cluster-card__thumb--placeholder" />
        )}
      </div>

      <div className="acx-top-cluster-card__content">
        <p className="acx-top-cluster-card__title">
          {suggestedLabel ? (
            <strong>{title}</strong>
          ) : !isReadOnly ? (
            <button
              type="button"
              className="acx-top-cluster-card__title-action acx-identity-cluster__label acx-identity-cluster__label--action"
              onClick={() => onLabel(cluster.id)}
              disabled={isBusy}
              title={__('Open labeling form', 'alt-context')}
            >
              {title}
            </button>
          ) : (
            <span>{title}</span>
          )}
        </p>
        <p className="acx-top-cluster-card__meta">
          {sprintf(_n('%d face in cluster', '%d faces in cluster', faceCount, 'alt-context'), faceCount)}
        </p>
      </div>

      <div className="acx-top-cluster-card__actions">
        {!isReadOnly && suggestedLabel && onConfirmSuggestedLabel ? (
          <>
            <button
              type="button"
              className="button button-primary acx-top-cluster-card__confirm-btn"
              onClick={handleConfirmSuggestedLabelClick}
              disabled={isBusy}
              title={__('Confirm suggested name', 'alt-context')}
            >
              {__('Yes', 'alt-context')}
            </button>
            <button
              type="button"
              className="button acx-top-cluster-card__reject-btn"
              onClick={handleRejectSuggestedLabelClick}
              disabled={isBusy}
              title={__('Reject suggestion for now', 'alt-context')}
            >
              {__('No', 'alt-context')}
            </button>
          </>
        ) : null}
        {!isReadOnly && onReview && (
          <button
            type="button"
            className="button acx-top-cluster-card__review-btn"
            onClick={() => onReview(cluster.id)}
            disabled={isBusy}
          >
            {__('Review', 'alt-context')}
          </button>
        )}
        {!isReadOnly && onDismiss && (
          <button
            type="button"
            className="button button-link acx-top-cluster-card__skip-btn"
            onClick={() => onDismiss(cluster.id)}
            disabled={isBusy}
            title={__('Skip this cluster for now', 'alt-context')}
          >
            {__('Skip', 'alt-context')}
          </button>
        )}
      </div>
    </div>
  );
};
