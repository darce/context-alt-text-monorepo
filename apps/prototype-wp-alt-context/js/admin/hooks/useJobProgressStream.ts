import { useState, useEffect, useRef } from 'react';
import { useJobCoordination } from './useJobCoordination';
import type { JobProgress } from '../api/recognition/types/scan';

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
 *
 * @param jobId - The UUID of the job to track.
 * @returns {JobProgressStream} Real-time progress and status.
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
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Reset state when jobId changes
  useEffect(() => {
    setProgress(null);
    setStatus('pending');
    setEtaSeconds(null);
    startTimeRef.current = null;
    progressRef.current = null;
  }, [jobId]);

  // Handle incoming broadcasted events for non-primary tabs
  useEffect(() => {
    if (!channel || isPrimary) {
      return;
    }

    const handleMessage = (event: MessageEvent) => {
      const { type, payload } = event.data as {
        type: string;
        payload: { progress: JobProgress | null; status: JobStatus; etaSeconds: number | null };
      };
      if (type === 'JOB_PROGRESS') {
        setProgress(payload.progress);
        setStatus(payload.status);
        setEtaSeconds(payload.etaSeconds);
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

    // Use absolute URL from config if available, otherwise relative
    const apiBase = window.AltContextAdmin?.endpoints.recognitionJobs ?? '/wp-json/alt-context/v1/recognition/jobs';
    const url = new URL(`${apiBase}/${jobId}/stream`, window.location.origin);
    const nonce = window.AltContextAdmin?.nonce;
    if (nonce) {
      url.searchParams.set('_wpnonce', nonce);
    }

    let eventSource: EventSource | null = new EventSource(url.toString());
    let isClosed = false;

    const closeAndCleanup = () => {
      isClosed = true;
      eventSource?.close();
      eventSource = null;
    };

    eventSource.addEventListener('progress', (e) => {
      if (isClosed) {
        return;
      }
      try {
        const data = JSON.parse(e.data as string) as { completed: number; total: number; status: JobStatus };

        // Calculate new state
        const now = Date.now();
        const newProgress: JobProgress = { completed: data.completed, total: data.total };
        let newEta: number | null = null;

        // Initialize start time on first progress
        if (!startTimeRef.current && data.completed > 0) {
          startTimeRef.current = now;
        }

        // Calculate ETA
        if (startTimeRef.current && data.completed > 0 && data.completed < data.total) {
          const elapsedMs = now - startTimeRef.current;
          const itemsProcessed = data.completed;
          const rate = itemsProcessed / elapsedMs;
          const remainingItems = data.total - data.completed;
          const remainingMs = remainingItems / rate;
          newEta = Math.round(remainingMs / 1000);
        }

        // Update local state
        progressRef.current = newProgress;
        setProgress(newProgress);
        setStatus(data.status);
        setEtaSeconds(newEta);

        // Broadcast to other tabs
        channel?.postMessage({
          type: 'JOB_PROGRESS',
          payload: {
            progress: newProgress,
            status: data.status,
            etaSeconds: newEta,
          },
        });
      } catch (err) {
        console.error('Failed to parse SSE progress data', err);
      }
    });

    eventSource.addEventListener('done', (e) => {
      if (isClosed) {
        return;
      }
      try {
        const data = JSON.parse(e.data as string) as { status: JobStatus };
        const latestProgress = progressRef.current;
        const finalProgress =
          latestProgress && data.status === 'completed'
            ? { completed: latestProgress.total, total: latestProgress.total }
            : latestProgress;
        setStatus(data.status);
        setProgress(finalProgress ?? null);
        setEtaSeconds(null);

        // Broadcast completion
        channel?.postMessage({
          type: 'JOB_PROGRESS',
          payload: {
            progress: finalProgress ?? null,
            status: data.status,
            etaSeconds: null,
          },
        });

        closeAndCleanup();
      } catch (err) {
        console.error('Failed to parse SSE done data', err);
      }
    });

    // Handle server-sent error events (e.g., 404 Job not found)
    eventSource.addEventListener('error', (e: Event) => {
      if (isClosed) {
        return;
      }

      // Check if this is a MessageEvent with error data from the server
      if (e instanceof MessageEvent && e.data) {
        try {
          const errorData = JSON.parse(e.data as string) as { message?: string };
          console.error('SSE server error:', errorData.message);

          // Job not found - mark as failed and stop reconnecting
          if (errorData.message?.includes('not found')) {
            setStatus('failed');
            closeAndCleanup();
            return;
          }
        } catch {
          // Not JSON, fall through to connection error handling
        }
      }

      // Connection error - EventSource will auto-reconnect
      console.warn('SSE connection error, will auto-reconnect...', e);
    });

    // Handle EventSource connection failures
    eventSource.onerror = () => {
      if (isClosed) {
        return;
      }
      // EventSource auto-reconnects on connection errors
      // Only log if we haven't explicitly closed
      if (eventSource?.readyState === EventSource.CLOSED) {
        console.warn('SSE connection closed unexpectedly');
      }
    };

    return () => closeAndCleanup();
  }, [jobId, isOnline, isPrimary, channel]);

  return { progress, status, isOnline, etaSeconds, isPrimary };
};
