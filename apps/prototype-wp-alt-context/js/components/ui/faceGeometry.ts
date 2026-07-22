/**
 * Pure face-bbox projection helpers shared by FaceThumbnail (crop-into-square)
 * and FaceOverlayLayer (percentage rects over a displayed image).
 */

import type { BoundingBox } from '../../admin/api/recognition/types/identity';

export interface CropTransform {
  scale: number;
  offsetX: number;
  offsetY: number;
}

export interface OverlayRect {
  /** left edge as % of natural image width */
  left: number;
  /** top edge as % of natural image height */
  top: number;
  /** width as % of natural image width */
  width: number;
  /** height as % of natural image height */
  height: number;
}

export interface NaturalSize {
  width: number;
  height: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * Scale/offset transform that crops `bbox` into a fixed square of `displaySize`.
 * Matches the pre-extraction FaceThumbnail math.
 */
export function cropTransformFor(bbox: BoundingBox, displaySize: number): CropTransform {
  const denom = Math.max(bbox.width, bbox.height);
  const scale = denom > 0 ? displaySize / denom : 0;
  const scaledWidth = bbox.width * scale;
  const scaledHeight = bbox.height * scale;
  const offsetX = (displaySize - scaledWidth) / 2;
  const offsetY = (displaySize - scaledHeight) / 2;
  return { scale, offsetX, offsetY };
}

/**
 * Map a pixel-space bbox onto percentage position within the natural image.
 * Degenerate / out-of-bounds boxes are clamped into [0, 100] ranges.
 */
export function overlayRectFor(bbox: BoundingBox, naturalSize: NaturalSize): OverlayRect {
  if (naturalSize.width <= 0 || naturalSize.height <= 0) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }

  const safeWidth = Math.max(0, bbox.width);
  const safeHeight = Math.max(0, bbox.height);

  const x0 = clamp(bbox.x, 0, naturalSize.width);
  const y0 = clamp(bbox.y, 0, naturalSize.height);
  const x1 = clamp(bbox.x + safeWidth, 0, naturalSize.width);
  const y1 = clamp(bbox.y + safeHeight, 0, naturalSize.height);

  return {
    left: (x0 / naturalSize.width) * 100,
    top: (y0 / naturalSize.height) * 100,
    width: ((x1 - x0) / naturalSize.width) * 100,
    height: ((y1 - y0) / naturalSize.height) * 100,
  };
}
