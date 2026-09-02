import { useCallback, useEffect, useReducer, useRef, useState } from 'react';

import type { JobProgress } from '../api/recognition/types/scan';
import { getEndpoint, getNonce } from '../api/config';
import { createLogger, logJobEvent } from '../utils/logger';
import {
  JOB_EVENT,
  JOB_MACHINE_STATE,
  JOB_MACHINE_STALL_THRESHOLD_MS,
  initialJobState,
  isTerminalJobState,
  jobReducer,
  type JobMachineStatus,
} from './jobMachine';
import { useJobCoordination } from './useJobCoordination';
import { broadcastJobProgress, parseDoneEvent, parseProgressEvent } from './useJobProgressStreamHelpers';

const log = createLogger('hooks.jobProgressStream');

export const JOB_STATUS = {
  IDLE: JOB_MACHINE_STATE.idle,
  PENDING: JOB_MACHINE_STATE.pending,
  RUNNING: JOB_MACHINE_STATE.running,
  STALLED: JOB_MACHINE_STATE.stalled,
  OFFLINE: JOB_MACHINE_STATE.offline,
  COMPLETED: JOB_MACHINE_STATE.completed,
  COMPLETED_WITH_ERRORS: JOB_MACHINE_STATE.completedWithErrors,
  FAILED: JOB_MACHINE_STATE.failed,
  CLUSTERING: 'clustering',
} as const;

export type JobStatus = (typeof JOB_STATUS)[keyof typeof JOB_STATUS];

/** Map reducer status to the hook view union in one place (sr-007). */
export const toJobStatus = (status: JobMachineStatus): JobStatus => status;

export const getJobProgressStallThresholdMs = (): number => JOB_MACHINE_STALL_THRESHOLD_MS;

export interface JobProgressStream {
  progress: JobProgress | null;
  status: JobStatus;
  isOnline: boolean;
  etaSeconds: number | null;
  isPrimary: boolean;
  lastEventAt: number | null;
  stalledForSeconds: number | null;
  retry: () => void;
}

const streamEventFields = (event: Event): { type: string; readyState?: number } => {
  const fields: { type: string; readyState?: number } = { type: event.type };
  if (event.target instanceof EventSource) {
    fields.readyState = event.target.readyState;
  }
  return fields;
};

const deriveStalledForSeconds = (
  status: JobMachineStatus,
  lastEventAt: number | null,
  now: number,
): number | null =>
  status === JOB_MACHINE_STATE.stalled && lastEventAt !== null
    ? Math.floor((now - lastEventAt) / 1000)
    : null;

/**
 * Hook to connect to the backend SSE endpoint for real-time job progress updates.
 */
