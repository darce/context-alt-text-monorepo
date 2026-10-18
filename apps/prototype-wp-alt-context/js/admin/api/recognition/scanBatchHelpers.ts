import { getConfig } from '../config';

const MULTIPART_MAX_IMAGES = 5;

export const getEffectiveBatchSize = (): number => {
  const configured = getConfig().maxMediaPerBatch;
  if (!Number.isFinite(configured) || configured <= 0) {
    return MULTIPART_MAX_IMAGES;
  }

  return Math.min(configured, MULTIPART_MAX_IMAGES);
};

export const chunkMediaIds = (mediaIds: number[], size: number): number[][] => {
  if (size <= 0) {
    return [mediaIds];
  }

  const batches: number[][] = [];
  for (let index = 0; index < mediaIds.length; index += size) {
    batches.push(mediaIds.slice(index, index + size));
  }
  return batches;
};

export const createBatchRunId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  return `batch-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
};
