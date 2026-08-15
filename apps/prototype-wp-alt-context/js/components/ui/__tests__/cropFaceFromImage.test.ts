import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { cropFaceFromImage } from '../cropFaceFromImage';

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(value, max));

/** Independent copy of the bbox-plus-padding source rect. Mutating production math must fail. */
const expectedSourceRect = (
  naturalWidth: number,
  naturalHeight: number,
  bbox: { x: number; y: number; width: number; height: number },
  paddingRatio: number,
  originalWidth = naturalWidth,
  originalHeight = naturalHeight,
): { sx: number; sy: number; sWidth: number; sHeight: number } => {
  const scaleX = naturalWidth / originalWidth || 1;
  const scaleY = naturalHeight / originalHeight || 1;
  const scaledX = bbox.x * scaleX;
  const scaledY = bbox.y * scaleY;
  const scaledWidth = bbox.width * scaleX;
  const scaledHeight = bbox.height * scaleY;
  const paddingX = scaledWidth * paddingRatio;
  const paddingY = scaledHeight * paddingRatio;
  const expandedX = Math.max(0, scaledX - paddingX);
  const expandedY = Math.max(0, scaledY - paddingY);
  const expandedWidth = scaledWidth + 2 * paddingX;
  const expandedHeight = scaledHeight + 2 * paddingY;
  const centerX = expandedX + expandedWidth / 2;
  const centerY = expandedY + expandedHeight / 2;
  const squareSize = Math.max(expandedWidth, expandedHeight);
  const sx = clamp(centerX - squareSize / 2, 0, Math.max(0, naturalWidth - squareSize));
  const sy = clamp(centerY - squareSize / 2, 0, Math.max(0, naturalHeight - squareSize));
  return {
    sx,
    sy,
    sWidth: Math.min(squareSize, naturalWidth - sx),
    sHeight: Math.min(squareSize, naturalHeight - sy),
  };
};

describe('cropFaceFromImage [TEST-15]', () => {
  const originalGetContext = HTMLCanvasElement.prototype.getContext;
  const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
  const drawImage = vi.fn();
  const clearRect = vi.fn();
  const toDataURL = vi.fn(() => 'data:image/jpeg;base64,crop-record');
  const getContext = vi.fn(() => ({ clearRect, drawImage }));

  beforeEach(() => {
    drawImage.mockClear();
    clearRect.mockClear();
    toDataURL.mockClear();
    getContext.mockClear();
    getContext.mockImplementation(() => ({ clearRect, drawImage }));
    HTMLCanvasElement.prototype.getContext = getContext as unknown as typeof HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.toDataURL = toDataURL as unknown as typeof HTMLCanvasElement.prototype.toDataURL;
  });

  afterEach(() => {
    HTMLCanvasElement.prototype.getContext = originalGetContext;
    HTMLCanvasElement.prototype.toDataURL = originalToDataURL;
  });

  it('returns null for a non-positive size without touching canvas', () => {
    const image = { naturalWidth: 100, naturalHeight: 100, width: 100, height: 100 } as HTMLImageElement;
    expect(
      cropFaceFromImage({
        image,
        bbox: { x: 0, y: 0, width: 10, height: 10 },
        size: 0,
      }),
    ).toBeNull();
    expect(getContext).not.toHaveBeenCalled();
    expect(drawImage).not.toHaveBeenCalled();
    expect(toDataURL).not.toHaveBeenCalled();
  });

  it('draws the padded bbox source rectangle and returns the jpeg data URL', () => {
    const image = { naturalWidth: 200, naturalHeight: 100, width: 200, height: 100 } as HTMLImageElement;
    const bbox = { x: 40, y: 20, width: 40, height: 20 };
    const paddingRatio = 0.15;
    const size = 32;
    const expected = expectedSourceRect(200, 100, bbox, paddingRatio);

    expect(cropFaceFromImage({ image, bbox, size, paddingRatio })).toBe('data:image/jpeg;base64,crop-record');

    expect(getContext).toHaveBeenCalledWith('2d');
    expect(drawImage).toHaveBeenCalledTimes(1);
    const [, sx, sy, sWidth, sHeight, dx, dy, destWidth, destHeight] = drawImage.mock.calls[0] as [
      HTMLImageElement,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
    ];
    expect({ sx, sy, sWidth, sHeight }).toEqual(expected);
    expect(sx).not.toBe(sy);
    const scale = size / Math.max(expected.sWidth, expected.sHeight);
    expect(destWidth).toBeCloseTo(expected.sWidth * scale);
    expect(destHeight).toBeCloseTo(expected.sHeight * scale);
    expect(dx).toBeCloseTo((size - destWidth) / 2);
    expect(dy).toBeCloseTo((size - destHeight) / 2);
    expect(toDataURL).toHaveBeenCalledWith('image/jpeg', 0.92);
  });

  it('scales the source rectangle when original dimensions differ from natural', () => {
    const image = { naturalWidth: 100, naturalHeight: 50, width: 100, height: 50 } as HTMLImageElement;
    const bbox = { x: 80, y: 40, width: 80, height: 40 };
    const paddingRatio = 0.15;
    const expected = expectedSourceRect(100, 50, bbox, paddingRatio, 200, 100);

    cropFaceFromImage({
      image,
      bbox,
      size: 32,
      originalWidth: 200,
      originalHeight: 100,
      paddingRatio,
    });

    const [, sx, sy, sWidth, sHeight] = drawImage.mock.calls[0] as [
      HTMLImageElement,
      number,
      number,
      number,
      number,
    ];
    expect({ sx, sy, sWidth, sHeight }).toEqual(expected);
  });

  it('returns null when the image has no natural size', () => {
    const image = { naturalWidth: 0, naturalHeight: 0, width: 0, height: 0 } as HTMLImageElement;
    expect(
      cropFaceFromImage({
        image,
        bbox: { x: 10, y: 10, width: 20, height: 20 },
        size: 32,
      }),
    ).toBeNull();
    expect(drawImage).not.toHaveBeenCalled();
    expect(toDataURL).not.toHaveBeenCalled();
  });

  it('returns null when getContext is unavailable', () => {
    getContext.mockReturnValueOnce(null);
    const image = { naturalWidth: 100, naturalHeight: 100, width: 100, height: 100 } as HTMLImageElement;
    expect(
      cropFaceFromImage({
        image,
        bbox: { x: 10, y: 10, width: 20, height: 20 },
        size: 32,
      }),
    ).toBeNull();
    expect(drawImage).not.toHaveBeenCalled();
    expect(toDataURL).not.toHaveBeenCalled();
  });

  it('clamps an out-of-range box to the image bounds', () => {
    const image = { naturalWidth: 80, naturalHeight: 80, width: 80, height: 80 } as HTMLImageElement;
    const bbox = { x: 70, y: 70, width: 40, height: 40 };
    const paddingRatio = 0.15;
    const expected = expectedSourceRect(80, 80, bbox, paddingRatio);

    cropFaceFromImage({ image, bbox, size: 32, paddingRatio });

    const [, sx, sy, sWidth, sHeight] = drawImage.mock.calls[0] as [
      HTMLImageElement,
      number,
      number,
      number,
      number,
    ];
    expect({ sx, sy, sWidth, sHeight }).toEqual(expected);
    expect(sx + sWidth).toBeLessThanOrEqual(80);
    expect(sy + sHeight).toBeLessThanOrEqual(80);
  });
});
