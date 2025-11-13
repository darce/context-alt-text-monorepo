import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ClusterFace } from '../../api/recognitionApi';
import type { MediaMeta } from './utils/mediaMeta';

export type FaceThumbnailProps = {
  face: ClusterFace;
  mediaMeta?: MediaMeta;
  size?: number;
  onClick?: () => void;
};

const PADDING_RATIO = 0.05; // 5% padding around bbox for expression context

export const FaceThumbnail = ({ face, mediaMeta, size = 96, onClick }: FaceThumbnailProps): React.JSX.Element => {
  const [croppedSrc, setCroppedSrc] = React.useState<string | null>(null);

  // Canvas-based cropping with improved logic
  React.useEffect(() => {
    if (!mediaMeta?.url) {
      setCroppedSrc(null);
      return;
    }

    let cancelled = false;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = mediaMeta.url;

    const draw = () => {
      if (cancelled) return;

      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');

      if (!ctx) {
        setCroppedSrc(mediaMeta.url);
        return;
      }

      const { x, y, width, height } = face.bbox;

      // Calculate padding (5% of bbox dimensions)
      const paddingX = width * PADDING_RATIO;
      const paddingY = height * PADDING_RATIO;

      // Expand bbox with padding
      const expandedX = Math.max(0, x - paddingX);
      const expandedY = Math.max(0, y - paddingY);
      const expandedWidth = width + 2 * paddingX;
      const expandedHeight = height + 2 * paddingY;

      // Calculate center point
      const centerX = expandedX + expandedWidth / 2;
      const centerY = expandedY + expandedHeight / 2;

      // Make it square by taking the larger dimension
      const squareSize = Math.max(expandedWidth, expandedHeight);

      // Calculate source crop region (centered square)
      const sx = clamp(centerX - squareSize / 2, 0, img.width - squareSize);
      const sy = clamp(centerY - squareSize / 2, 0, img.height - squareSize);
      const sWidth = Math.min(squareSize, img.width - sx);
      const sHeight = Math.min(squareSize, img.height - sy);

      // Scale to fit canvas (fill the entire canvas)
      const scale = size / Math.max(sWidth, sHeight);
      const destWidth = sWidth * scale;
      const destHeight = sHeight * scale;

      // Center on canvas
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
  }, [face.bbox, mediaMeta?.url, size]);

  if (!mediaMeta?.url) {
    return <div className="acx-cluster-card__face--placeholder" aria-hidden="true" />;
  }

  // Render canvas-cropped image
  return (
    <img
      src={croppedSrc ?? mediaMeta.url}
      alt={sprintf(__('Face from media %d', 'alt-context'), face.media_id)}
      width={size}
      height={size}
      className="acx-cluster-card__thumb"
      onClick={onClick}
      loading="lazy"
    />
  );
};

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(value, max));
