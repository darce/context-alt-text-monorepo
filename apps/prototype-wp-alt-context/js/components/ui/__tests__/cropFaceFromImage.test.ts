import { describe, expect, it } from 'vitest';

import { cropFaceFromImage } from '../cropFaceFromImage';

describe('cropFaceFromImage', () => {
  it('returns null for a non-positive size', () => {
    const image = { naturalWidth: 100, naturalHeight: 100, width: 100, height: 100 } as HTMLImageElement;
    expect(
      cropFaceFromImage({
        image,
        bbox: { x: 0, y: 0, width: 10, height: 10 },
        size: 0,
      }),
    ).toBeNull();
  });
});
