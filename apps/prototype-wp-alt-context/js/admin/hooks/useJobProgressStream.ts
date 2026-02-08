import { useEffect, useRef, useState } from 'react';

import type { JobProgress } from '../api/recognition/types/scan';
import { getConfig, getEndpoint } from '../api/config';
import { useJobCoordination } from './useJobCoordination';
import { broadcastJobProgress, parseDoneEvent, parseProgressEvent } from './useJobProgressStreamHelpers';

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'clustering';

export interface JobProgressStream {
  progress: JobProgress | null;
  status: JobStatus;
  isOnline: boolean;
  etaSeconds: number | null;
  isPrimary: boolean;
}

/**
 * Hook to connect to the backend SSE endpoint for real-time job progress updates.
 */
export const useJobProgressStream = (jobId: string | null): JobProgressStream => {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [status, setStatus] = useState<JobStatus>('pending');
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [etaSeconds, setEtaSeconds] = useState<number | null>(null);
  const startTimeRef = useRef<number | null>(null);
  const progressRef = useRef<JobProgress | null>(null);

  const { isPrimary, channel } = useJobCoordination(jobId);

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
    setStatus('pending');
    setEtaSeconds(null);
    startTimeRef.current = null;
    progressRef.current = null;
  }, [jobId]);

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
    let eventSource: EventSource | null = new EventSource(streamUrl.toString());

    const close = () => {
      closed = true;
      eventSource?.close();
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

      progressRef.current = parsed.progress;
      setProgress(parsed.progress);
      setStatus(parsed.status);
      setEtaSeconds(parsed.etaSeconds);
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

      setStatus(parsed.status);
      setProgress(parsed.progress);
      setEtaSeconds(null);
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
            setStatus('failed');
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
  }, [jobId, isOnline, isPrimary, channel]);

  return { progress, status, isOnline, etaSeconds, isPrimary };
};
