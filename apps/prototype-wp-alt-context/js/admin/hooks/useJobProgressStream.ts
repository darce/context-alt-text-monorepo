import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';

import type { JobProgress } from '../api/recognition/types/scan';
import { getEndpoint, getNonce } from '../api/config';
import {
  createLogger,
  logJobEvent,
  newRequestId,
  redactEndpoint,
  withRequestId,
  type Logger,
} from '../utils/logger';
import {
  JOB_EVENT,
  JOB_MACHINE_STALL_THRESHOLD_MS,
  JOB_STATUS,
  initialJobState,
  isTerminalJobStatus,
  isWireJobStatus,
  jobReducer,
  projectWireStatus,
  type JobEvent,
  type WireJobStatus,
} from './jobMachine';
import { useJobCoordination } from './useJobCoordination';
import { broadcastJobProgress, parseDoneEvent, parseProgressEvent } from './useJobProgressStreamHelpers';

const log = createLogger('hooks.jobProgressStream');

// One vocabulary, one owner (FEBT1-LA-05, REF-26): the status map and its predicates live in
// jobMachine.ts and are re-exported here only so existing importers keep one import site.
export { JOB_STATUS, isTerminalJobStatus, isWireJobStatus };
export type { JobStatus, WireJobStatus } from './jobMachine';

const unreachableStatus = (value: never): never => {
  throw new Error(`Unhandled JobStatus: ${JSON.stringify(value)}`);
};

export const getJobProgressStallThresholdMs = (): number => JOB_MACHINE_STALL_THRESHOLD_MS;

