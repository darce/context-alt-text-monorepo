import { describe, expect, it } from 'vitest';

import type { BoundingBox } from '../../../admin/api/recognition/types/identity';
import {
  AVATAR_STATE,
  FACE_THUMB_MODE,
  LOAD_STATUS,
  resolveFaceThumbCrop,
  resolveFaceThumbDisplay,
  resolveUncroppedSource,
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
    expect(display.unavailableLabel).toBe('Representative image unavailable');
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
    expect(missing.state).toBe('data-missing');
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

  it('a non-dedicated thumbUrl with croppable media falls through to crop [REV1-01]', () => {
    const display = resolveFaceThumbDisplay(
      { thumbUrl: ATTACHMENT_URL, mediaUrl: ATTACHMENT_URL, bbox: BBOX },
      { blobStatus: LOAD_STATUS.idle, cropStatus: LOAD_STATUS.idle },
    );

    expect(display.mode).toBe(FACE_THUMB_MODE.crop);
    expect(display.state).toBe(AVATAR_STATE.loading);
    expect(display.src).toBeNull();
    expect(display.crop).toEqual({ mediaUrl: ATTACHMENT_URL, bbox: BBOX });
  });

  it('a nonempty mediaUrl without a croppable bbox is uncropped, not missing [REV1-02]', () => {
    const display = resolveFaceThumbDisplay(
      { thumbUrl: null, mediaUrl: ATTACHMENT_URL, bbox: { x: 0, y: 0, width: 0, height: 0 } },
      { blobStatus: LOAD_STATUS.idle, cropStatus: LOAD_STATUS.idle },
    );

    expect(display.state).toBe(AVATAR_STATE.uncropped);
    expect(display.mode).toBe(FACE_THUMB_MODE.uncropped);
    expect(display.src).toBe(ATTACHMENT_URL);
    expect(display.unavailableLabel).toBeNull();
    expect(display.isLoudError).toBe(false);
  });

  it('a plain thumbUrl with no crop data is uncropped last-hop, not avatar', () => {
    const display = resolveFaceThumbDisplay(
      { thumbUrl: ATTACHMENT_URL },
      { blobStatus: LOAD_STATUS.idle, cropStatus: LOAD_STATUS.idle },
    );

    expect(display.state).toBe(AVATAR_STATE.uncropped);
    expect(display.mode).toBe(FACE_THUMB_MODE.uncropped);
    expect(display.src).toBe(ATTACHMENT_URL);
  });
});

describe('resolveUncroppedSource', () => {
  it('prefers attachment_url over media_url, then a non-dedicated thumb', () => {
    expect(
      resolveUncroppedSource({
        attachmentUrl: ATTACHMENT_URL,
        mediaUrl: 'https://example.test/uploads/legacy.jpg',
        thumbUrl: 'https://example.test/uploads/150.jpg',
      }),
    ).toBe(ATTACHMENT_URL);
    expect(resolveUncroppedSource({ mediaUrl: ATTACHMENT_URL })).toBe(ATTACHMENT_URL);
    expect(resolveUncroppedSource({ thumbUrl: ATTACHMENT_URL })).toBe(ATTACHMENT_URL);
    expect(resolveUncroppedSource({ thumbUrl: BLOB_URL })).toBeNull();
  });
});
