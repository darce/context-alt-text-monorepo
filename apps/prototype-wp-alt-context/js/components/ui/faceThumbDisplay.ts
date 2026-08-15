/**
 * Pure face-thumb display resolver.
 *
 * Hop order matches ClusterLabelingPanel:
 *   dedicated face-thumb blob → CSS crop of attachment/media + bbox →
 *   uncropped source → missing.
 *
 * PHP MapsResponseFields::resolve_thumb_url falls back to the full-scene
 * attachment URL whenever no /recognition/face-thumbs/ blob exists, so
 * "thumbUrl is nonempty" is not "thumbUrl is a dedicated face crop".
 * Gate the avatar-first branch on isDedicatedFaceThumbUrl alone.
 */

import { __, sprintf } from '@wordpress/i18n';

import type { BoundingBox } from '../../admin/api/recognition/types/identity';
import { isCroppableBbox } from './faceGeometry';
import { isDedicatedFaceThumbUrl } from './isDedicatedFaceThumbUrl';

export const AVATAR_STATE = {
  loading: 'loading',
  real: 'real',
  fallbackCrop: 'fallback-crop',
  uncropped: 'uncropped',
  missing: 'data-missing',
  error: 'error',
} as const;

export type AvatarState = (typeof AVATAR_STATE)[keyof typeof AVATAR_STATE];

export const FACE_THUMB_MODE = {
  avatar: 'avatar',
  crop: 'crop',
  uncropped: 'uncropped',
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

export function unavailableImageName(alt?: string | null): string {
  if (typeof alt === 'string' && alt.trim() !== '') {
    return sprintf(
      /* translators: %s: image description */
      __('%s — image unavailable', 'alt-context'),
      alt,
    );
  }
  return __('Representative image unavailable', 'alt-context');
}

export interface FaceThumbSource {
  thumbUrl?: string | null;
  attachmentUrl?: string | null;
  mediaUrl?: string | null;
  bbox?: BoundingBox | null;
}

export interface FaceThumbLoadStatus {
  blobStatus: LoadStatus;
  cropStatus: LoadStatus;
  uncroppedStatus?: LoadStatus;
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

const trimmedUrl = (value: string | null | undefined): string | null =>
  nonemptyUrl(value) ? value.trim() : null;

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

/**
 * Last-hop source when no dedicated blob and no croppable bbox exist.
 * Prefer attachment, then media, then a non-dedicated thumb_url.
 */
export const resolveUncroppedSource = (source: FaceThumbSource): string | null => {
  const attachment = trimmedUrl(source.attachmentUrl);
  if (attachment) {
    return attachment;
  }
  const media = trimmedUrl(source.mediaUrl);
  if (media) {
    return media;
  }
  const thumb = trimmedUrl(source.thumbUrl);
  if (thumb && !isDedicatedFaceThumbUrl(thumb)) {
    return thumb;
  }
  return null;
};

export const resolveFaceThumbDisplay = (
  source: FaceThumbSource,
  loadStatus: FaceThumbLoadStatus,
): FaceThumbDisplay => {
  const thumbUrl = trimmedUrl(source.thumbUrl);
  const crop = resolveFaceThumbCrop(source);
  const dedicated = isDedicatedFaceThumbUrl(thumbUrl);
  const uncroppedSrc = resolveUncroppedSource(source);
  const { blobStatus, cropStatus } = loadStatus;
  const uncroppedStatus = loadStatus.uncroppedStatus ?? LOAD_STATUS.idle;

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

  const uncropped = (): FaceThumbDisplay => ({
    state: AVATAR_STATE.uncropped,
    mode: FACE_THUMB_MODE.uncropped,
    src: uncroppedSrc,
    crop: null,
    unavailableLabel: null,
    isLoudError: false,
  });

  // Dedicated blob only — a nonempty attachment URL in thumb_url is not a face chip.
  if (dedicated && thumbUrl && blobStatus !== LOAD_STATUS.error) {
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
    if (dedicated && blobStatus === LOAD_STATUS.error) {
      return fallbackCrop();
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

  if (uncroppedSrc) {
    if (uncroppedStatus === LOAD_STATUS.error) {
      return loudError();
    }
    return uncropped();
  }

  if (dedicated && blobStatus === LOAD_STATUS.error) {
    return loudError();
  }

  return missing();
};
