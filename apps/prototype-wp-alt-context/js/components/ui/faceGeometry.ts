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

/** True when both natural dimensions are finite and strictly positive. */
export function isUsableNaturalSize(size: NaturalSize): boolean {
  return (
    Number.isFinite(size.width) &&
    Number.isFinite(size.height) &&
    size.width > 0 &&
    size.height > 0
  );
}

/** True when a media id is a finite number strictly greater than zero. */
export function isPositiveMediaId(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

export interface ContainFit {
  scale: number;
  displayWidth: number;
  displayHeight: number;
  offsetX: number;
  offsetY: number;
}

/**
 * Object-fit: contain math: scale a natural image into a frame, letter/pillar-box.
 * Shared by FaceLightbox fallback bbox and the overlay-layer wrapper.
 */
export function containFit(natural: NaturalSize, frame: NaturalSize): ContainFit | null {
  if (!isUsableNaturalSize(natural) || !isUsableNaturalSize(frame)) {
    return null;
  }
  const scale = Math.min(frame.width / natural.width, frame.height / natural.height);
  const displayWidth = natural.width * scale;
  const displayHeight = natural.height * scale;
  return {
    scale,
    displayWidth,
    displayHeight,
    offsetX: (frame.width - displayWidth) / 2,
    offsetY: (frame.height - displayHeight) / 2,
  };
}

/**
 * True when bbox has all four edges as finite numbers (runtime API may omit fields).
 * Does not require positive width/height — zero-extent boxes are still positionable.
 */
export function isCompleteFiniteBbox(bbox: BoundingBox | null | undefined): bbox is BoundingBox {
  if (bbox == null || typeof bbox !== 'object') {
    return false;
  }
  return (
    Number.isFinite(bbox.x) &&
    Number.isFinite(bbox.y) &&
    Number.isFinite(bbox.width) &&
    Number.isFinite(bbox.height)
  );
}

/**
 * True when bbox is complete, finite, and has strictly positive extent — safe for cropTransformFor.
 * Arrow form (unlike its siblings) so the file's func-style baseline does not grow.
 */
export const isCroppableBbox = (bbox: BoundingBox | null | undefined): bbox is BoundingBox =>
  isCompleteFiniteBbox(bbox) && bbox.width > 0 && bbox.height > 0;

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
  // Non-finite or non-positive natural dims → zero rect (callers should also skip render).
  if (!isUsableNaturalSize(naturalSize) || !isCompleteFiniteBbox(bbox)) {
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
