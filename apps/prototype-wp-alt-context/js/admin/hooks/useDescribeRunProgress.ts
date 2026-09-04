import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import {
  fetchBulkDescribeRun,
  GPU_STATE,
  isDescribeRunTerminal,
  isGpuState,
  type DescribeRunResponse,
  type DescribeRunStatus,
  type GpuState,
} from '../api/describeApi';
import { getJobProgressStallThresholdMs } from './useJobProgressStream';
import { gateRefetchInterval } from '../utils/recognitionCooldown';
import { isAbortOrTimeout } from '../utils/retryPolicy';

/**
 * Honest per-image progress for a bulk describe run (WBUX-3 S6-02).
 *
 * Transport is polling, not SSE: there is no describe SSE surface (the WP stream
 * proxy was removed in INT-03), so polling the run status route is the sole
 * progress channel. React Query drives the interval and stops once the
 * run reaches a terminal status. ETA is taken verbatim from the backend
 * (`eta_seconds`) — never recomputed client-side. Stall is derived locally as
 * the time since `completed` last advanced, mirroring useJobProgressStream.
 */
export const DESCRIBE_RUN_POLL_INTERVAL_MS = 2_000;

/**
 * Consecutive abort-like poll failures that flip a frozen run to a hard error
 * (UXP-2 BR review). A single timeout freezes-and-thaws (BR-07), but a frozen
 * bar that never recovers is a silent hang: at the 2s cadence, 5 dead polls is
 * ~>10s of dead air, at which point the run stops polling and surfaces the
 * Retry affordance instead of freezing forever.
 */
export const FROZEN_POLL_ESCALATION_THRESHOLD = 5;

/**
 * "The poll did not come back" — the *presentation* policy for describe-run
 * progress: freeze the bar and keep polling, rather than dead-ending the
 * operator on a transient failure.
 *
 * Named for its policy, not its shape, and deliberately distinct from the retry
 * decision even though both currently reduce to `isAbortOrTimeout`. They answer
 * different questions and have different reasons to change: FEBT1-W2A-05
 * narrowed the *retry* predicate and silently moved this UI policy across a
 * module boundary (three tests red). A retry-side narrowing must land here as a
 * compile-or-test event, not as a behaviour change nobody asked for
 * (DOM-03 one meaning per term per context; REF-10 the shared implementation is
 * coincidental, not a shared rule).
 *
 * Exported so a unit test can pin both abort-like tags directly (TEST-15).
 */
export const isFrozenPollFailure = (error: unknown): boolean => isAbortOrTimeout(error);

/**
 * Pure refetchInterval decision for describe-run progress (UXP-2-BR-07).
 *
 * Transient abort/timeout must keep polling — user abort is never retried, and
 * timeout is retried only once, so the next scheduled poll is the remaining
 * retry. Stop only on hard (non-abort/timeout) errors, terminal run status, or
 * the frozen-streak bound.
 *
 * Exported so pure unit tests can invert each branch (TEST-15) without the hook.
 */
export const getDescribeRunRefetchInterval = (args: {
  status: 'pending' | 'error' | 'success';
  error: unknown;
  data: DescribeRunResponse | undefined;
  frozenPollStreak: number;
}): number | false => {
  // Keep polling through abort/timeout; only hard failures stop (BR-07).
  if (args.status === 'error' && !isFrozenPollFailure(args.error)) {
    return false;
  }
  if (args.frozenPollStreak >= FROZEN_POLL_ESCALATION_THRESHOLD) {
    return false;
  }
  if (args.data && isDescribeRunTerminal(args.data.status)) {
    return false;
  }
  return DESCRIBE_RUN_POLL_INTERVAL_MS;
};

