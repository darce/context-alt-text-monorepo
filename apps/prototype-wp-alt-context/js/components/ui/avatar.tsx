/**
 * Avatar — Radix UI wrapper for accessible, consistently-sized avatar display.
 *
 * Use for pre-cropped thumbnail URLs (e.g. representative_thumb_path).
 * For face bounding-box crops from full images, use FaceThumbnail instead.
 */

import * as React from 'react';
import * as AvatarPrimitive from '@radix-ui/react-avatar';
import { __ } from '@wordpress/i18n';

export type AvatarSize = 'sm' | 'md' | 'lg';

const sizeMap: Record<AvatarSize, number> = {
  sm: 32,
  md: 48,
  lg: 64,
};

export interface AvatarProps {
  /** Pre-cropped thumbnail URL */
  src: string;
  /** Accessible alt text */
  alt?: string;
  /** Size variant */
  size?: AvatarSize;
  /** Optional pixel size override */
  sizePx?: number;
  /** Shape — circle (default) or square */
  shape?: 'circle' | 'square';
  /** Additional CSS class on the root element */
  className?: string;
}

export const Avatar = ({
  src,
  alt = __('Face thumbnail', 'alt-context'),
  size = 'md',
  sizePx,
  shape = 'circle',
  className = '',
}: AvatarProps): React.JSX.Element => {
  const displaySize = sizePx ?? sizeMap[size];
  const baseClass = 'acx-avatar';
  const classes = [baseClass, `${baseClass}--${size}`, shape === 'square' ? `${baseClass}--square` : '', className]
    .filter(Boolean)
    .join(' ');

  return (
    <AvatarPrimitive.Root className={classes} style={{ width: displaySize, height: displaySize }}>
      <AvatarPrimitive.Image className={`${baseClass}__image`} src={src} alt={alt} />
      <AvatarPrimitive.Fallback className={`${baseClass}__fallback`} delayMs={300}>
        <span className="screen-reader-text">{__('Image unavailable', 'alt-context')}</span>
      </AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  );
};
