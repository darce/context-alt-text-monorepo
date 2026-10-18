import type { MutableRefObject } from 'react';

import type { JobProgress } from '../api/recognition/types/scan';
import { isScanSuccessStatus } from './jobStateMachineUtils';

interface SseProgressFields {
  phase?: 'queued' | 'detecting' | 'clustering' | 'retrying' | 'awaiting_projection' | 'failed' | 'complete';
  /**
   * Real per-item failure count from the producer. `build_stream_progress_payload()` in
   * class-job-progress-stream-service.php emits `items_failed` (absint) on both the
   * progress and the done frame; it is the only wire source for the count that *defines*
   * `completed_with_errors` (FEBT1-LA-03).
   */
  items_failed?: number;
  failure_reason?: string;
  images_processed?: number;
  faces_found?: number;
  clusters_created?: number;
  retry_count?: number;
  current_stage?: string;
  last_successful_processed_identities?: number;
  last_error_code?: string;
}

interface ProgressEventData<TStatus extends string> extends SseProgressFields {
  completed: number;
  total: number;
  status: TStatus;
}

interface DoneEventData<TStatus extends string> extends SseProgressFields {
  status: TStatus;
  completed?: number;
  total?: number;
}

/**
 * Why a frame could not be turned into state. A malformed frame on the wire (`json`) and a
 * producer/consumer contract drift (`schema`) have different operational meanings and
 * different owners, so they must be distinguishable in the logs (FEBT1-LA-04, OBS-02).
 * Tagged-union failure classification ported from utils/appError.ts:37 (`_tag`).
 */
export type ProgressParseFailureReason = 'json' | 'schema';

export type ParsedProgressEvent<TStatus extends string> =
  | { readonly ok: true; readonly progress: JobProgress; readonly status: TStatus; readonly etaSeconds: number | null }
  | { readonly ok: false; readonly reason: ProgressParseFailureReason };

const parseJson = <T>(payload: string): T | null => {
  try {
    return JSON.parse(payload) as T;
  } catch {
    return null;
  }
};

/** sr-005: untrusted wire counts must be finite non-negative numbers before they reach state. */
const asCount = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;

const calcEtaSeconds = (elapsedMs: number, completed: number, total: number): number | null => {
  if (completed <= 0 || completed >= total) {
    return null;
  }
  const rate = completed / elapsedMs;
  if (!Number.isFinite(rate) || rate <= 0) {
    return null;
  }
  const remainingItems = total - completed;
  return Math.round(remainingItems / rate / 1000);
};

const copyOptionalProgressFields = (data: SseProgressFields, progress: JobProgress): void => {
  if (data.phase) {
    progress.phase = data.phase;
  }
  if (typeof data.images_processed === 'number') {
    progress.images_processed = data.images_processed;
  }
  if (typeof data.faces_found === 'number') {
    progress.faces_found = data.faces_found;
  }
  if (typeof data.clusters_created === 'number') {
    progress.clusters_created = data.clusters_created;
  }
  if (typeof data.retry_count === 'number') {
    progress.retry_count = data.retry_count;
  }
  if (typeof data.current_stage === 'string') {
    progress.current_stage = data.current_stage;
  }
  if (typeof data.last_successful_processed_identities === 'number') {
    progress.last_successful_processed_identities = data.last_successful_processed_identities;
  }
  if (typeof data.last_error_code === 'string') {
    progress.last_error_code = data.last_error_code;
  }
};

export const parseProgressEvent = <TStatus extends string>(
  payload: string,
  startTimeRef: MutableRefObject<number | null>,
): ParsedProgressEvent<TStatus> => {
  const data = parseJson<ProgressEventData<TStatus>>(payload);
  if (!data) {
    return { ok: false, reason: 'json' };
  }

  // Validate the untrusted SSE boundary (sr-005): a malformed/schema-evolved event with
  // non-numeric completed/total must not pollute JobProgress with NaN (which then poisons
  // the monotonic-progress cache for the whole run).
  if (
    typeof data.completed !== 'number' ||
    !Number.isFinite(data.completed) ||
    typeof data.total !== 'number' ||
    !Number.isFinite(data.total)
  ) {
    return { ok: false, reason: 'schema' };
  }

  const now = Date.now();
  if (!startTimeRef.current && data.completed > 0) {
    startTimeRef.current = now;
  }

  const progress: JobProgress = { completed: data.completed, total: data.total };
  copyOptionalProgressFields(data, progress);

  const etaSeconds =
    startTimeRef.current && data.completed > 0
      ? calcEtaSeconds(now - startTimeRef.current, data.completed, data.total)
      : null;

  return { ok: true, progress, status: data.status, etaSeconds };
};

export const parseDoneEvent = <TStatus extends string>(
  payload: string,
  latestProgress: JobProgress | null,
): { progress: JobProgress | null; status: TStatus; failedCount?: number } | null => {
  const data = parseJson<DoneEventData<TStatus>>(payload);
  if (!data) {
    return null;
  }

  // Present only when the producer sent it: an absent `items_failed` must stay absent
  // rather than becoming a fabricated 0 (rg-015, FEBT1-W2D-05).
  const failedCount = asCount(data.items_failed);
  const withFailedCount = <T extends object>(result: T): T & { failedCount?: number } =>
    failedCount === undefined ? result : { ...result, failedCount };

  if (typeof data.completed === 'number' && typeof data.total === 'number') {
    const progress: JobProgress = {
      completed: data.completed,
      total: data.total,
    };
    copyOptionalProgressFields(data, progress);
    return withFailedCount({ progress, status: data.status });
  }

  if (latestProgress && isScanSuccessStatus(data.status)) {
    return withFailedCount({
      progress: {
        completed: latestProgress.total,
        total: latestProgress.total,
      },
      status: data.status,
    });
  }

  return withFailedCount({ progress: latestProgress, status: data.status });
};

export const broadcastJobProgress = <TStatus extends string>(
  channel: BroadcastChannel | null,
  payload: { progress: JobProgress | null; status: TStatus; etaSeconds: number | null },
): void => {
  channel?.postMessage({
    type: 'JOB_PROGRESS',
    payload,
  });
};
