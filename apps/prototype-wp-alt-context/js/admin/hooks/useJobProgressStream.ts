import { useCallback, useEffect, useRef, useState } from 'react';

import type { JobProgress } from '../api/recognition/types/scan';
import { getConfig, getEndpoint } from '../api/config';
import { useJobCoordination } from './useJobCoordination';
import { broadcastJobProgress, parseDoneEvent, parseProgressEvent } from './useJobProgressStreamHelpers';

export const JOB_STATUS = {
  PENDING: 'pending',
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CLUSTERING: 'clustering',
} as const;

export type JobStatus = (typeof JOB_STATUS)[keyof typeof JOB_STATUS];

export const JOB_PROGRESS_STALL_THRESHOLD_MS = 30_000;

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
    const goOnline = () => setIsOnline(true);
    const goOffline = () => setIsOnline(false);

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
  }, [jobId]);

  useEffect(() => {
    if (!jobId || !isOnline || !isPrimary) {
      setStalledForSeconds(null);
      return;
    }

    if (status === JOB_STATUS.COMPLETED || status === JOB_STATUS.FAILED) {
      setStalledForSeconds(null);
      return;
    }

    const updateStallState = () => {
      const baseline = lastEventAt ?? streamOpenedAtRef.current;
      if (!baseline) {
        setStalledForSeconds(null);
        return;
      }

      const elapsedMs = Date.now() - baseline;
      setStalledForSeconds(elapsedMs >= JOB_PROGRESS_STALL_THRESHOLD_MS ? Math.floor(elapsedMs / 1000) : null);
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

    const streamUrl = new URL(`${getEndpoint('recognitionJobs')}/${jobId}/stream`, window.location.origin);
    const nonce = getConfig().nonce;
    if (nonce) {
      streamUrl.searchParams.set('_wpnonce', nonce);
    }

    let closed = false;
    streamOpenedAtRef.current = Date.now();
    let eventSource: EventSource | null = new EventSource(streamUrl.toString());
    eventSourceRef.current = eventSource;

    const close = () => {
      closed = true;
      eventSource?.close();
      if (eventSourceRef.current === eventSource) {
        eventSourceRef.current = null;
      }
      eventSource = null;
    };

    eventSource.addEventListener('progress', (event) => {
      if (closed) {
        return;
      }

      const parsed = parseProgressEvent<JobStatus>(event.data as string, startTimeRef);
      if (!parsed) {
        console.error('Failed to parse SSE progress data');
        return;
      }

      const receivedAt = Date.now();

      progressRef.current = parsed.progress;
      setProgress(parsed.progress);
      setStatus(parsed.status);
      setEtaSeconds(parsed.etaSeconds);
      setLastEventAt(receivedAt);
      setStalledForSeconds(null);
      broadcastJobProgress(channel, parsed);
    });

    eventSource.addEventListener('done', (event) => {
      if (closed) {
        return;
      }

      const parsed = parseDoneEvent<JobStatus>(event.data as string, progressRef.current);
      if (!parsed) {
        console.error('Failed to parse SSE done data');
        return;
      }

      setLastEventAt(Date.now());

      setStatus(parsed.status);
      setProgress(parsed.progress);
      setEtaSeconds(null);
      setStalledForSeconds(null);
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
            close();
            return;
          }
          console.error('SSE server error:', errorData.message);
        } catch {
          // Non-JSON payload; handled below.
        }
      }

      console.warn('SSE connection error, will auto-reconnect...', event);
    });

    eventSource.onerror = () => {
      if (!closed && eventSource?.readyState === EventSource.CLOSED) {
        console.warn('SSE connection closed unexpectedly');
      }
    };

    return () => close();
  }, [channel, connectionNonce, isOnline, isPrimary, jobId]);

  return { progress, status, isOnline, etaSeconds, isPrimary, lastEventAt, stalledForSeconds, retry };
};
