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

export const useDurableFaceThumb = (source: FaceThumbSource): UseDurableFaceThumbResult => {
  const [blobStatus, setBlobStatus] = React.useState<LoadStatus>(LOAD_STATUS.idle);
  const [cropStatus, setCropStatus] = React.useState<LoadStatus>(LOAD_STATUS.idle);
  const [uncroppedStatus, setUncroppedStatus] = React.useState<LoadStatus>(LOAD_STATUS.idle);

  const dedicatedKey = isDedicatedFaceThumbUrl(source.thumbUrl) ? (source.thumbUrl ?? '') : '';
  const cropKey = `${source.attachmentUrl ?? ''}|${source.mediaUrl ?? ''}`;
  const uncroppedKey = `${source.attachmentUrl ?? ''}|${source.mediaUrl ?? ''}|${source.thumbUrl ?? ''}`;

  React.useEffect(() => {
    setBlobStatus(dedicatedKey ? LOAD_STATUS.loading : LOAD_STATUS.idle);
  }, [dedicatedKey]);

  React.useEffect(() => {
    setCropStatus(LOAD_STATUS.idle);
  }, [cropKey]);

  React.useEffect(() => {
    setUncroppedStatus(LOAD_STATUS.idle);
  }, [uncroppedKey]);

  const onBlobLoad = React.useCallback(() => {
    setBlobStatus(LOAD_STATUS.loaded);
  }, []);

  const onBlobError = React.useCallback(() => {
    setBlobStatus(LOAD_STATUS.error);
  }, []);

  const onCropLoad = React.useCallback(() => {
    setCropStatus(LOAD_STATUS.loaded);
  }, []);

  const onCropError = React.useCallback(() => {
    setCropStatus(LOAD_STATUS.error);
  }, []);

  const onUncroppedLoad = React.useCallback(() => {
    setUncroppedStatus(LOAD_STATUS.loaded);
  }, []);

  const onUncroppedError = React.useCallback(() => {
    setUncroppedStatus(LOAD_STATUS.error);
  }, []);

  const display = resolveFaceThumbDisplay(source, { blobStatus, cropStatus, uncroppedStatus });

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
