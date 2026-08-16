import { describe, expect, it } from 'vitest';

import { isDedicatedFaceThumbUrl } from '../isDedicatedFaceThumbUrl';

describe('isDedicatedFaceThumbUrl', () => {
  it('accepts recognition face-thumbs URLs', () => {
    expect(
      isDedicatedFaceThumbUrl('https://example.test/wp-content/uploads/recognition/face-thumbs/rep-1.jpg'),
    ).toBe(true);
  });

  it('rejects plain media thumbs and empty values', () => {
    expect(isDedicatedFaceThumbUrl('https://example.test/uploads/2026/01/photo.jpg')).toBe(false);
    expect(isDedicatedFaceThumbUrl('')).toBe(false);
    expect(isDedicatedFaceThumbUrl(null)).toBe(false);
    expect(isDedicatedFaceThumbUrl(undefined)).toBe(false);
  });
});