export interface JobProgressStream {
  progress: JobProgress | null;
  status: WireJobStatus;
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
 * The single wire-status -> machine-event mapping (FEBT1-LA-05). Both the SSE frame handlers
 * and the BroadcastChannel observer path route through it, so a secondary tab and the primary
 * tab can no longer disagree about what a status means.
 */
const jobEventForWireStatus = (
  status: WireJobStatus,
  fields: {
    readonly done: number;
    readonly total: number;
    readonly at: number;
    readonly failedCount?: number;
    readonly error?: { message: string } | null;
  },
): JobEvent => {
  switch (status) {
    case JOB_STATUS.PENDING:
    case JOB_STATUS.RUNNING:
    case JOB_STATUS.CLUSTERING:
      return { type: JOB_EVENT.PROGRESS, status, done: fields.done, total: fields.total, at: fields.at };
    case JOB_STATUS.COMPLETED:
      return { type: JOB_EVENT.COMPLETE, at: fields.at };
    case JOB_STATUS.COMPLETED_WITH_ERRORS:
      return fields.failedCount === undefined
        ? { type: JOB_EVENT.COMPLETE_WITH_ERRORS, at: fields.at }
        : { type: JOB_EVENT.COMPLETE_WITH_ERRORS, failedCount: fields.failedCount, at: fields.at };
    case JOB_STATUS.FAILED:
      return { type: JOB_EVENT.FAIL, error: fields.error ?? null };
    case JOB_STATUS.REJECTED:
      return { type: JOB_EVENT.REJECT, error: fields.error ?? null };
    default:
      return unreachableStatus(status);
  }
};

/**
 * Hook to connect to the backend SSE endpoint for real-time job progress updates.
 */
export const useJobProgressStream = (jobId: string | null): JobProgressStream => {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [etaSeconds, setEtaSeconds] = useState<number | null>(null);
  const [connectionNonce, setConnectionNonce] = useState(0);
  const [machine, dispatch] = useReducer(jobReducer, initialJobState);
  const startTimeRef = useRef<number | null>(null);
  const streamOpenedAtRef = useRef<number | null>(null);
  const progressRef = useRef<JobProgress | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const hasOpenedRef = useRef(false);
  // One correlation id per SSE unit of work (OBS-03). A module-scope logger mints its
  // requestId once at import time, which correlates "which module", not "which job".
  const jobRequestIdRef = useRef<string | null>(null);
  const jobStartedAtRef = useRef<number | null>(null);

  const { isPrimary, channel } = useJobCoordination(jobId);

  // Single source of truth (FEBT1-LA-05): the returned status is a projection of the machine,
  // not a parallel useState slot that the machine and the SSE handlers both wrote to.
  const status = useMemo<WireJobStatus>(() => projectWireStatus(machine), [machine]);

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
    setEtaSeconds(null);
    startTimeRef.current = null;
    streamOpenedAtRef.current = null;
    progressRef.current = null;
    jobRequestIdRef.current = jobId ? newRequestId() : null;
    jobStartedAtRef.current = jobId ? Date.now() : null;
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
    if (!streamIsActive || machine.status !== JOB_STATUS.STALLED) {
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
    if (machine.status !== JOB_STATUS.STALLED) {
      stalledSinceRef.current = null;
      return;
    }
    if (stalledSinceRef.current === machine.lastEventAt) {
      return;
    }
    stalledSinceRef.current = machine.lastEventAt;
    log.warn('sse.stalled', {
      jobId: machine.jobId ?? undefined,
      requestId: jobRequestIdRef.current ?? undefined,
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
        payload: { progress: JobProgress | null; status: WireJobStatus; etaSeconds: number | null };
      };
      if (payload.type !== 'JOB_PROGRESS') {
        return;
      }
      const broadcastStatus = payload.payload.status;
      if (!isWireJobStatus(broadcastStatus)) {
        log.warn('sse.broadcast_unknown_status', { status: String(broadcastStatus) });
        return;
      }

      setProgress(payload.payload.progress);
      setEtaSeconds(payload.payload.etaSeconds);
      // Forcing every broadcast to PROGRESS left secondary tabs permanently 'running' after
      // the primary tab finished or failed (FEBT1G-H-02).
      dispatch(
        jobEventForWireStatus(broadcastStatus, {
          done: payload.payload.progress?.completed ?? 0,
          total: payload.payload.progress?.total ?? 0,
          at: Date.now(),
        }),
      );
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

    const jobLog: Logger = withRequestId(log.child({ jobId }), jobRequestIdRef.current ?? newRequestId());
    const endpoint = `${getEndpoint('recognitionJobs')}/${jobId}/stream`;
    const streamUrl = new URL(endpoint, window.location.origin);
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

    // OBS-01/OBS-02: the SSE job lifetime is a unit of work, so it opens with one wide,
    // correlated record instead of being visible only when it fails. The nonce never
    // reaches the log — only the pathname does.
    jobLog.info('stream.open', {
      event: 'stream.open',
      jobId,
      endpoint: redactEndpoint(streamUrl.toString()),
      connectionNonce,
      reconnectAttempts: machine.reconnectAttempts,
    });

    const close = () => {
      closed = true;
      eventSource?.close();
      if (eventSourceRef.current === eventSource) {
        eventSourceRef.current = null;
      }
      eventSource = null;
    };

    const streamDurationMs = (): number | null =>
      jobStartedAtRef.current === null ? null : Date.now() - jobStartedAtRef.current;

    /**
     * The status set is closed and the non-terminal branch is explicit: a non-terminal status
     * on a terminal frame fails closed instead of silently reporting success (FEBT1G-H-03).
     * No field here is synthesised — `failedCount` is omitted when the wire did not carry one
     * and `error` carries the real server message or null (rg-015).
     */
    const emitTerminal = (
      nextStatus: WireJobStatus,
      nextProgress: JobProgress | null,
      at: number,
      error: { message: string } | null = null,
      failedCount?: number,
    ): void => {
      const terminalStatus: WireJobStatus = isTerminalJobStatus(nextStatus) ? nextStatus : JOB_STATUS.FAILED;
      const terminalError = isTerminalJobStatus(nextStatus)
        ? error
        : (error ?? { message: `Stream ended in non-terminal status "${nextStatus}"` });
      dispatch(
        jobEventForWireStatus(terminalStatus, {
          done: nextProgress?.completed ?? 0,
          total: nextProgress?.total ?? 0,
          at,
          error: terminalError,
          failedCount,
        }),
      );
      // The wide record for the SSE unit of work (OBS-02): outcome, size, duration and
      // reconnect count on ONE line. `logJobEvent` owns the closed lifecycle fields; the
      // request-scoped dimensions ride on a child logger rather than widening that contract.
      logJobEvent(
        jobLog.child({ durationMs: streamDurationMs(), reconnectAttempts: machine.reconnectAttempts }),
        'stream.done',
        { status: terminalStatus, jobId, done: nextProgress?.completed, total: nextProgress?.total, failedCount },
      );
    };

    const emitUnknownTerminal = (rawStatus: unknown, nextProgress: JobProgress | null): void => {
      jobLog.error('sse.done_unknown_status', { status: String(rawStatus) });
      dispatch({
        type: JOB_EVENT.FAIL,
        error: { message: `Stream reported an unrecognised status "${String(rawStatus)}"` },
      });
      logJobEvent(
        jobLog.child({ durationMs: streamDurationMs(), reconnectAttempts: machine.reconnectAttempts }),
        'stream.done',
        { status: JOB_STATUS.FAILED, jobId, done: nextProgress?.completed, total: nextProgress?.total },
      );
    };

    eventSource.addEventListener('progress', (event) => {
      if (closed) {
        return;
      }

      const parsed = parseProgressEvent<string>(event.data as string, startTimeRef);
      if (!parsed.ok) {
        // Expected producer churn (malformed or schema-evolved frame): the stream stays open
        // and later frames still complete the job, so this is not an ERROR (OBS-04). The
        // reason discriminates a bad frame on the wire from contract drift (FEBT1-LA-04).
        jobLog.warn('sse.progress_parse_failed', { reason: parsed.reason });
        return;
      }
      if (!isWireJobStatus(parsed.status)) {
        jobLog.warn('sse.progress_unknown_status', { status: String(parsed.status) });
        return;
      }

      const receivedAt = Date.now();

      progressRef.current = parsed.progress;
      setProgress(parsed.progress);
      setEtaSeconds(parsed.etaSeconds);
      dispatch(
        jobEventForWireStatus(parsed.status, {
          done: parsed.progress.completed,
          total: parsed.progress.total,
          at: receivedAt,
        }),
      );
      broadcastJobProgress(channel, {
        progress: parsed.progress,
        status: parsed.status,
        etaSeconds: parsed.etaSeconds,
      });
    });

    eventSource.addEventListener('done', (event) => {
      if (closed) {
        return;
      }

      const parsed = parseDoneEvent<string>(event.data as string, progressRef.current);
      if (!parsed) {
        // A terminal frame we cannot read is a real failure: nothing else will arrive.
        jobLog.error('sse.done_parse_failed');
        dispatch({ type: JOB_EVENT.FAIL, error: { message: 'Terminal stream frame could not be parsed' } });
        close();
        return;
      }

      const receivedAt = Date.now();
      setProgress(parsed.progress);
      setEtaSeconds(null);

      if (!isWireJobStatus(parsed.status)) {
        emitUnknownTerminal(parsed.status, parsed.progress);
        close();
        return;
      }

      emitTerminal(parsed.status, parsed.progress, receivedAt, null, parsed.failedCount);
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
    // `machine.reconnectAttempts` is read for log dimensions only; re-opening the transport
    // on every counter change would defeat the reconnect ceiling it reports.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel, connectionNonce, isOnline, isPrimary, jobId]);

  return { progress, status, isOnline, etaSeconds, isPrimary, lastEventAt, stalledForSeconds, retry };
};
