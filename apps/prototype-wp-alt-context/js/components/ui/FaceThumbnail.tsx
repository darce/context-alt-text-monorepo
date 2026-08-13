/**
 * FaceThumbnail - CSS-based face cropping from source image.
 *
 * Uses CSS transform to crop and scale a face region from a full image,
 * avoiding the need for server-side thumbnail generation.
 *
 * @see docs/tasks/4.0/4.2.5/OFFLINE_FIRST_THUMBNAILS.md
 */

import * as React from 'react';
import { __ } from '@wordpress/i18n';

import type { BoundingBox } from '../../admin/api/recognition/types/identity';
import { cropTransformFor } from './faceGeometry';

export type FaceThumbnailSize = 'sm' | 'md' | 'lg';

const sizeMap: Record<FaceThumbnailSize, number> = {
  sm: 32,
  md: 48,
  lg: 64,
};

export interface FaceThumbnailProps {
  /** URL of the source image (WordPress media URL) */
  mediaUrl: string;
  /** Bounding box coordinates of the face in the source image */
  bbox: BoundingBox;
  /** Display size variant */
  size?: FaceThumbnailSize;
  /** Optional explicit pixel size override */
  sizePx?: number;
  /** Thumbnail shape. */
  shape?: 'circle' | 'square';
  /** Accessible alt text */
  alt?: string;
  /** Optional native img loading hint; omitted when unset */
  loading?: 'lazy' | 'eager';
  /** Additional CSS class */
  className?: string;
}

type LoadingState = 'loading' | 'loaded' | 'error';

/**
 * Renders a face thumbnail by CSS-cropping a region from the source image.
 *
 * Uses GPU-accelerated CSS transforms for performance.
 * Works offline with browser-cached images.
 */
export const FaceThumbnail = React.forwardRef<HTMLDivElement, FaceThumbnailProps>(
  (
    {
      mediaUrl,
      bbox,
      size = 'md',
      sizePx,
      shape = 'circle',
      alt = __('Detected face', 'alt-context'),
      loading,
      className = '',
    },
    ref,
  ) => {
    const [loadState, setLoadState] = React.useState<LoadingState>('loading');
    const imgRef = React.useRef<HTMLImageElement | null>(null);
    const displaySize = sizePx ?? sizeMap[size];
    const borderRadius = shape === 'square' ? '0' : '50%';
    const { scale, offsetX, offsetY } = cropTransformFor(bbox, displaySize);

    const handleLoad = React.useCallback(() => {
      setLoadState('loaded');
    }, []);

    const handleError = React.useCallback(() => {
      setLoadState('error');
    }, []);

    React.useEffect(() => {
      setLoadState('loading');
    }, [mediaUrl]);

    React.useEffect(() => {
      const img = imgRef.current;
      if (!img || loadState !== 'loading') {
        return;
      }

      if (!img.complete) {
        return;
      }

      setLoadState(img.naturalWidth > 0 ? 'loaded' : 'error');
    }, [loadState, mediaUrl]);

    const baseClass = 'acx-face-thumbnail';
    const sizeClass = `${baseClass}--${size}`;
    const stateClass = loadState !== 'loaded' ? `${baseClass}--${loadState}` : '';
    const classes = [baseClass, sizeClass, stateClass, className].filter(Boolean).join(' ');

    // Show placeholder on error
    if (loadState === 'error') {
      return (
        <div
          ref={ref}
          className={classes}
          role="img"
          aria-label={__('Face image unavailable', 'alt-context')}
          style={{ width: displaySize, height: displaySize }}
        />
      );
    }

    return (
      <div
        ref={ref}
        className={classes}
        style={{
          width: displaySize,
          height: displaySize,
          overflow: 'hidden',
          borderRadius,
          position: 'relative',
        }}
      >
        {loadState === 'loading' && (
          <span
            className={`${baseClass}__placeholder`}
            aria-hidden="true"
            style={{
              position: 'absolute',
              inset: 0,
              backgroundColor: 'var(--acx-color-gray-200, #e5e7eb)',
              borderRadius,
            }}
          />
        )}
        <img
          ref={imgRef}
          src={mediaUrl}
          alt={alt}
          loading={loading}
          onLoad={handleLoad}
          onError={handleError}
          style={{
            // Position the image so the bbox is centered in the container
            transform: `translate(${offsetX - bbox.x * scale}px, ${offsetY - bbox.y * scale}px) scale(${scale})`,
            transformOrigin: 'top left',
            maxWidth: 'none',
            // Hide while loading to prevent flash
            opacity: loadState === 'loaded' ? 1 : 0,
            transition: 'opacity 150ms ease-in',
          }}
        />
      </div>
    );
  },
);

FaceThumbnail.displayName = 'FaceThumbnail';
