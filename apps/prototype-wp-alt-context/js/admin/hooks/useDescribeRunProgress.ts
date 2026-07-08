import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  fetchBulkDescribeRun,
  isDescribeRunTerminal,
  type DescribeRunResponse,
  type DescribeRunStatus,
} from '../api/describeApi';
import { JOB_PROGRESS_STALL_THRESHOLD_MS } from './useJobProgressStream';

/**
 * Honest per-image progress for a bulk describe run (WBUX-3 S6-02).
 *
 * Transport is polling, not SSE: the WP stream proxy returns after a bounded
 * hold (~25s) rather than a true passthrough, so a status poll is the robust
 * honest-progress channel. React Query drives the interval and stops once the
 * run reaches a terminal status. ETA is taken verbatim from the backend
 * (`eta_seconds`) — never recomputed client-side. Stall is derived locally as
 * the time since `completed` last advanced, mirroring useJobProgressStream.
 */
const DESCRIBE_RUN_POLL_INTERVAL_MS = 2_000;
// Bounded retry so a single transient poll failure self-heals instead of freezing
// the run (FE-02). Backoff caps at 8s; after these attempts the error is surfaced.
const DESCRIBE_RUN_POLL_RETRIES = 3;

export interface DescribeRunProgress {
  run: DescribeRunResponse | null;
  status: DescribeRunStatus | null;
  progressFraction: number | null;
  etaSeconds: number | null;
  isTerminal: boolean;
  stalledForSeconds: number | null;
  isPolling: boolean;
  isError: boolean;
  error: Error | null;
  retry: () => void;
}

export const useDescribeRunProgress = (runId: string | null): DescribeRunProgress => {
  const query = useQuery<DescribeRunResponse, Error>({
    queryKey: ['bulkDescribeRun', runId],
    queryFn: () => {
      // Internal invariant: React Query never runs queryFn while `enabled` is false.
      if (runId === null) {
        throw new Error('useDescribeRunProgress queryFn invoked without a runId');
      }
      return fetchBulkDescribeRun(runId);
    },
    enabled: runId !== null,
    retry: DESCRIBE_RUN_POLL_RETRIES,
    retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000),
    refetchInterval: (q) => {
      if (q.state.status === 'error') {
        return false;
      }
      const data = q.state.data;
      if (data && isDescribeRunTerminal(data.status)) {
        return false;
      }
      return DESCRIBE_RUN_POLL_INTERVAL_MS;
    },
  });

  const run = query.data ?? null;
  const status = run?.status ?? null;
  const isTerminal = status !== null && isDescribeRunTerminal(status);
  const isError = query.isError;

  const { refetch } = query;
  const retry = useCallback(() => {
    void refetch();
  }, [refetch]);

  const lastCompletedRef = useRef<number | null>(null);
  const lastProgressAtRef = useRef<number | null>(null);
  const [stalledForSeconds, setStalledForSeconds] = useState<number | null>(null);

  // Reset per-run stall accounting whenever the tracked run changes.
  useEffect(() => {
    lastCompletedRef.current = null;
    lastProgressAtRef.current = null;
    setStalledForSeconds(null);
  }, [runId]);

  // Record the wall-clock time each time the processed count advances (or on
  // first data). "Processed" is every terminal item (completed + failed +
  // skipped), not just successes — otherwise a run advancing purely via
  // failures/skips would look stalled and the bar would never fill.
  useEffect(() => {
    if (run === null) {
      return;
    }
    const processed = run.completed + run.failed + run.skipped;
    if (lastCompletedRef.current === null || processed > lastCompletedRef.current) {
      lastCompletedRef.current = processed;
      lastProgressAtRef.current = Date.now();
      setStalledForSeconds(null);
    }
  }, [run]);

  // Tick the stall indicator once per second while the run is live. A polling
  // error surfaces its own Retry affordance, so suppress the stall banner then.
  useEffect(() => {
    if (runId === null || isTerminal || isError) {
      setStalledForSeconds(null);
      return;
    }

    const updateStallState = () => {
      const baseline = lastProgressAtRef.current;
      if (baseline === null) {
        setStalledForSeconds(null);
        return;
      }
      const elapsedMs = Date.now() - baseline;
      setStalledForSeconds(
        elapsedMs >= JOB_PROGRESS_STALL_THRESHOLD_MS ? Math.floor(elapsedMs / 1000) : null,
      );
    };

    updateStallState();
    const intervalId = window.setInterval(updateStallState, 1_000);
    return () => window.clearInterval(intervalId);
  }, [runId, isTerminal, isError]);

  // Terminal (processed) items over total: completed + failed + skipped, so the
  // bar reaches 100% when every item is done regardless of per-item outcome.
  const progressFraction =
    run !== null && run.total > 0
      ? Math.min(1, Math.max(0, (run.completed + run.failed + run.skipped) / run.total))
      : null;

  return {
    run,
    status,
    progressFraction,
    etaSeconds: run?.eta_seconds ?? null,
    isTerminal,
    stalledForSeconds,
    isPolling: runId !== null && !isTerminal && !isError,
    isError,
    error: query.error ?? null,
    retry,
  };
};
