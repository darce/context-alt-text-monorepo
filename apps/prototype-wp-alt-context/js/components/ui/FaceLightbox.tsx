/**
 * Shared media+bbox lightbox primitive (promoted from ReviewCardLightbox).
 * Shows source media full-size with the face bbox rect highlighted.
 * Dialog only (Esc/close); no routing, no new endpoint.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from './dialog';
import type { BoundingBox } from '../../admin/api/recognition/types/identity';

export interface FaceLightboxProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mediaUrl: string;
  bbox: BoundingBox;
  label?: string;
}

/** @deprecated Prefer FaceLightboxProps; kept for ReviewCardLightbox shim consumers. */
export type ReviewCardLightboxProps = FaceLightboxProps;

export const FaceLightbox = ({
  open,
  onOpenChange,
  mediaUrl,
  bbox,
  label,
}: FaceLightboxProps): React.JSX.Element => {
  const frameRef = React.useRef<HTMLDivElement>(null);
  const [naturalSize, setNaturalSize] = React.useState<{ w: number; h: number } | null>(null);
  const [frameSize, setFrameSize] = React.useState<{ w: number; h: number } | null>(null);

  React.useEffect(() => {
    if (!open) {
      setNaturalSize(null);
      setFrameSize(null);
    }
  }, [open, mediaUrl]);

  React.useEffect(() => {
    if (!open || !frameRef.current) {
      return;
    }
    const el = frameRef.current;
    const update = (): void => {
      setFrameSize({ w: el.clientWidth, h: el.clientHeight });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [open, naturalSize]);

  const handleLoad = (event: React.SyntheticEvent<HTMLImageElement>): void => {
    const img = event.currentTarget;
    setNaturalSize({ w: img.naturalWidth, h: img.naturalHeight });
  };

  let highlightStyle: React.CSSProperties | undefined;
  if (naturalSize && frameSize && naturalSize.w > 0 && naturalSize.h > 0) {
    const scale = Math.min(frameSize.w / naturalSize.w, frameSize.h / naturalSize.h);
    const displayW = naturalSize.w * scale;
    const displayH = naturalSize.h * scale;
    const offsetX = (frameSize.w - displayW) / 2;
    const offsetY = (frameSize.h - displayH) / 2;
    highlightStyle = {
      left: offsetX + bbox.x * scale,
      top: offsetY + bbox.y * scale,
      width: bbox.width * scale,
      height: bbox.height * scale,
    };
  }

  const title = label
    ? __('Original media with face highlight', 'alt-context')
    : __('Original media', 'alt-context');

  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay />
        <DialogContent className="acx-review-card-lightbox" aria-describedby="acx-review-card-lightbox-desc">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription id="acx-review-card-lightbox-desc">
            {label
              ? __('Face region is outlined on the source photo.', 'alt-context')
              : __('Source photo for this review card.', 'alt-context')}
          </DialogDescription>
          <div ref={frameRef} className="acx-review-card-lightbox__frame">
            <img
              src={mediaUrl}
              alt={label ?? __('Original media', 'alt-context')}
              className="acx-review-card-lightbox__image"
              onLoad={handleLoad}
            />
            {highlightStyle ? (
              <span
                className="acx-review-card-lightbox__bbox"
                style={highlightStyle}
                aria-hidden="true"
              />
            ) : null}
          </div>
          <div className="acx-dialog__actions">
            <button
              type="button"
              className="acx-button acx-button--secondary"
              onClick={() => onOpenChange(false)}
            >
              {__('Close', 'alt-context')}
            </button>
          </div>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
};
