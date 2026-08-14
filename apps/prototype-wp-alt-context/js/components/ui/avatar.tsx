/**
 * Avatar — Radix UI wrapper for accessible, consistently-sized avatar display.
 *
 * Use for pre-cropped thumbnail URLs (e.g. representative_thumb_path).
 * For face bounding-box crops from full images, use FaceThumbnail instead.
 */

import * as React from 'react';
import * as AvatarPrimitive from '@radix-ui/react-avatar';
import { __ } from '@wordpress/i18n';

import { AVATAR_STATE, type AvatarState } from './faceThumbDisplay';

export type AvatarSize = 'sm' | 'md' | 'lg';
export { AVATAR_STATE, type AvatarState };

const sizeMap: Record<AvatarSize, number> = {
  sm: 32,
  md: 48,
  lg: 64,
};

export interface AvatarProps {
  /** Pre-cropped thumbnail URL. Null/empty is an explicit missing state. */
  src?: string | null;
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
  /** Override the derived data-avatar-state (durable-thumb fallback). */
  state?: AvatarState;
  onLoad?: () => void;
  onError?: () => void;
}

export const Avatar = ({
  src,
  alt = __('Face thumbnail', 'alt-context'),
  size = 'md',
  sizePx,
  shape = 'circle',
  className = '',
  state: stateOverride,
  onLoad,
  onError,
}: AvatarProps): React.JSX.Element => {
  const displaySize = sizePx ?? sizeMap[size];
  const trimmedSrc = typeof src === 'string' && src.trim() !== '' ? src : null;
  const [loadState, setLoadState] = React.useState<AvatarState>(
    trimmedSrc ? AVATAR_STATE.loading : AVATAR_STATE.missing,
  );

  React.useEffect(() => {
    setLoadState(trimmedSrc ? AVATAR_STATE.loading : AVATAR_STATE.missing);
  }, [trimmedSrc]);

  const derivedState: AvatarState = !trimmedSrc ? AVATAR_STATE.missing : loadState;
  const avatarState = stateOverride ?? derivedState;
  const baseClass = 'acx-avatar';
  const stateClass = avatarState !== AVATAR_STATE.real ? `${baseClass}--${avatarState}` : '';
  const classes = [
    baseClass,
    `${baseClass}--${size}`,
    shape === 'square' ? `${baseClass}--square` : '',
    stateClass,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const handleLoadingStatusChange = React.useCallback(
    (status: 'idle' | 'loading' | 'loaded' | 'error') => {
      if (status === 'loaded') {
        setLoadState(AVATAR_STATE.real);
        onLoad?.();
        return;
      }
      if (status === 'error') {
        setLoadState(AVATAR_STATE.error);
        onError?.();
      }
    },
    [onError, onLoad],
  );

  const handleNativeLoad = React.useCallback(() => {
    setLoadState(AVATAR_STATE.real);
    onLoad?.();
  }, [onLoad]);

  const handleNativeError = React.useCallback(() => {
    setLoadState(AVATAR_STATE.error);
    onError?.();
  }, [onError]);

  if (!trimmedSrc || avatarState === AVATAR_STATE.missing) {
    return (
      <AvatarPrimitive.Root
        className={classes}
        style={{ width: displaySize, height: displaySize }}
        data-avatar-state={AVATAR_STATE.missing}
      >
        <AvatarPrimitive.Fallback className={`${baseClass}__fallback`} delayMs={0}>
          <span className="screen-reader-text">{__('Representative image unavailable', 'alt-context')}</span>
        </AvatarPrimitive.Fallback>
      </AvatarPrimitive.Root>
    );
  }

  return (
    <AvatarPrimitive.Root
      className={classes}
      style={{ width: displaySize, height: displaySize }}
      data-avatar-state={avatarState}
    >
      <AvatarPrimitive.Image
        className={`${baseClass}__image`}
        src={trimmedSrc}
        alt={alt}
        onLoadingStatusChange={handleLoadingStatusChange}
        onLoad={handleNativeLoad}
        onError={handleNativeError}
      />
      <AvatarPrimitive.Fallback className={`${baseClass}__fallback`} delayMs={300}>
        <span className="screen-reader-text">
          {avatarState === AVATAR_STATE.error
            ? __('Image failed to load', 'alt-context')
            : __('Image unavailable', 'alt-context')}
        </span>
      </AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  );
};