export interface DescribeRunProgress {
  run: DescribeRunResponse | null;
  status: DescribeRunStatus | null;
  progressFraction: number | null;
  etaSeconds: number | null;
  /** GPU lifecycle snapshot carried by the existing run-status poll. */
  gpuState?: GpuState | null;
  isTerminal: boolean;
  stalledForSeconds: number | null;
  isPolling: boolean;
  /**
   * The last status poll failed transiently (abort/timeout) but polling
   * continues — progress is frozen at the last known values, not dead
   * (UXP-2 BR-07). Distinct from isError, which is a hard stop with a Retry
   * affordance.
   */
  isFrozen: boolean;
  isError: boolean;
  error: Error | null;
  retry: () => void;
}

export const useDescribeRunProgress = (runId: string | null): DescribeRunProgress => {
  // Consecutive abort-like poll failures, tracked across renders. Read inside
  // the refetchInterval predicate (stops the poll once escalated) and surfaced
  // as a hard error below. A ref drives the poll decision; the mirrored state
  // forces the re-render that flips isFrozen -> isError.
  const consecutiveFrozenPollsRef = useRef(0);
  const [frozenPollStreak, setFrozenPollStreak] = useState(0);

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
    // Gated on the shared recognition cooldown (UXP-2 slice 2).
    // Never return false from the gated path during cooldown (gate handles that);
    // terminal / hard-error / frozen-bound stops are decided by the pure helper.
    refetchInterval: gateRefetchInterval((q) =>
      getDescribeRunRefetchInterval({
        status: q.state.status,
        error: q.state.error,
        data: q.state.data,
        frozenPollStreak: consecutiveFrozenPollsRef.current,
      }),
    ),
  });

  // Count consecutive abort-like poll failures off the query's update
  // watermarks: a fresh abort-like error advances the streak; any fresh data
  // resets it. Watermarks are unambiguous regardless of whether retained data
  // keeps the query's status 'success' or 'error'.
  const { dataUpdatedAt, errorUpdatedAt, error: queryError } = query;
  const lastCountedErrorAtRef = useRef(0);
  const lastCountedDataAtRef = useRef(0);
  useEffect(() => {
    if (dataUpdatedAt > lastCountedDataAtRef.current) {
      lastCountedDataAtRef.current = dataUpdatedAt;
      consecutiveFrozenPollsRef.current = 0;
      setFrozenPollStreak(0);
    }
    if (errorUpdatedAt > lastCountedErrorAtRef.current && isFrozenPollFailure(queryError)) {
      lastCountedErrorAtRef.current = errorUpdatedAt;
      consecutiveFrozenPollsRef.current += 1;
      setFrozenPollStreak(consecutiveFrozenPollsRef.current);
    }
  }, [dataUpdatedAt, errorUpdatedAt, queryError]);

  // Reset the frozen-streak accounting whenever the tracked run changes.
  useEffect(() => {
    consecutiveFrozenPollsRef.current = 0;
    lastCountedErrorAtRef.current = 0;
    lastCountedDataAtRef.current = 0;
    setFrozenPollStreak(0);
  }, [runId]);

  const run = query.data ?? null;
  const status = run?.status ?? null;
  const isTerminal = status !== null && isDescribeRunTerminal(status);
  const frozenStreakExceeded = frozenPollStreak >= FROZEN_POLL_ESCALATION_THRESHOLD;
  const isFrozen = query.isError && isFrozenPollFailure(query.error) && !frozenStreakExceeded;
  const isError = query.isError && !isFrozen;

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
  // error surfaces its own Retry affordance, and a frozen poll already shows
  // the paused notice, so suppress the speculative stall banner in both.
  useEffect(() => {
    if (runId === null || isTerminal || isError || isFrozen) {
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
        elapsedMs >= getJobProgressStallThresholdMs() ? Math.floor(elapsedMs / 1000) : null,
      );
    };

    updateStallState();
    const intervalId = window.setInterval(updateStallState, 1_000);
    return () => window.clearInterval(intervalId);
  }, [runId, isTerminal, isError, isFrozen]);

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
    gpuState: isGpuState(run?.gpu_state) ? run.gpu_state : GPU_STATE.UNKNOWN,
    isTerminal,
    stalledForSeconds,
    isPolling: runId !== null && !isTerminal && !isError,
    isFrozen,
    isError,
    error: query.error ?? null,
    retry,
  };
};
