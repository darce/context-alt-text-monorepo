/**
 * Individual cluster card with face thumbnails and label actions.
 */

import React from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';

import { Avatar } from '../../../../components/ui/avatar';
import { DurableFaceThumb } from '../../../../components/ui/DurableFaceThumb';
import type { FaceThumbSource } from '../../../../components/ui/faceThumbDisplay';
import type { BoundingBox } from '../../../api/recognition/types/identity';
import type { TopUnlabeledCluster } from '../../../api/recognition/types/cluster';
import { REPRESENTATIVE_VOCABULARY } from './representativeVocabulary';
import { ReviewCardGroupShell } from './reviewCardGroupAccname';
import { isHumanLabeledTarget } from './suggestionProjection';

/**
 * Hop order (blob → crop → uncropped → missing) lives in resolveFaceThumbDisplay
 * alone. This card only supplies the source; it must not re-derive the chain
 * inline, or the copy drifts from the canonical one (NAME-05, REF-26).
 */
const toFaceThumbSource = (representative: TopUnlabeledCluster['representatives'][number]): FaceThumbSource => {
  const bbox = representative.bbox;
  const coercedBbox: BoundingBox | null = bbox
    ? {
        x: Number(bbox.x),
        y: Number(bbox.y),
        width: Number(bbox.width),
        height: Number(bbox.height),
      }
    : null;

  return {
    thumbUrl: representative.thumb_url ?? null,
    attachmentUrl: representative.attachment_url ?? null,
    mediaUrl: representative.media_url ?? null,
    bbox: coercedBbox,
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
  /**
   * BR-41: 1-based queue position. When BOTH `queuePosition` and `queueTotal` are
   * valid integers >= 1, ordinal text folds into the group accname.
   */
  queuePosition?: number;
  /** BR-41: filtered queue length paired with `queuePosition`. */
  queueTotal?: number;
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
  queuePosition,
  queueTotal,
}: TopClusterCardProps): React.JSX.Element => {
  const gridSizePx = 80;
  const gapPx = 2;
  const maxThumbs = 4;
  const faceCount = cluster.identity_count;
  const trimmedSuggested = typeof cluster.suggested_label === 'string' ? cluster.suggested_label.trim() : '';
  const suggestedLabel = trimmedSuggested !== '' && isHumanLabeledTarget(trimmedSuggested) ? trimmedSuggested : null;
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
  const rowCount = reps.length <= 2 ? 1 : 2;
  const cellSize = (gridSizePx - gapPx * (columnCount - 1)) / columnCount;
  // UXW2-2 (B5): a rep without a usable image renders the missing state WITH
  // its visible label at every cell size — never a blank tile (PRINCIPLES §11).
  const hideMissingLabel = false;
  // UXW2-2 (B5): the count describes rendered faces; members without a tile
  // fold into "+N more" (ClusterPreview +N pattern) instead of inflating the count.
  const renderedFaceCount = reps.length;
  const moreFaceCount = Math.max(0, faceCount - renderedFaceCount);
  const gridHeight = cellSize * rowCount + gapPx * (rowCount - 1);
  const gridClassName =
    columnCount === 1 ? 'acx-top-cluster-card__grid acx-top-cluster-card__grid--single' : 'acx-top-cluster-card__grid';
  const gridStyle: React.CSSProperties = {
    height: gridHeight,
    gridTemplateColumns: `repeat(${columnCount}, 1fr)`,
    gridTemplateRows: `repeat(${rowCount}, 1fr)`,
  };
  const isBusy = isDismissing || isConfirming;
  const faceAltText = __('Face to label', 'alt-context');
  const missingRepresentativeLabel = REPRESENTATIVE_VOCABULARY.imageUnavailable;
  const groupLabelId = `acx-cluster-pos-${cluster.id}`;

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
    <ReviewCardGroupShell
      kind="cluster"
      labelId={groupLabelId}
      queuePosition={queuePosition}
      queueTotal={queueTotal}
      className="acx-top-cluster-card"
      data-testid="acx-review-card"
      data-review-kind="cluster"
    >
      <div className="acx-top-cluster-card__faces">
        {reps.length > 0 ? (
          <div className={gridClassName} style={gridStyle}>
            {reps.map((rep) => (
              <div key={rep.id} className="acx-top-cluster-card__thumb acx-top-cluster-card__thumb--frame">
                <DurableFaceThumb
                  source={toFaceThumbSource(rep)}
                  sizePx={cellSize}
                  shape="square"
                  alt={faceAltText}
                  missingLabel={missingRepresentativeLabel}
                  hideMissingLabel={hideMissingLabel}
                  className="acx-top-cluster-card__thumb-image"
                />
              </div>
            ))}
          </div>
        ) : (
          <Avatar
            sizePx={gridSizePx}
            shape="square"
            missingLabel={missingRepresentativeLabel}
            className="acx-top-cluster-card__thumb"
          />
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
          {sprintf(
            _n('%d face in cluster', '%d faces in cluster', renderedFaceCount, 'alt-context'),
            renderedFaceCount,
          )}
          {moreFaceCount > 0
            ? ` ${sprintf(
                /* translators: %d: faces not shown as thumbnails */
                __('(+%d more)', 'alt-context'),
                moreFaceCount,
              )}`
            : ''}
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
        {/* BR-31: Review (members) stays available in read-only review-queue mode;
            isReadOnly only demotes LABEL / confirm / dismiss. */}
        {onReview && (
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
    </ReviewCardGroupShell>
  );
};
