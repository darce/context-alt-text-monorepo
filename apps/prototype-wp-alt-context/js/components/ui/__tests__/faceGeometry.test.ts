import { describe, it, expect } from 'vitest';

import { cropTransformFor, overlayRectFor } from '../faceGeometry';
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
