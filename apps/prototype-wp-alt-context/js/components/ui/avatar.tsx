/**
 * Avatar — Radix UI wrapper for accessible, consistently-sized avatar display.
 *
 * Use for pre-cropped thumbnail URLs (e.g. representative_thumb_path).
 * For face bounding-box crops from full images, use FaceThumbnail instead.
 *
 * Four-state contract (B.4): loading / real / data-missing / error.
 * Missing is expected and quiet; error is a real fault. Do not collapse them.
 */

import * as React from 'react';
import * as AvatarPrimitive from '@radix-ui/react-avatar';
import { AlertTriangle, ImageOff } from 'lucide-react';
import { __ } from '@wordpress/i18n';

import { AVATAR_STATE, type AvatarState } from './faceThumbDisplay';

export { AVATAR_STATE, type AvatarState };

export const AVATAR_STATES = AVATAR_STATE;

export type AvatarSize = 'sm' | 'md' | 'lg';

export type ImageLoadingStatus = 'idle' | 'loading' | 'loaded' | 'error';

const sizeMap: Record<AvatarSize, number> = {
  sm: 32,
  md: 48,
  lg: 64,
};

export interface AvatarProps {
  /** Pre-cropped thumbnail URL. Omit or pass empty for the data-missing branch. */
  src?: string;
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
  /** Accessible name for the data-missing branch (`aria-label`). Not visible copy. */
  missingLabel?: string;
  /** Visible missing-state micro-copy. Defaults to the short "No image" label. */
  missingText?: string;
  /** Hide the visible missing-label (keep aria-label). Opt in for chips too small for the copy. */
  hideMissingLabel?: boolean;
  /** Externally-owned state override. When omitted the component derives its own. */
  state?: AvatarState;
  onLoad?: () => void;
  onError?: () => void;
}

function hasAvatarSrc(src: string | undefined): src is string {
  return typeof src === 'string' && src.trim() !== '';
}

function resolveAvatarState(src: string | undefined, loadStatus: ImageLoadingStatus): AvatarState {
  if (!hasAvatarSrc(src)) {
    return AVATAR_STATE.missing;
  }
  if (loadStatus === 'loaded') {
    return AVATAR_STATES.real;
  }
  if (loadStatus === 'error') {
    return AVATAR_STATES.error;
  }
  return AVATAR_STATES.loading;
}

/**
 * Swap-frame resolver: a new src must not inherit the previous identity's
 * loaded/error status for even one render.
 */
export function resolveAvatarRenderState(
  src: string | undefined,
  previousSrc: string | undefined,
  loadStatus: ImageLoadingStatus,
): AvatarState {
  const effectiveStatus = src !== previousSrc ? 'idle' : loadStatus;
  return resolveAvatarState(src, effectiveStatus);
}

export const Avatar = ({
  src,
  alt = __('Face thumbnail', 'alt-context'),
  size = 'md',
  sizePx,
  shape = 'circle',
  className = '',
  missingLabel = __('No image', 'alt-context'),
  missingText = __('No image', 'alt-context'),
  hideMissingLabel = false,
  state: stateOverride,
  onLoad,
  onError,
}: AvatarProps): React.JSX.Element => {
  const displaySize = sizePx ?? sizeMap[size];
  const iconSize = Math.max(12, Math.round(displaySize * 0.35));
  const [loadStatus, setLoadStatus] = React.useState<ImageLoadingStatus>('idle');
  const [previousSrc, setPreviousSrc] = React.useState(src);
  const onLoadRef = React.useRef(onLoad);
  const onErrorRef = React.useRef(onError);
  React.useEffect(() => {
    onLoadRef.current = onLoad;
  }, [onLoad]);
  React.useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);
  React.useEffect(() => {
    if (loadStatus === 'loaded') {
      onLoadRef.current?.();
    } else if (loadStatus === 'error') {
      onErrorRef.current?.();
    }
  }, [loadStatus]);
  if (src !== previousSrc) {
    setPreviousSrc(src);
    setLoadStatus('idle');
  }
  const derivedState = resolveAvatarRenderState(src, previousSrc, loadStatus);
  const state = stateOverride ?? derivedState;
  const baseClass = 'acx-avatar';
  const classes = [
    baseClass,
    `${baseClass}--${size}`,
    shape === 'square' ? `${baseClass}--square` : '',
    hideMissingLabel ? `${baseClass}--hide-missing-label` : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  const rootStyle = { width: displaySize, height: displaySize };

  if (state === AVATAR_STATE.missing) {
    return (
      <span
        className={classes}
        data-avatar-state={AVATAR_STATE.missing}
        role="img"
        aria-label={missingLabel}
        style={rootStyle}
      >
        <ImageOff className={`${baseClass}__missing-icon`} size={iconSize} aria-hidden="true" />
        <span className={`${baseClass}__missing-label`}>{missingText}</span>
      </span>
    );
  }

  return (
    <AvatarPrimitive.Root className={classes} data-avatar-state={state} style={rootStyle}>
      <AvatarPrimitive.Image
        className={`${baseClass}__image`}
        src={src}
        alt={alt}
        onLoadingStatusChange={setLoadStatus}
      />
      {state === AVATAR_STATES.loading ? <span className={`${baseClass}__skeleton`} aria-hidden="true" /> : null}
      {state === AVATAR_STATES.error ? (
        <span className={`${baseClass}__error`}>
          <AlertTriangle className={`${baseClass}__warning-icon`} size={iconSize} aria-hidden="true" />
          <ImageOff className={`${baseClass}__broken-icon`} size={iconSize} aria-hidden="true" />
          <span className="screen-reader-text">{__('Image failed to load', 'alt-context')}</span>
        </span>
      ) : null}
    </AvatarPrimitive.Root>
  );
};
