import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';

import type { JobProgress } from '../api/recognition/types/scan';
import { getEndpoint, getNonce } from '../api/config';
import { createLogger, logJobEvent } from '../utils/logger';
import {
  JOB_EVENT,
  JOB_MACHINE_STALL_THRESHOLD_MS,
  JOB_MACHINE_STATE,
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
  // The WP SSE producer's TERMINAL_JOB_STATUSES includes 'rejected'
  // (class-job-progress-stream-service.php). Omitting it here made emitTerminal's
  // else-branch report a rejected job as completed.
  REJECTED: 'rejected',
  CLUSTERING: 'clustering',
} as const;

export type JobStatus = (typeof JOB_STATUS)[keyof typeof JOB_STATUS];

const JOB_STATUS_VALUES: readonly string[] = Object.values(JOB_STATUS);

/**
 * Explicit validation of untrusted SSE boundary data (sr-005): the parse helpers cast the
 * wire `status` to JobStatus without checking it, so an unknown or absent status must be
 * rejected here rather than falling through a default branch that means "success".
 */
export const isJobStatus = (value: unknown): value is JobStatus =>
  typeof value === 'string' && JOB_STATUS_VALUES.includes(value);

const TERMINAL_JOB_STATUSES: ReadonlySet<JobStatus> = new Set([
  JOB_STATUS.COMPLETED,
  JOB_STATUS.COMPLETED_WITH_ERRORS,
  JOB_STATUS.REJECTED,
  JOB_STATUS.FAILED,
]);

export const isTerminalJobStatus = (status: JobStatus): boolean => TERMINAL_JOB_STATUSES.has(status);

