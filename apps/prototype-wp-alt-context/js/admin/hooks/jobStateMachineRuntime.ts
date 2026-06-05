import type { BatchRunStatus, JobProgress, JobStatusResponse } from '../api/recognition/types/scan';
import type { JobStatus } from './useJobProgressStream';

/**
 * Clamp progress counters so a later snapshot for the same run cannot regress
 * displayed values when SSE fallback aggregation or batch-run polling drops a
 * count. The guard is per-run; callers must reset `prev` to null when the run
 * identity changes (new scan/batch-run id).
 */
export const enforceMonotonicProgress = (
  prev: JobProgress | null,
  next: JobProgress | null,
): JobProgress | null => {
  if (!next) {
    return prev ?? next;
  }
  if (!prev) {
    return next;
  }
  const completed = Math.max(prev.completed, next.completed);
  const imagesProcessedSource = next.images_processed ?? next.completed;
  const prevImagesProcessed = prev.images_processed ?? prev.completed;
  const imagesProcessed = Math.max(prevImagesProcessed, imagesProcessedSource);
  const result: JobProgress = {
    ...next,
    completed,
  };
  if (typeof next.images_processed === 'number' || typeof prev.images_processed === 'number') {
    result.images_processed = imagesProcessed;
  }
  if (typeof next.faces_found === 'number' || typeof prev.faces_found === 'number') {
    result.faces_found = Math.max(prev.faces_found ?? 0, next.faces_found ?? 0);
  }
  return result;
};

interface ScanRunningParams {
  scanPending: boolean;
  waitingForCompletion: boolean;
  activeJobIds: string[];
  sseStatus: JobStatus;
  scanStatus: JobStatusResponse | undefined;
  batchRunStatus?: BatchRunStatus;
}

export const isScanRunning = ({
  scanPending,
  waitingForCompletion,
  activeJobIds,
  sseStatus,
  scanStatus,
  batchRunStatus,
}: ScanRunningParams): boolean => {
  if (scanPending || waitingForCompletion) {
    return true;
  }
  if (batchRunStatus && !batchRunStatus.terminal_state) {
    return true;
  }
  if (activeJobIds.length > 0) {
    return sseStatus === 'pending' || sseStatus === 'running';
  }
  const status = scanStatus?.status;
  return status === 'pending' || status === 'running';
};
