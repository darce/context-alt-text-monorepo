import * as React from 'react';

import {
  LOAD_STATUS,
  resolveFaceThumbDisplay,
  type FaceThumbDisplay,
  type FaceThumbSource,
  type LoadStatus,
} from './faceThumbDisplay';
import { isDedicatedFaceThumbUrl } from './isDedicatedFaceThumbUrl';

export interface UseDurableFaceThumbResult {
  display: FaceThumbDisplay;
  onBlobLoad: () => void;
  onBlobError: () => void;
  onCropLoad: () => void;
  onCropError: () => void;
  onUncroppedLoad: () => void;
  onUncroppedError: () => void;
}

const normalizedBboxKey = (bbox: FaceThumbSource['bbox']): string => {
  if (
    bbox == null ||
    !Number.isFinite(bbox.x) ||
    !Number.isFinite(bbox.y) ||
    !Number.isFinite(bbox.width) ||
    !Number.isFinite(bbox.height)
  ) {
    return '';
  }
  return `${bbox.x},${bbox.y},${bbox.width},${bbox.height}`;
};

export const cropKeyFor = (source: FaceThumbSource): string =>
  `${source.attachmentUrl ?? ''}|${source.mediaUrl ?? ''}|${normalizedBboxKey(source.bbox)}`;

const dedicatedKeyFor = (source: FaceThumbSource): string =>
  isDedicatedFaceThumbUrl(source.thumbUrl) ? (source.thumbUrl ?? '') : '';

const uncroppedKeyFor = (source: FaceThumbSource): string =>
  `${source.attachmentUrl ?? ''}|${source.mediaUrl ?? ''}|${source.thumbUrl ?? ''}`;

const resetIfKeyChanged = (
  currentKey: string,
  seenKey: string,
  setSeenKey: (key: string) => void,
  nextStatus: LoadStatus,
  setStatus: (status: LoadStatus) => void,
): LoadStatus => {
  if (currentKey === seenKey) {
    return nextStatus;
  }
  setSeenKey(currentKey);
  setStatus(nextStatus);
  return nextStatus;
};

export const useDurableFaceThumb = (source: FaceThumbSource): UseDurableFaceThumbResult => {
  const dedicatedKey = dedicatedKeyFor(source);
  const cropKey = cropKeyFor(source);
  const uncroppedKey = uncroppedKeyFor(source);

  const [blobStatus, setBlobStatus] = React.useState<LoadStatus>(
    dedicatedKey ? LOAD_STATUS.loading : LOAD_STATUS.idle,
  );
  const [cropStatus, setCropStatus] = React.useState<LoadStatus>(LOAD_STATUS.idle);
  const [uncroppedStatus, setUncroppedStatus] = React.useState<LoadStatus>(LOAD_STATUS.idle);

  const [seenDedicatedKey, setSeenDedicatedKey] = React.useState(dedicatedKey);
  const [seenCropKey, setSeenCropKey] = React.useState(cropKey);
  const [seenUncroppedKey, setSeenUncroppedKey] = React.useState(uncroppedKey);

  const liveDedicatedKey = React.useRef(dedicatedKey);
  const liveCropKey = React.useRef(cropKey);
  const liveUncroppedKey = React.useRef(uncroppedKey);
  liveDedicatedKey.current = dedicatedKey;
  liveCropKey.current = cropKey;
  liveUncroppedKey.current = uncroppedKey;

  const nextBlobStatus = resetIfKeyChanged(
    dedicatedKey,
    seenDedicatedKey,
    setSeenDedicatedKey,
    dedicatedKey !== seenDedicatedKey
      ? dedicatedKey
        ? LOAD_STATUS.loading
        : LOAD_STATUS.idle
      : blobStatus,
    setBlobStatus,
  );
  const nextCropStatus = resetIfKeyChanged(
    cropKey,
    seenCropKey,
    setSeenCropKey,
    cropKey !== seenCropKey ? LOAD_STATUS.idle : cropStatus,
    setCropStatus,
  );
  const nextUncroppedStatus = resetIfKeyChanged(
    uncroppedKey,
    seenUncroppedKey,
    setSeenUncroppedKey,
    uncroppedKey !== seenUncroppedKey ? LOAD_STATUS.idle : uncroppedStatus,
    setUncroppedStatus,
  );

  const onBlobLoad = React.useCallback(() => {
    if (liveDedicatedKey.current !== dedicatedKey) {
      return;
    }
    setBlobStatus(LOAD_STATUS.loaded);
  }, [dedicatedKey]);

  const onBlobError = React.useCallback(() => {
    if (liveDedicatedKey.current !== dedicatedKey) {
      return;
    }
    setBlobStatus(LOAD_STATUS.error);
  }, [dedicatedKey]);

  const onCropLoad = React.useCallback(() => {
    if (liveCropKey.current !== cropKey) {
      return;
    }
    setCropStatus(LOAD_STATUS.loaded);
  }, [cropKey]);

  const onCropError = React.useCallback(() => {
    if (liveCropKey.current !== cropKey) {
      return;
    }
    setCropStatus(LOAD_STATUS.error);
  }, [cropKey]);

  const onUncroppedLoad = React.useCallback(() => {
    if (liveUncroppedKey.current !== uncroppedKey) {
      return;
    }
    setUncroppedStatus(LOAD_STATUS.loaded);
  }, [uncroppedKey]);

  const onUncroppedError = React.useCallback(() => {
    if (liveUncroppedKey.current !== uncroppedKey) {
      return;
    }
    setUncroppedStatus(LOAD_STATUS.error);
  }, [uncroppedKey]);

  const display = resolveFaceThumbDisplay(source, {
    blobStatus: nextBlobStatus,
    cropStatus: nextCropStatus,
    uncroppedStatus: nextUncroppedStatus,
  });

  return {
    display,
    onBlobLoad,
    onBlobError,
    onCropLoad,
    onCropError,
    onUncroppedLoad,
    onUncroppedError,
  };
};
