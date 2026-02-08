import type { MutableRefObject } from 'react';

import type { JobProgress } from '../api/recognition/types/scan';

interface ProgressEventData<TStatus extends string> {
  completed: number;
  total: number;
  status: TStatus;
  phase?: 'queued' | 'detecting' | 'clustering' | 'complete';
  images_processed?: number;
  faces_found?: number;
  clusters_created?: number;
}

interface DoneEventData<TStatus extends string> {
  status: TStatus;
  completed?: number;
  total?: number;
  phase?: 'queued' | 'detecting' | 'clustering' | 'complete';
  images_processed?: number;
  faces_found?: number;
  clusters_created?: number;
}

const parseJson = <T>(payload: string): T | null => {
  try {
    return JSON.parse(payload) as T;
  } catch {
    return null;
  }
};

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

export const parseProgressEvent = <TStatus extends string>(
  payload: string,
  startTimeRef: MutableRefObject<number | null>,
): { progress: JobProgress; status: TStatus; etaSeconds: number | null } | null => {
  const data = parseJson<ProgressEventData<TStatus>>(payload);
  if (!data) {
    return null;
  }

  const now = Date.now();
  if (!startTimeRef.current && data.completed > 0) {
    startTimeRef.current = now;
  }

  const progress: JobProgress = { completed: data.completed, total: data.total };
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

  const etaSeconds =
    startTimeRef.current && data.completed > 0
      ? calcEtaSeconds(now - startTimeRef.current, data.completed, data.total)
      : null;

  return { progress, status: data.status, etaSeconds };
};

export const parseDoneEvent = <TStatus extends string>(
  payload: string,
  latestProgress: JobProgress | null,
): { progress: JobProgress | null; status: TStatus } | null => {
  const data = parseJson<DoneEventData<TStatus>>(payload);
  if (!data) {
    return null;
  }

  if (typeof data.completed === 'number' && typeof data.total === 'number') {
    const progress: JobProgress = {
      completed: data.completed,
      total: data.total,
    };
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
    return { progress, status: data.status };
  }

  if (latestProgress && data.status === 'completed') {
    return {
      progress: {
        completed: latestProgress.total,
        total: latestProgress.total,
      },
      status: data.status,
    };
  }

  return { progress: latestProgress, status: data.status };
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
