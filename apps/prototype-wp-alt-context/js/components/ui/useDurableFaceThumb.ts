import * as React from 'react';

import {
  LOAD_STATUS,
  resolveFaceThumbDisplay,
  type FaceThumbDisplay,
  type FaceThumbSource,
  type LoadStatus,
} from './faceThumbDisplay';

export interface UseDurableFaceThumbResult {
  display: FaceThumbDisplay;
  onBlobLoad: () => void;
  onBlobError: () => void;
  onCropLoad: () => void;
  onCropError: () => void;
}

export const useDurableFaceThumb = (source: FaceThumbSource): UseDurableFaceThumbResult => {
  const [blobStatus, setBlobStatus] = React.useState<LoadStatus>(LOAD_STATUS.idle);
  const [cropStatus, setCropStatus] = React.useState<LoadStatus>(LOAD_STATUS.idle);

  const thumbKey = source.thumbUrl ?? '';
  const cropKey = `${source.attachmentUrl ?? ''}|${source.mediaUrl ?? ''}`;

  React.useEffect(() => {
    setBlobStatus(thumbKey ? LOAD_STATUS.loading : LOAD_STATUS.idle);
  }, [thumbKey]);

  React.useEffect(() => {
    setCropStatus(cropKey ? LOAD_STATUS.idle : LOAD_STATUS.idle);
  }, [cropKey]);

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

  const display = resolveFaceThumbDisplay(source, { blobStatus, cropStatus });

  return { display, onBlobLoad, onBlobError, onCropLoad, onCropError };
};
