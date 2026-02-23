import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ClusterIdentity } from '../../api/recognition';
import type { MediaMeta } from '../../api/mediaApi';

export interface IdentityThumbnailProps {
  identity: ClusterIdentity;
  mediaMeta?: MediaMeta;
  size?: number;
  onClick?: () => void;
}

const PADDING_RATIO = 0.15;

export const IdentityThumbnail = ({
  identity,
  mediaMeta,
  size = 96,
  onClick,
}: IdentityThumbnailProps): React.JSX.Element => {
  const [croppedSrc, setCroppedSrc] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (identity.thumb_url) {
      setCroppedSrc(null);
      return;
    }
    if (!mediaMeta?.url) {
      setCroppedSrc(null);
      return;
    }
    let cancelled = false;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = mediaMeta.url;

    const draw = () => {
      if (cancelled) {
        return;
      }

      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');

      if (!ctx) {
        setCroppedSrc(mediaMeta.url);
        return;
      }

      const naturalWidth = img.naturalWidth || img.width;
      const naturalHeight = img.naturalHeight || img.height;
      const originalWidth = mediaMeta.width ?? naturalWidth;
      const originalHeight = mediaMeta.height ?? naturalHeight;
      const scaleX = naturalWidth / originalWidth;
      const scaleY = naturalHeight / originalHeight;

      const scaledX = identity.bbox.x * scaleX;
      const scaledY = identity.bbox.y * scaleY;
      const scaledWidth = identity.bbox.width * scaleX;
      const scaledHeight = identity.bbox.height * scaleY;

      const paddingX = scaledWidth * PADDING_RATIO;
      const paddingY = scaledHeight * PADDING_RATIO;

      const expandedX = Math.max(0, scaledX - paddingX);
      const expandedY = Math.max(0, scaledY - paddingY);
      const expandedWidth = scaledWidth + 2 * paddingX;
      const expandedHeight = scaledHeight + 2 * paddingY;

      const centerX = expandedX + expandedWidth / 2;
      const centerY = expandedY + expandedHeight / 2;

      const squareSize = Math.max(expandedWidth, expandedHeight);
      const maxSx = Math.max(0, naturalWidth - squareSize);
      const maxSy = Math.max(0, naturalHeight - squareSize);

      const sx = clamp(centerX - squareSize / 2, 0, maxSx);
      const sy = clamp(centerY - squareSize / 2, 0, maxSy);
      const sWidth = Math.min(squareSize, naturalWidth - sx);
      const sHeight = Math.min(squareSize, naturalHeight - sy);

      const scale = size / Math.max(sWidth, sHeight);
      const destWidth = sWidth * scale;
      const destHeight = sHeight * scale;

      const dx = (size - destWidth) / 2;
      const dy = (size - destHeight) / 2;

      ctx.clearRect(0, 0, size, size);
      ctx.drawImage(img, sx, sy, sWidth, sHeight, dx, dy, destWidth, destHeight);
      setCroppedSrc(canvas.toDataURL('image/jpeg', 0.92));
    };

    img.onload = draw;
    img.onerror = () => setCroppedSrc(mediaMeta.url);

    return () => {
      cancelled = true;
    };
  }, [identity.thumb_url, identity.bbox, mediaMeta?.height, mediaMeta?.url, mediaMeta?.width, size]);

  const resolvedSrc = identity.thumb_url ?? croppedSrc ?? mediaMeta?.url ?? null;

  if (!resolvedSrc) {
    return <div className="acx-cluster-card__face--placeholder" aria-hidden="true" />;
  }

  return (
    <img
      src={resolvedSrc}
      alt={sprintf(__('Identity from media %d', 'alt-context'), identity.media_id)}
      width={size}
      height={size}
      className="acx-cluster-card__thumb"
      onClick={onClick}
      loading="lazy"
    />
  );
};

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(value, max));