const unreachableStatus = (value: never): never => {
  throw new Error(`Unhandled JobStatus: ${JSON.stringify(value)}`);
};

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
  const [connectionNonce, setConnectionNonce] = useState(0);
  const [machine, dispatch] = useReducer(jobReducer, initialJobState);
  const startTimeRef = useRef<number | null>(null);
  const streamOpenedAtRef = useRef<number | null>(null);
  const progressRef = useRef<JobProgress | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const hasOpenedRef = useRef(false);

  const { isPrimary, channel } = useJobCoordination(jobId);

  const retry = useCallback(() => {
    streamOpenedAtRef.current = Date.now();
    // A fresh transport is being opened: this is the reconnect site the ceiling counts.
    dispatch({ type: JOB_EVENT.RECONNECTING, at: streamOpenedAtRef.current });
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

  const streamIsActive = Boolean(jobId) && isOnline && isPrimary && !isTerminalJobStatus(status);

  useEffect(() => {
    if (!streamIsActive) {
      return;
    }
    const tick = () => dispatch({ type: JOB_EVENT.STALL_TICK, now: Date.now() });
    tick();
    const intervalId = window.setInterval(tick, 1000);
    return () => window.clearInterval(intervalId);
  }, [connectionNonce, streamIsActive]);

  // Derived from the machine rather than a parallel useState slot (FEBT1-W2D-01): the quiet
  // window is (last tick observed) - (last real event), which the machine now preserves
  // because STALL_TICK no longer re-stamps lastEventAt.
  const stalledForSeconds = useMemo<number | null>(() => {
    if (!streamIsActive || machine.status !== JOB_MACHINE_STATE.stalled) {
      return null;
    }
    if (machine.lastEventAt === null || machine.lastTickAt === null) {
      return null;
    }
    const elapsedMs = machine.lastTickAt - machine.lastEventAt;
    return elapsedMs >= getJobProgressStallThresholdMs() ? Math.floor(elapsedMs / 1000) : null;
  }, [machine.lastEventAt, machine.lastTickAt, machine.status, streamIsActive]);

  const lastEventAt = machine.lastEventAt;

  // One wide event per stall entry (OBS-08): a proxy holding the socket OPEN while forwarding
  // nothing previously produced zero log lines while the UI counter climbed.
  const stalledSinceRef = useRef<number | null>(null);
  useEffect(() => {
    if (machine.status !== JOB_MACHINE_STATE.stalled) {
      stalledSinceRef.current = null;
      return;
    }
    if (stalledSinceRef.current === machine.lastEventAt) {
      return;
    }
    stalledSinceRef.current = machine.lastEventAt;
    log.warn('sse.stalled', {
      jobId: machine.jobId ?? undefined,
      quietMs: machine.lastTickAt !== null && machine.lastEventAt !== null
        ? machine.lastTickAt - machine.lastEventAt
        : null,
      reconnectAttempts: machine.reconnectAttempts,
      done: machine.done,
      total: machine.total,
      thresholdMs: getJobProgressStallThresholdMs(),
    });
  }, [machine.done, machine.jobId, machine.lastEventAt, machine.lastTickAt, machine.reconnectAttempts, machine.status, machine.total]);

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
      const broadcastStatus = payload.payload.status;
      if (!isJobStatus(broadcastStatus)) {
        log.warn('sse.broadcast_unknown_status', { status: String(broadcastStatus) });
        return;
      }

      setProgress(payload.payload.progress);
      setStatus(broadcastStatus);
      setEtaSeconds(payload.payload.etaSeconds);
      const at = Date.now();
      const done = payload.payload.progress?.completed ?? 0;
      const total = payload.payload.progress?.total ?? 0;
      // Forcing every broadcast to PROGRESS left secondary tabs permanently 'running' after
      // the primary tab finished or failed (FEBT1G-H-02).
      switch (broadcastStatus) {
        case JOB_STATUS.COMPLETED:
          dispatch({ type: JOB_EVENT.COMPLETE, at });
          break;
        case JOB_STATUS.COMPLETED_WITH_ERRORS:
          dispatch({ type: JOB_EVENT.COMPLETE_WITH_ERRORS, at });
          break;
        case JOB_STATUS.FAILED:
        case JOB_STATUS.REJECTED:
          dispatch({ type: JOB_EVENT.FAIL, error: null });
          break;
        case JOB_STATUS.PENDING:
        case JOB_STATUS.RUNNING:
        case JOB_STATUS.CLUSTERING:
          dispatch({ type: JOB_EVENT.PROGRESS, done, total, at });
          break;
        default:
          unreachableStatus(broadcastStatus);
      }
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

    /**
     * The status set is closed and the default branch is explicit: an unknown or
     * non-terminal status on a terminal frame fails closed instead of silently reporting
     * success (FEBT1G-H-03). No field here is synthesised — `failedCount` is omitted when the
     * wire did not carry one and `error` carries the real server message or null (rg-015).
     */
    const emitTerminal = (
      nextStatus: JobStatus,
      nextProgress: JobProgress | null,
      at: number,
      error: { message: string } | null = null,
    ): void => {
      switch (nextStatus) {
        case JOB_STATUS.COMPLETED:
          dispatch({ type: JOB_EVENT.COMPLETE, at });
          break;
        case JOB_STATUS.COMPLETED_WITH_ERRORS:
          dispatch({ type: JOB_EVENT.COMPLETE_WITH_ERRORS, at });
          break;
        case JOB_STATUS.FAILED:
        case JOB_STATUS.REJECTED:
          dispatch({ type: JOB_EVENT.FAIL, error });
          break;
        case JOB_STATUS.PENDING:
        case JOB_STATUS.RUNNING:
        case JOB_STATUS.CLUSTERING:
          dispatch({
            type: JOB_EVENT.FAIL,
            error: error ?? { message: `Stream ended in non-terminal status "${nextStatus}"` },
          });
          break;
        default:
          unreachableStatus(nextStatus);
      }
      logJobEvent(jobLog, 'stream.done', {
        status: nextStatus,
        jobId,
        done: nextProgress?.completed,
        total: nextProgress?.total,
      });
    };

    const emitUnknownTerminal = (rawStatus: unknown, nextProgress: JobProgress | null): void => {
      jobLog.error('sse.done_unknown_status', { status: String(rawStatus) });
      setStatus(JOB_STATUS.FAILED);
      dispatch({
        type: JOB_EVENT.FAIL,
        error: { message: `Stream reported an unrecognised status "${String(rawStatus)}"` },
      });
      logJobEvent(jobLog, 'stream.done', {
        status: JOB_STATUS.FAILED,
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
        // Expected producer churn (malformed or schema-evolved frame): the stream stays open
        // and later frames still complete the job, so this is not an ERROR (OBS-04).
        jobLog.warn('sse.progress_parse_failed');
        return;
      }
      if (!isJobStatus(parsed.status)) {
        jobLog.warn('sse.progress_unknown_status', { status: String(parsed.status) });
        return;
      }

      const receivedAt = Date.now();

      progressRef.current = parsed.progress;
      setProgress(parsed.progress);
      setStatus(parsed.status);
      setEtaSeconds(parsed.etaSeconds);
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
        // A terminal frame we cannot read is a real failure: nothing else will arrive.
        jobLog.error('sse.done_parse_failed');
        setStatus(JOB_STATUS.FAILED);
        dispatch({ type: JOB_EVENT.FAIL, error: { message: 'Terminal stream frame could not be parsed' } });
        close();
        return;
      }

      const receivedAt = Date.now();
      setProgress(parsed.progress);
      setEtaSeconds(null);

      if (!isJobStatus(parsed.status)) {
        emitUnknownTerminal(parsed.status, parsed.progress);
        close();
        return;
      }

      setStatus(parsed.status);
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
            // Carry the real server message instead of a synthesised literal (rg-015).
            emitTerminal(
              JOB_STATUS.FAILED,
              progressRef.current,
              Date.now(),
              errorData.message ? { message: errorData.message } : null,
            );
            // Secondary tabs were never told about server-error terminals (FEBT1G-H-02).
            broadcastJobProgress(channel, {
              progress: progressRef.current,
              status: JOB_STATUS.FAILED,
              etaSeconds: null,
            });
            close();
            return;
          }
          jobLog.error('sse.server_error', { detail: errorData.message });
        } catch {
          // Non-JSON payload; handled below.
        }
      }

      // Routine EventSource churn: the browser reconnects on its own. Not operator-actionable.
      jobLog.debug('sse.connection_error', streamEventFields(event));
    });

    eventSource.onopen = () => {
      if (closed) {
        return;
      }
      // Every re-open after the first is a real reconnect: clear the breaker (FEBT1-W2D-03).
      if (hasOpenedRef.current) {
        dispatch({ type: JOB_EVENT.RECONNECTED, at: Date.now() });
      }
      hasOpenedRef.current = true;
    };

    eventSource.onerror = () => {
      if (closed) {
        return;
      }
      if (eventSource?.readyState === EventSource.CLOSED) {
        jobLog.debug('sse.connection_closed', { readyState: EventSource.CLOSED });
        return;
      }
      if (eventSource?.readyState === EventSource.CONNECTING) {
        // The browser is re-establishing the transport: this is the other real reconnect site.
        dispatch({ type: JOB_EVENT.RECONNECTING, at: Date.now() });
      }
    };

    return () => close();
  }, [channel, connectionNonce, isOnline, isPrimary, jobId]);

  return { progress, status, isOnline, etaSeconds, isPrimary, lastEventAt, stalledForSeconds, retry };
};
