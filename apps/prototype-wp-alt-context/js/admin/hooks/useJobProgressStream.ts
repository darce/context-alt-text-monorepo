import { useCallback, useEffect, useReducer, useRef, useState } from 'react';

import type { JobProgress } from '../api/recognition/types/scan';
import { getEndpoint, getNonce } from '../api/config';
import { createLogger, logJobEvent } from '../utils/logger';
import {
  JOB_EVENT,
  JOB_MACHINE_STALL_THRESHOLD_MS,
  initialJobState,
  jobReducer,
} from './jobMachine';
import { useJobCoordination } from './useJobCoordination';
import { broadcastJobProgress, parseDoneEvent, parseProgressEvent } from './useJobProgressStreamHelpers';

const log = createLogger('hooks.jobProgressStream');

export const JOB_STATUS = {
  PENDING: 'pending',
  RUNNING: 'running',
  COMPLETED: 'completed',
  // Terminal partial-success the WP SSE producer forwards verbatim from the description-service
  // (some items succeeded, some failed). Must be recognized as terminal on the SSE channel too.
  COMPLETED_WITH_ERRORS: 'completed_with_errors',
  FAILED: 'failed',
  CLUSTERING: 'clustering',
} as const;

export type JobStatus = (typeof JOB_STATUS)[keyof typeof JOB_STATUS];

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

/**
 * Hook to connect to the backend SSE endpoint for real-time job progress updates.
 */
export const useJobProgressStream = (jobId: string | null): JobProgressStream => {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [status, setStatus] = useState<JobStatus>(JOB_STATUS.PENDING);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [etaSeconds, setEtaSeconds] = useState<number | null>(null);
  const [lastEventAt, setLastEventAt] = useState<number | null>(null);
  const [stalledForSeconds, setStalledForSeconds] = useState<number | null>(null);
  const [connectionNonce, setConnectionNonce] = useState(0);
  const [, dispatch] = useReducer(jobReducer, initialJobState);
  const startTimeRef = useRef<number | null>(null);
  const streamOpenedAtRef = useRef<number | null>(null);
  const progressRef = useRef<JobProgress | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const { isPrimary, channel } = useJobCoordination(jobId);

  const retry = useCallback(() => {
    setLastEventAt(null);
    setStalledForSeconds(null);
    streamOpenedAtRef.current = Date.now();
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    setConnectionNonce((value) => value + 1);
  }, []);

  useEffect(() => {
    const goOnline = () => {
      setIsOnline(true);
      dispatch({ type: JOB_EVENT.ONLINE, at: Date.now() });
    };
    const goOffline = () => {
      setIsOnline(false);
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
    setProgress(null);
    setStatus(JOB_STATUS.PENDING);
    setEtaSeconds(null);
    setLastEventAt(null);
    setStalledForSeconds(null);
    startTimeRef.current = null;
    streamOpenedAtRef.current = null;
    progressRef.current = null;
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
    if (!jobId || !isOnline || !isPrimary) {
      setStalledForSeconds(null);
      return;
    }

    if (
      status === JOB_STATUS.COMPLETED ||
      status === JOB_STATUS.COMPLETED_WITH_ERRORS ||
      status === JOB_STATUS.FAILED
    ) {
      setStalledForSeconds(null);
      return;
    }

    const stallThresholdMs = getJobProgressStallThresholdMs();
    const updateStallState = () => {
      const now = Date.now();
      dispatch({ type: JOB_EVENT.STALL_TICK, now });
      const baseline = lastEventAt ?? streamOpenedAtRef.current;
      if (!baseline) {
        setStalledForSeconds(null);
        return;
      }

      const elapsedMs = now - baseline;
      setStalledForSeconds(elapsedMs >= stallThresholdMs ? Math.floor(elapsedMs / 1000) : null);
    };

    updateStallState();
    const intervalId = window.setInterval(updateStallState, 1000);
    return () => window.clearInterval(intervalId);
  }, [connectionNonce, isOnline, isPrimary, jobId, lastEventAt, status]);

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
      setProgress(payload.payload.progress);
      setStatus(payload.payload.status);
      setEtaSeconds(payload.payload.etaSeconds);
      const at = Date.now();
      const done = payload.payload.progress?.completed ?? 0;
      const total = payload.payload.progress?.total ?? 0;
      dispatch({ type: JOB_EVENT.PROGRESS, done, total, at });
    };

    channel.addEventListener('message', handleMessage);
    return () => channel.removeEventListener('message', handleMessage);
  }, [channel, isPrimary]);

  useEffect(() => {
    progressRef.current = progress;
  }, [progress]);

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

    const emitTerminal = (nextStatus: JobStatus, nextProgress: JobProgress | null, at: number): void => {
      if (nextStatus === JOB_STATUS.COMPLETED_WITH_ERRORS) {
        dispatch({
          type: JOB_EVENT.COMPLETE_WITH_ERRORS,
          failedCount: 0,
          at,
        });
      } else if (nextStatus === JOB_STATUS.FAILED) {
        dispatch({ type: JOB_EVENT.FAIL, error: { message: 'stream failed' } });
      } else {
        dispatch({ type: JOB_EVENT.COMPLETE, at });
      }
      logJobEvent(jobLog, 'stream.done', {
        status: nextStatus,
        jobId,
        done: nextProgress?.completed,
        total: nextProgress?.total,
        failedCount: nextStatus === JOB_STATUS.FAILED ? 1 : undefined,
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
      setProgress(parsed.progress);
      setStatus(parsed.status);
      setEtaSeconds(parsed.etaSeconds);
      setLastEventAt(receivedAt);
      setStalledForSeconds(null);
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
      setLastEventAt(receivedAt);

      setStatus(parsed.status);
      setProgress(parsed.progress);
      setEtaSeconds(null);
      setStalledForSeconds(null);
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
          if (errorData.message?.includes('not found')) {
            setStatus(JOB_STATUS.FAILED);
            emitTerminal(JOB_STATUS.FAILED, progressRef.current, Date.now());
            close();
            return;
          }
          jobLog.error('sse.server_error', { detail: errorData.message });
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

  return { progress, status, isOnline, etaSeconds, isPrimary, lastEventAt, stalledForSeconds, retry };
};
