/**
 * Pure face-thumb display resolver.
 *
 * Prefer the scan-time dedicated blob (`thumb_url` under recognition/face-thumbs).
 * When that blob 404s after cleanup, crop from durable attachment_url + bbox.
 * Missing data stays quiet; a claimed URL that then fails stays loud.
 */

import type { BoundingBox } from '../../admin/api/recognition/types/identity';
import { isCroppableBbox } from './faceGeometry';
import { isDedicatedFaceThumbUrl } from './isDedicatedFaceThumbUrl';

export const AVATAR_STATE = {
  loading: 'loading',
  real: 'real',
  fallbackCrop: 'fallback-crop',
  missing: 'missing',
  error: 'error',
} as const;

export type AvatarState = (typeof AVATAR_STATE)[keyof typeof AVATAR_STATE];

export const FACE_THUMB_MODE = {
  avatar: 'avatar',
  crop: 'crop',
  none: 'none',
} as const;

export type FaceThumbMode = (typeof FACE_THUMB_MODE)[keyof typeof FACE_THUMB_MODE];

export const LOAD_STATUS = {
  idle: 'idle',
  loading: 'loading',
  loaded: 'loaded',
  error: 'error',
} as const;

export type LoadStatus = (typeof LOAD_STATUS)[keyof typeof LOAD_STATUS];

export const REPRESENTATIVE_IMAGE_UNAVAILABLE = 'Representative image unavailable';

export interface FaceThumbSource {
  thumbUrl?: string | null;
  attachmentUrl?: string | null;
  mediaUrl?: string | null;
  bbox?: BoundingBox | null;
}

export interface FaceThumbLoadStatus {
  blobStatus: LoadStatus;
  cropStatus: LoadStatus;
}

export interface FaceThumbCrop {
  mediaUrl: string;
  bbox: BoundingBox;
}

export interface FaceThumbDisplay {
  state: AvatarState;
  mode: FaceThumbMode;
  src: string | null;
  crop: FaceThumbCrop | null;
  unavailableLabel: string | null;
  isLoudError: boolean;
}

const nonemptyUrl = (value: string | null | undefined): value is string =>
  typeof value === 'string' && value.trim() !== '';

export const resolveFaceThumbCrop = (source: FaceThumbSource): FaceThumbCrop | null => {
  const mediaUrl = nonemptyUrl(source.attachmentUrl)
    ? source.attachmentUrl
    : nonemptyUrl(source.mediaUrl)
      ? source.mediaUrl
      : null;
  if (!mediaUrl || !isCroppableBbox(source.bbox)) {
    return null;
  }
  return { mediaUrl, bbox: source.bbox };
};

export const resolveFaceThumbDisplay = (
  source: FaceThumbSource,
  loadStatus: FaceThumbLoadStatus,
): FaceThumbDisplay => {
  const thumbUrl = nonemptyUrl(source.thumbUrl) ? source.thumbUrl.trim() : null;
  const crop = resolveFaceThumbCrop(source);
  const dedicated = isDedicatedFaceThumbUrl(thumbUrl);
  const { blobStatus, cropStatus } = loadStatus;

  const missing = (partial?: Partial<FaceThumbDisplay>): FaceThumbDisplay => ({
    state: AVATAR_STATE.missing,
    mode: FACE_THUMB_MODE.none,
    src: null,
    crop: null,
    unavailableLabel: REPRESENTATIVE_IMAGE_UNAVAILABLE,
    isLoudError: false,
    ...partial,
  });

  const loudError = (partial?: Partial<FaceThumbDisplay>): FaceThumbDisplay => ({
    state: AVATAR_STATE.error,
    mode: FACE_THUMB_MODE.none,
    src: null,
    crop: null,
    unavailableLabel: null,
    isLoudError: true,
    ...partial,
  });

  const fallbackCrop = (): FaceThumbDisplay => ({
    state: AVATAR_STATE.fallbackCrop,
    mode: FACE_THUMB_MODE.crop,
    src: null,
    crop,
    unavailableLabel: null,
    isLoudError: false,
  });

  if (thumbUrl && (dedicated || crop)) {
    if (blobStatus === LOAD_STATUS.error) {
      if (crop && cropStatus !== LOAD_STATUS.error) {
        return fallbackCrop();
      }
      return loudError();
    }
    if (blobStatus === LOAD_STATUS.loaded) {
      return {
        state: AVATAR_STATE.real,
        mode: FACE_THUMB_MODE.avatar,
        src: thumbUrl,
        crop: null,
        unavailableLabel: null,
        isLoudError: false,
      };
    }
    return {
      state: AVATAR_STATE.loading,
      mode: FACE_THUMB_MODE.avatar,
      src: thumbUrl,
      crop: null,
      unavailableLabel: null,
      isLoudError: false,
    };
  }

  if (thumbUrl) {
    if (blobStatus === LOAD_STATUS.error) {
      return loudError();
    }
    if (blobStatus === LOAD_STATUS.loaded) {
      return {
        state: AVATAR_STATE.real,
        mode: FACE_THUMB_MODE.avatar,
        src: thumbUrl,
        crop: null,
        unavailableLabel: null,
        isLoudError: false,
      };
    }
    return {
      state: AVATAR_STATE.loading,
      mode: FACE_THUMB_MODE.avatar,
      src: thumbUrl,
      crop: null,
      unavailableLabel: null,
      isLoudError: false,
    };
  }

  if (crop) {
    if (cropStatus === LOAD_STATUS.error) {
      return loudError();
    }
    if (cropStatus === LOAD_STATUS.loaded) {
      return {
        state: AVATAR_STATE.real,
        mode: FACE_THUMB_MODE.crop,
        src: null,
        crop,
        unavailableLabel: null,
        isLoudError: false,
      };
    }
    return {
      state: AVATAR_STATE.loading,
      mode: FACE_THUMB_MODE.crop,
      src: null,
      crop,
      unavailableLabel: null,
      isLoudError: false,
    };
  }

  return missing();
};
