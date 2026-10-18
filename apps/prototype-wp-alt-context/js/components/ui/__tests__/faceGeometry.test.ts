import { describe, it, expect } from 'vitest';

import {
  containFit,
  cropTransformFor,
  isCompleteFiniteBbox,
  isCroppableBbox,
  isPositiveMediaId,
  isUsableNaturalSize,
  overlayRectFor,
} from '../faceGeometry';
import type { BoundingBox } from '../../../admin/api/recognition/types/identity';

describe('cropTransformFor', () => {
  it('matches FaceThumbnail square-bbox scale for md (48px)', () => {
    const bbox: BoundingBox = { x: 100, y: 50, width: 200, height: 200 };
    const { scale, offsetX, offsetY } = cropTransformFor(bbox, 48);
    expect(scale).toBe(0.24);
    expect(offsetX).toBe(0);
    expect(offsetY).toBe(0);
  });

  it('centers a wide bbox in the display square', () => {
    const bbox: BoundingBox = { x: 0, y: 0, width: 200, height: 100 };
    const { scale, offsetX, offsetY } = cropTransformFor(bbox, 48);
    expect(scale).toBe(0.24);
    expect(offsetX).toBe(0);
    expect(offsetY).toBe((48 - 100 * 0.24) / 2);
  });
});

describe('overlayRectFor', () => {
  const natural = { width: 1000, height: 500 };

  it('returns exact percentages for a known bbox', () => {
    const bbox: BoundingBox = { x: 100, y: 50, width: 200, height: 100 };
    expect(overlayRectFor(bbox, natural)).toEqual({
      left: 10,
      top: 10,
      width: 20,
      height: 20,
    });
  });

  it('returns zero-area rect for zero-width/height bbox', () => {
    const bbox: BoundingBox = { x: 250, y: 100, width: 0, height: 0 };
    expect(overlayRectFor(bbox, natural)).toEqual({
      left: 25,
      top: 20,
      width: 0,
      height: 0,
    });
  });

  it('clamps a bbox that extends past the image edge', () => {
    const bbox: BoundingBox = { x: 900, y: 400, width: 200, height: 200 };
    expect(overlayRectFor(bbox, natural)).toEqual({
      left: 90,
      top: 80,
      width: 10,
      height: 20,
    });
  });

  it('clamps a fully out-of-bounds bbox to an empty rect at the edge', () => {
    const bbox: BoundingBox = { x: 2000, y: -100, width: 50, height: 50 };
    expect(overlayRectFor(bbox, natural)).toEqual({
      left: 100,
      top: 0,
      width: 0,
      height: 0,
    });
  });

  it('returns zeros when natural size is degenerate', () => {
    const bbox: BoundingBox = { x: 10, y: 10, width: 20, height: 20 };
    expect(overlayRectFor(bbox, { width: 0, height: 0 })).toEqual({
      left: 0,
      top: 0,
      width: 0,
      height: 0,
    });
  });

  it('returns zeros when natural size is non-finite', () => {
    const bbox: BoundingBox = { x: 10, y: 10, width: 20, height: 20 };
    expect(overlayRectFor(bbox, { width: Number.NaN, height: 500 })).toEqual({
      left: 0,
      top: 0,
      width: 0,
      height: 0,
    });
    expect(overlayRectFor(bbox, { width: 1000, height: Number.POSITIVE_INFINITY })).toEqual({
      left: 0,
      top: 0,
      width: 0,
      height: 0,
    });
  });

  it('returns zeros when bbox fields are incomplete or non-finite', () => {
    const partial = { x: 10, y: 10 } as unknown as BoundingBox;
    const nanBbox: BoundingBox = { x: 10, y: Number.NaN, width: 20, height: 20 };
    expect(overlayRectFor(partial, natural)).toEqual({
      left: 0,
      top: 0,
      width: 0,
      height: 0,
    });
    expect(overlayRectFor(nanBbox, natural)).toEqual({
      left: 0,
      top: 0,
      width: 0,
      height: 0,
    });
  });

  it('treats negative bbox dimensions as zero extent', () => {
    const bbox: BoundingBox = { x: 100, y: 50, width: -40, height: -20 };
    expect(overlayRectFor(bbox, natural)).toEqual({
      left: 10,
      top: 10,
      width: 0,
      height: 0,
    });
  });
});