export const useJobProgressStream = (jobId: string | null): JobProgressStream => {
  const [connectionNonce, setConnectionNonce] = useState(0);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [machine, dispatch] = useReducer(jobReducer, initialJobState);
  const startTimeRef = useRef<number | null>(null);
  const streamOpenedAtRef = useRef<number | null>(null);
  const progressRef = useRef<JobProgress | null>(null);
  const etaSecondsRef = useRef<number | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const { isPrimary, channel } = useJobCoordination(jobId);

  const status = toJobStatus(machine.status);
  const isOnline = machine.status !== JOB_MACHINE_STATE.offline;
  const lastEventAt = machine.lastEventAt;
  const stalledForSeconds = deriveStalledForSeconds(machine.status, machine.lastEventAt, nowMs);

  const retry = useCallback(() => {
    streamOpenedAtRef.current = Date.now();
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    setConnectionNonce((value) => value + 1);
  }, []);

  useEffect(() => {
    const goOnline = () => {
      dispatch({ type: JOB_EVENT.ONLINE, at: Date.now() });
    };
    const goOffline = () => {
      dispatch({ type: JOB_EVENT.OFFLINE, at: Date.now() });
    };

    window.addEventListener('online', goOnline);
    window.addEventListener('offline', goOffline);
    return () => {
      window.removeEventListener('online', goOnline);
      window.removeEventListener('offline', goOffline);
    };
  }, []);

  useEffect(() => {
    startTimeRef.current = null;
    streamOpenedAtRef.current = null;
    progressRef.current = null;
    etaSecondsRef.current = null;
    if (jobId) {
      dispatch({ type: JOB_EVENT.START, jobId, at: Date.now() });
      if (!navigator.onLine) {
        dispatch({ type: JOB_EVENT.OFFLINE, at: Date.now() });
      }
    } else {
      dispatch({ type: JOB_EVENT.RESET });
    }
  }, [jobId]);

  useEffect(() => {
    if (!jobId || !isOnline || !isPrimary || isTerminalJobState(machine)) {
      return;
    }

    const tick = () => {
      const now = Date.now();
      dispatch({ type: JOB_EVENT.STALL_TICK, now });
      setNowMs(now);
    };

    tick();
    const intervalId = window.setInterval(tick, 1000);
    return () => window.clearInterval(intervalId);
  }, [connectionNonce, isOnline, isPrimary, jobId, machine.status]);

  useEffect(() => {
    if (!channel || isPrimary) {
      return;
    }

    const handleMessage = (event: MessageEvent) => {
      const payload = event.data as {
        type: string;
        payload: { progress: JobProgress | null; status: JobStatus; etaSeconds: number | null };
      };
      if (payload.type !== 'JOB_PROGRESS') {
        return;
      }
      progressRef.current = payload.payload.progress;
      etaSecondsRef.current = payload.payload.etaSeconds;
      const at = Date.now();
      const done = payload.payload.progress?.completed ?? 0;
      const total = payload.payload.progress?.total ?? 0;
      dispatch({ type: JOB_EVENT.PROGRESS, done, total, at });
    };

    channel.addEventListener('message', handleMessage);
    return () => channel.removeEventListener('message', handleMessage);
  }, [channel, isPrimary]);

  useEffect(() => {
    if (!jobId || !isOnline || !isPrimary) {
      return;
    }

    const jobLog = log.child({ jobId });
    const streamUrl = new URL(`${getEndpoint('recognitionJobs')}/${jobId}/stream`, window.location.origin);
    // Live nonce at every (re)connect so post-refresh reconnects carry the new value.
    const nonce = getNonce();
    if (nonce) {
      streamUrl.searchParams.set('_wpnonce', nonce);
    }

    let closed = false;
    streamOpenedAtRef.current = Date.now();
    let eventSource: EventSource | null = new EventSource(streamUrl.toString());
    eventSourceRef.current = eventSource;
    dispatch({ type: JOB_EVENT.STREAM_OPEN, at: streamOpenedAtRef.current });

    const close = () => {
      closed = true;
      eventSource?.close();
      if (eventSourceRef.current === eventSource) {
        eventSourceRef.current = null;
      }
      eventSource = null;
    };

    const emitTerminal = (
      nextStatus: JobStatus,
      nextProgress: JobProgress | null,
      at: number,
      errorMessage?: string,
    ): void => {
      if (nextStatus === JOB_STATUS.COMPLETED_WITH_ERRORS) {
        dispatch({
          type: JOB_EVENT.COMPLETE_WITH_ERRORS,
          at,
        });
      } else if (nextStatus === JOB_STATUS.FAILED) {
        dispatch({
          type: JOB_EVENT.FAIL,
          error: { message: errorMessage ?? 'job stream error' },
        });
      } else {
        dispatch({ type: JOB_EVENT.COMPLETE, at });
      }
      logJobEvent(jobLog, 'stream.done', {
        status: nextStatus,
        jobId,
        done: nextProgress?.completed,
        total: nextProgress?.total,
      });
    };

    eventSource.addEventListener('progress', (event) => {
      if (closed) {
        return;
      }

      const parsed = parseProgressEvent<JobStatus>(event.data as string, startTimeRef);
      if (!parsed) {
        jobLog.error('sse.progress_parse_failed');
        return;
      }

      const receivedAt = Date.now();

      progressRef.current = parsed.progress;
      etaSecondsRef.current = parsed.etaSeconds;
      dispatch({
        type: JOB_EVENT.PROGRESS,
        done: parsed.progress.completed,
        total: parsed.progress.total,
        at: receivedAt,
      });
      broadcastJobProgress(channel, parsed);
    });

    eventSource.addEventListener('done', (event) => {
      if (closed) {
        return;
      }

      const parsed = parseDoneEvent<JobStatus>(event.data as string, progressRef.current);
      if (!parsed) {
        jobLog.error('sse.done_parse_failed');
        return;
      }

      const receivedAt = Date.now();
      progressRef.current = parsed.progress;
      etaSecondsRef.current = null;
      emitTerminal(parsed.status, parsed.progress, receivedAt);
      broadcastJobProgress(channel, {
        progress: parsed.progress,
        status: parsed.status,
        etaSeconds: null,
      });
      close();
    });

    eventSource.addEventListener('error', (event: Event) => {
      if (closed) {
        return;
      }

      if (event instanceof MessageEvent && event.data) {
        try {
          const errorData = JSON.parse(event.data as string) as { message?: string };
          const message = typeof errorData.message === 'string' ? errorData.message : undefined;
          jobLog.error('sse.server_error', { detail: message });
          emitTerminal(JOB_STATUS.FAILED, progressRef.current, Date.now(), message);
          close();
          return;
        } catch {
          // Non-JSON payload; handled below.
        }
      }

      jobLog.warn('sse.connection_error', streamEventFields(event));
    });

    eventSource.onerror = () => {
      if (!closed && eventSource?.readyState === EventSource.CLOSED) {
        jobLog.warn('sse.connection_closed', { readyState: EventSource.CLOSED });
      }
    };

    return () => close();
  }, [channel, connectionNonce, isOnline, isPrimary, jobId]);

  return {
    progress: progressRef.current,
    status,
    isOnline,
    etaSeconds: etaSecondsRef.current,
    isPrimary,
    lastEventAt,
    stalledForSeconds,
    retry,
  };
};
