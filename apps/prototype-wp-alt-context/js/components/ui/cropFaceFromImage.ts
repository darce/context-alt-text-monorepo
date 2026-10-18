/**
 * Canvas crop of a face bbox into a square data URL.
 * Shared by IdentityThumbnail and the durable-thumb fallback path.
 */

export const FACE_CROP_PADDING_RATIO = 0.15;

export interface PixelBbox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CropFaceFromImageOptions {
  image: CanvasImageSource & {
    naturalWidth?: number;
    naturalHeight?: number;
    width?: number;
    height?: number;
  };
  bbox: PixelBbox;
  size: number;
  originalWidth?: number;
  originalHeight?: number;
  paddingRatio?: number;
}

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(value, max));

export const cropFaceFromImage = (options: CropFaceFromImageOptions): string | null => {
  const { image, bbox, size, paddingRatio = FACE_CROP_PADDING_RATIO } = options;
  if (!Number.isFinite(size) || size <= 0) {
    return null;
  }

  try {
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      return null;
    }

    // 0 is an unloaded/unusable dimension and must fall through; ?? would keep 0.
    /* eslint-disable @typescript-eslint/prefer-nullish-coalescing -- 0-width/height must fall through */
    const naturalWidth = image.naturalWidth || image.width || 0;
    const naturalHeight = image.naturalHeight || image.height || 0;
    /* eslint-enable @typescript-eslint/prefer-nullish-coalescing */
    if (!Number.isFinite(naturalWidth) || !Number.isFinite(naturalHeight) || naturalWidth <= 0 || naturalHeight <= 0) {
      return null;
    }

    const originalWidth = options.originalWidth ?? naturalWidth;
    const originalHeight = options.originalHeight ?? naturalHeight;
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
    const maxSx = Math.max(0, naturalWidth - squareSize);
    const maxSy = Math.max(0, naturalHeight - squareSize);

    const sx = clamp(centerX - squareSize / 2, 0, maxSx);
    const sy = clamp(centerY - squareSize / 2, 0, maxSy);
    const sWidth = Math.min(squareSize, naturalWidth - sx);
    const sHeight = Math.min(squareSize, naturalHeight - sy);

    const scale = size / Math.max(sWidth, sHeight);
    const destWidth = sWidth * scale;
    const destHeight = sHeight * scale;

    const dx = (size - destWidth) / 2;
    const dy = (size - destHeight) / 2;

    ctx.clearRect(0, 0, size, size);
    ctx.drawImage(image, sx, sy, sWidth, sHeight, dx, dy, destWidth, destHeight);
    return canvas.toDataURL('image/jpeg', 0.92);
  } catch {
    return null;
  }
};
