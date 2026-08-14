import { describe, expect, it } from 'vitest';

import type { BoundingBox } from '../../../admin/api/recognition/types/identity';
import {
  AVATAR_STATE,
  FACE_THUMB_MODE,
  LOAD_STATUS,
  REPRESENTATIVE_IMAGE_UNAVAILABLE,
  resolveFaceThumbCrop,
  resolveFaceThumbDisplay,
} from '../faceThumbDisplay';

const BBOX: BoundingBox = { x: 10, y: 20, width: 40, height: 50 };
const BLOB_URL = 'https://example.test/wp-json/acx/v1/recognition/face-thumbs/job-1/50';
const ATTACHMENT_URL = 'https://example.test/uploads/50.jpg';

describe('resolveFaceThumbCrop', () => {
  it('prefers attachment_url over media_url when the bbox is croppable', () => {
    expect(
      resolveFaceThumbCrop({
        attachmentUrl: ATTACHMENT_URL,
        mediaUrl: 'https://example.test/uploads/legacy.jpg',
        bbox: BBOX,
      }),
    ).toEqual({ mediaUrl: ATTACHMENT_URL, bbox: BBOX });
  });

  it('returns null when attachment and bbox are both missing', () => {
    expect(resolveFaceThumbCrop({ thumbUrl: BLOB_URL })).toBeNull();
  });
});

describe('resolveFaceThumbDisplay [TEST-15]', () => {
  it('blob-error → attachment-bbox-crop is fallback-crop and not loud error', () => {
    const display = resolveFaceThumbDisplay(
      { thumbUrl: BLOB_URL, attachmentUrl: ATTACHMENT_URL, bbox: BBOX },
      { blobStatus: LOAD_STATUS.error, cropStatus: LOAD_STATUS.loading },
    );

    expect(display.state).toBe(AVATAR_STATE.fallbackCrop);
    expect(display.mode).toBe(FACE_THUMB_MODE.crop);
    expect(display.crop).toEqual({ mediaUrl: ATTACHMENT_URL, bbox: BBOX });
    expect(display.isLoudError).toBe(false);
  });

  it('missing state (no attachment/bbox) is quiet Representative image unavailable', () => {
    const display = resolveFaceThumbDisplay(
      { thumbUrl: null, attachmentUrl: null, mediaUrl: null, bbox: null },
      { blobStatus: LOAD_STATUS.idle, cropStatus: LOAD_STATUS.idle },
    );

    expect(display.state).toBe(AVATAR_STATE.missing);
    expect(display.unavailableLabel).toBe(REPRESENTATIVE_IMAGE_UNAVAILABLE);
    expect(display.isLoudError).toBe(false);
    expect(display.mode).toBe(FACE_THUMB_MODE.none);
  });

  it('genuine network failure (blob + crop both fail) stays loud error', () => {
    const display = resolveFaceThumbDisplay(
      { thumbUrl: BLOB_URL, attachmentUrl: ATTACHMENT_URL, bbox: BBOX },
      { blobStatus: LOAD_STATUS.error, cropStatus: LOAD_STATUS.error },
    );

    expect(display.state).toBe(AVATAR_STATE.error);
    expect(display.isLoudError).toBe(true);
  });

  it('data-avatar-state distinguishes fallback-crop vs missing vs error', () => {
    const fallback = resolveFaceThumbDisplay(
      { thumbUrl: BLOB_URL, attachmentUrl: ATTACHMENT_URL, bbox: BBOX },
      { blobStatus: LOAD_STATUS.error, cropStatus: LOAD_STATUS.loaded },
    );
    const missing = resolveFaceThumbDisplay(
      {},
      { blobStatus: LOAD_STATUS.idle, cropStatus: LOAD_STATUS.idle },
    );
    const error = resolveFaceThumbDisplay(
      { thumbUrl: BLOB_URL },
      { blobStatus: LOAD_STATUS.error, cropStatus: LOAD_STATUS.idle },
    );

    expect(fallback.state).toBe('fallback-crop');
    expect(missing.state).toBe('missing');
    expect(error.state).toBe('error');
    expect(new Set([fallback.state, missing.state, error.state]).size).toBe(3);
  });

  it('a dedicated blob that loaded stays real, not fallback-crop', () => {
    const display = resolveFaceThumbDisplay(
      { thumbUrl: BLOB_URL, attachmentUrl: ATTACHMENT_URL, bbox: BBOX },
      { blobStatus: LOAD_STATUS.loaded, cropStatus: LOAD_STATUS.idle },
    );

    expect(display.state).toBe(AVATAR_STATE.real);
    expect(display.mode).toBe(FACE_THUMB_MODE.avatar);
    expect(display.src).toBe(BLOB_URL);
    expect(display.isLoudError).toBe(false);
  });
});
