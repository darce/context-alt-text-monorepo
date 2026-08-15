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

interface KeyedLoadStatus {
  key: string;
  status: LoadStatus;
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

const keyedLoadStatus = (key: string, status: LoadStatus): KeyedLoadStatus => ({ key, status });

const statusForCurrentKey = (keyed: KeyedLoadStatus, currentKey: string): LoadStatus =>
  keyed.key === currentKey ? keyed.status : LOAD_STATUS.loading;

export const useDurableFaceThumb = (source: FaceThumbSource): UseDurableFaceThumbResult => {
  const dedicatedKey = dedicatedKeyFor(source);
  const cropKey = cropKeyFor(source);
  const uncroppedKey = uncroppedKeyFor(source);

  const [blobState, setBlobState] = React.useState<KeyedLoadStatus>(() =>
    keyedLoadStatus(dedicatedKey, dedicatedKey ? LOAD_STATUS.loading : LOAD_STATUS.idle),
  );
  const [cropState, setCropState] = React.useState<KeyedLoadStatus>(() =>
    keyedLoadStatus(cropKey, LOAD_STATUS.idle),
  );
  const [uncroppedState, setUncroppedState] = React.useState<KeyedLoadStatus>(() =>
    keyedLoadStatus(uncroppedKey, LOAD_STATUS.idle),
  );

  const onBlobLoad = React.useCallback(() => {
    setBlobState(keyedLoadStatus(dedicatedKey, LOAD_STATUS.loaded));
  }, [dedicatedKey]);

  const onBlobError = React.useCallback(() => {
    setBlobState(keyedLoadStatus(dedicatedKey, LOAD_STATUS.error));
  }, [dedicatedKey]);

  const onCropLoad = React.useCallback(() => {
    setCropState(keyedLoadStatus(cropKey, LOAD_STATUS.loaded));
  }, [cropKey]);

  const onCropError = React.useCallback(() => {
    setCropState(keyedLoadStatus(cropKey, LOAD_STATUS.error));
  }, [cropKey]);

  const onUncroppedLoad = React.useCallback(() => {
    setUncroppedState(keyedLoadStatus(uncroppedKey, LOAD_STATUS.loaded));
  }, [uncroppedKey]);

  const onUncroppedError = React.useCallback(() => {
    setUncroppedState(keyedLoadStatus(uncroppedKey, LOAD_STATUS.error));
  }, [uncroppedKey]);

  const display = resolveFaceThumbDisplay(source, {
    blobStatus: statusForCurrentKey(blobState, dedicatedKey),
    cropStatus: statusForCurrentKey(cropState, cropKey),
    uncroppedStatus: statusForCurrentKey(uncroppedState, uncroppedKey),
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
