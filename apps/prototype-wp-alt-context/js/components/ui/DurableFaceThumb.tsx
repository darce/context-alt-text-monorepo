/**
 * Durable face thumbnail: dedicated blob first, then attachment+bbox crop.
 */

import * as React from 'react';
import { __ } from '@wordpress/i18n';

import { Avatar, type AvatarSize } from './avatar';
import { FaceThumbnail } from './FaceThumbnail';
import {
  AVATAR_STATE,
  REPRESENTATIVE_IMAGE_UNAVAILABLE,
  type FaceThumbSource,
} from './faceThumbDisplay';
import { useDurableFaceThumb } from './useDurableFaceThumb';

export interface DurableFaceThumbProps {
  source: FaceThumbSource;
  alt?: string;
  size?: AvatarSize;
  sizePx?: number;
  shape?: 'circle' | 'square';
  className?: string;
  loading?: 'lazy' | 'eager';
}

export const DurableFaceThumb = ({
  source,
  alt = __('Detected face', 'alt-context'),
  size = 'md',
  sizePx,
  shape = 'circle',
  className = '',
  loading,
}: DurableFaceThumbProps): React.JSX.Element => {
  const { display, onBlobLoad, onBlobError, onCropLoad, onCropError } = useDurableFaceThumb(source);
  const baseClass = 'acx-durable-face-thumb';
  const stateClass = display.state !== AVATAR_STATE.real ? `${baseClass}--${display.state}` : '';
  const errorClass = display.isLoudError ? `${baseClass}--error` : '';
  const classes = [baseClass, stateClass, errorClass, className].filter(Boolean).join(' ');

  if (display.state === AVATAR_STATE.missing) {
    return (
      <span
        className={classes}
        data-avatar-state={AVATAR_STATE.missing}
        role="img"
        aria-label={__(REPRESENTATIVE_IMAGE_UNAVAILABLE, 'alt-context')}
      >
        <span className={`${baseClass}__fallback-label`}>{__('No image', 'alt-context')}</span>
      </span>
    );
  }

  if (display.isLoudError) {
    return (
      <span
        className={classes}
        data-avatar-state={AVATAR_STATE.error}
        role="img"
        aria-label={__('Image failed to load', 'alt-context')}
      />
    );
  }

  if (display.mode === 'crop' && display.crop) {
    return (
      <span className={classes} data-avatar-state={display.state}>
        <FaceThumbnail
          mediaUrl={display.crop.mediaUrl}
          bbox={display.crop.bbox}
          size={size}
          sizePx={sizePx}
          shape={shape}
          alt={alt}
          loading={loading}
          className={`${baseClass}__crop`}
          onLoad={onCropLoad}
          onError={onCropError}
        />
      </span>
    );
  }

  if (display.mode === 'avatar' && display.src) {
    return (
      <span className={classes} data-avatar-state={display.state}>
        <Avatar
          src={display.src}
          alt={alt}
          size={size}
          sizePx={sizePx}
          shape={shape}
          state={display.state}
          className={`${baseClass}__avatar`}
          onLoad={onBlobLoad}
          onError={onBlobError}
        />
      </span>
    );
  }

  return (
    <span
      className={classes}
      data-avatar-state={display.state}
      role="img"
      aria-label={__(REPRESENTATIVE_IMAGE_UNAVAILABLE, 'alt-context')}
    />
  );
};