describe('isUsableNaturalSize / isCompleteFiniteBbox', () => {
  it('rejects zero and non-finite natural sizes', () => {
    expect(isUsableNaturalSize({ width: 100, height: 50 })).toBe(true);
    expect(isUsableNaturalSize({ width: 0, height: 50 })).toBe(false);
    expect(isUsableNaturalSize({ width: Number.NaN, height: 50 })).toBe(false);
  });

  it('rejects partial and non-finite bboxes', () => {
    expect(isCompleteFiniteBbox({ x: 1, y: 2, width: 3, height: 4 })).toBe(true);
    expect(isCompleteFiniteBbox(null)).toBe(false);
    expect(isCompleteFiniteBbox({ x: 1, y: 2 } as unknown as BoundingBox)).toBe(false);
    expect(isCompleteFiniteBbox({ x: 1, y: 2, width: Number.NaN, height: 4 })).toBe(false);
  });

  it('isCompleteFiniteBbox accepts the PHP zero-extent placeholder {0,0,0,0}', () => {
    // trait-maps-response-fields.php emits this when bbox_json is missing/undecodable.
    expect(isCompleteFiniteBbox({ x: 0, y: 0, width: 0, height: 0 })).toBe(true);
  });
});

describe('containFit', () => {
  it('letterboxes a wide image in a taller frame (same math as FaceLightbox)', () => {
    const fit = containFit({ width: 200, height: 150 }, { width: 400, height: 300 });
    expect(fit).toEqual({
      scale: 2,
      displayWidth: 400,
      displayHeight: 300,
      offsetX: 0,
      offsetY: 0,
    });
  });

  it('pillarboxes a tall image in a wide frame', () => {
    const fit = containFit({ width: 100, height: 200 }, { width: 400, height: 200 });
    expect(fit).toEqual({
      scale: 1,
      displayWidth: 100,
      displayHeight: 200,
      offsetX: 150,
      offsetY: 0,
    });
  });

  it('returns null when natural or frame size is unusable', () => {
    expect(containFit({ width: 0, height: 100 }, { width: 400, height: 300 })).toBeNull();
    expect(containFit({ width: 100, height: 100 }, { width: Number.NaN, height: 300 })).toBeNull();
  });
});

describe('isPositiveMediaId', () => {
  it('accepts finite integers greater than zero', () => {
    expect(isPositiveMediaId(1)).toBe(true);
    expect(isPositiveMediaId(42)).toBe(true);
  });

  it('rejects zero, negatives, non-finite, and non-numbers', () => {
    expect(isPositiveMediaId(0)).toBe(false);
    expect(isPositiveMediaId(-3)).toBe(false);
    expect(isPositiveMediaId(Number.NaN)).toBe(false);
    expect(isPositiveMediaId(null)).toBe(false);
    expect(isPositiveMediaId(undefined)).toBe(false);
    expect(isPositiveMediaId('12')).toBe(false);
  });
});

describe('isCroppableBbox', () => {
  it('accepts complete finite boxes with strictly positive extent', () => {
    expect(isCroppableBbox({ x: 1, y: 2, width: 3, height: 4 })).toBe(true);
  });

  it('rejects null, incomplete, and non-finite boxes', () => {
    expect(isCroppableBbox(null)).toBe(false);
    expect(isCroppableBbox(undefined)).toBe(false);
    expect(isCroppableBbox({ x: 1, y: 2, width: Number.NaN, height: 4 })).toBe(false);
  });

  it('rejects the PHP zero-extent placeholder {0,0,0,0} (cropTransformFor would paint a blank)', () => {
    expect(isCroppableBbox({ x: 0, y: 0, width: 0, height: 0 })).toBe(false);
  });

  it('rejects zero width or zero height even when the other edge is positive', () => {
    expect(isCroppableBbox({ x: 0, y: 0, width: 0, height: 10 })).toBe(false);
    expect(isCroppableBbox({ x: 0, y: 0, width: 10, height: 0 })).toBe(false);
  });
});
