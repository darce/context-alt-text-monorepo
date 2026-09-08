import { useMemo } from 'react';

import type { BatchRunStatus, JobProgress, JobStatusResponse } from '../api/recognition/types/scan';
import { buildClusterProgress, buildScanProgress, buildStatusText } from './jobStateMachineProgress';
import { isScanRunning } from './jobStateMachineRuntime';
import type { PipelinePhase } from './jobStateMachineUtils';
import type { PersistedJob } from './useJobPersistence';
import type { JobStatus } from './useJobProgressStream';
import { useMonotonicScanProgress } from './useMonotonicScanProgress';

/**
 * Outcome of the run-liveness probe (sr-007: one canonical status surface).
 *
 * The probe is a *report*, never a write gate, so it must fail open on control
 * flow — nothing here kills, cancels or hides a run. But it must fail *loud* on
 * reporting: `UNOBSERVED` exists so "we hold no liveness evidence" can never be
 * rendered as "healthy" (RLSE-05, silent failure is the worst failure;
 * RLSE-04, an undesigned state is a bug). Before this state existed, `null` did
 * double duty for "the detector ran and saw recent progress" and "the detector
 * is not running at all", and the dead-stream case rendered as healthy.
 */
export const SCAN_STALL_STATE = {
  /** No run in flight; the probe is not applicable. */
  IDLE: 'idle',
  /** The probe is reporting and has seen progress inside the stall window. */
  LIVE: 'live',
  /** The probe is reporting and has seen no progress for `seconds`. */
  STALLED: 'stalled',
  /** A run may be in flight but no trustworthy reading exists. Unknown, not healthy. */
  UNOBSERVED: 'unobserved',
} as const;

export type ScanStallState = (typeof SCAN_STALL_STATE)[keyof typeof SCAN_STALL_STATE];

export interface ScanStallReport {
  state: ScanStallState;
  /** Observed silence duration. Non-null only in the `STALLED` state. */
  seconds: number | null;
}

/**
 * Boundary validation (sr-005): `stalledForSeconds` crosses a hook boundary from
 * a wall-clock subtraction. `typeof x === 'number'` alone admits `NaN` and
 * negatives from a skewed clock, which reach the banner as "last update NaN ago".
 * A corrupt reading is not evidence of health — it is no reading.
 */
const isObservedStallReading = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0;

export interface DeriveScanStallReportInput {
  currentPhase: PipelinePhase;
  stalledForSeconds: number | null | undefined;
  /**
   * Whether the caller has positive evidence that the liveness detector is
   * actually running (`useJobProgressStream` disables it when the tab is not
   * primary, the browser is offline, or there is no job id). Callers that hold
   * no such evidence must pass `false`: absence of evidence is `UNOBSERVED`,
   * never `LIVE`.
   */
  probeObserving: boolean;
}

/**
 * Single source of truth for the stall report, shared by the derived-state hook
 * and `JobPipelineProvider` so the two seams cannot drift.
 */
export const deriveScanStallReport = ({
  currentPhase,
  stalledForSeconds,
  probeObserving,
}: DeriveScanStallReportInput): ScanStallReport => {
  if (currentPhase === 'idle') {
    return { state: SCAN_STALL_STATE.IDLE, seconds: null };
  }
  // A real reading always wins: having a number *is* an observation.
  if (isObservedStallReading(stalledForSeconds)) {
    return { state: SCAN_STALL_STATE.STALLED, seconds: stalledForSeconds };
  }
  if (stalledForSeconds === null && probeObserving) {
    return { state: SCAN_STALL_STATE.LIVE, seconds: null };
  }
  return { state: SCAN_STALL_STATE.UNOBSERVED, seconds: null };
};

interface UseJobStateMachineDerivedStateOptions {
  currentPhase: PipelinePhase;
  activeJobIds: string[];
  activeJobs: PersistedJob[];
  latestScanJob: PersistedJob | null;
  latestJobId: string | null;
  scanPending: boolean;
  clusterPending: boolean;
  clusterQueuedSeconds?: number | null;
  waitingForCompletion: boolean;
  scanStatus: JobStatusResponse | undefined;
  batchRunStatus?: BatchRunStatus;
  sseStatus: JobStatus;
  sseProgress: JobProgress | null;
  stalledForSeconds: number | null | undefined;
  /** See `DeriveScanStallReportInput.probeObserving`. Defaults to "no evidence". */
  probeObserving?: boolean;
}

export const useJobStateMachineDerivedState = ({
  currentPhase,
  activeJobIds,
  activeJobs,
  latestScanJob,
  latestJobId,
  scanPending,
  clusterPending,
  clusterQueuedSeconds = null,
  waitingForCompletion,
  scanStatus,
  batchRunStatus,
  sseStatus,
  sseProgress,
  stalledForSeconds,
  probeObserving = false,
}: UseJobStateMachineDerivedStateOptions) => {
  const statusText = useMemo(
    () =>
      buildStatusText({
        clusterPending,
        clusterQueuedSeconds,
        sseStatus,
        sseProgress,
        activeJobIds,
        scanStatus,
        batchRunStatus,
        latestJobId,
        scanPending,
      }),
    [
      activeJobIds,
      batchRunStatus,
      clusterPending,
      clusterQueuedSeconds,
      latestJobId,
      scanPending,
      scanStatus,
      sseProgress,
      sseStatus,
    ],
  );

  const rawScanProgress = useMemo(
    () =>
      buildScanProgress({
        currentPhase,
        activeJobIds,
        activeJobs,
        sseProgress,
        latestScanJob,
        batchRunStatus,
        fallbackProgress: scanStatus?.progress,
      }),
    [activeJobIds, activeJobs, batchRunStatus, currentPhase, latestScanJob, scanStatus?.progress, sseProgress],
  );

  const rawClusterProgress = useMemo(
    () => buildClusterProgress(currentPhase, sseProgress, scanStatus?.progress),
    [currentPhase, scanStatus?.progress, sseProgress],
  );

  const scanRunKey = batchRunStatus?.id ?? latestScanJob?.id ?? activeJobIds[0] ?? null;
  const clusterRunKey = activeJobIds.find((id) => id !== latestScanJob?.id) ?? activeJobIds[0] ?? null;

  const scanProgress = useMonotonicScanProgress(rawScanProgress, scanRunKey);
  const clusterProgress = useMonotonicScanProgress(rawClusterProgress, clusterRunKey);

  const currentIsScanRunning = useMemo(
    () =>
      isScanRunning({
        scanPending,
        waitingForCompletion,
        activeJobIds,
        sseStatus,
        scanStatus,
        batchRunStatus,
      }),
    [activeJobIds, batchRunStatus, scanPending, scanStatus, sseStatus, waitingForCompletion],
  );

  const scanStallReport = useMemo(
    () => deriveScanStallReport({ currentPhase, stalledForSeconds, probeObserving }),
    [currentPhase, probeObserving, stalledForSeconds],
  );

  return {
    statusText,
    scanProgress,
    clusterProgress,
    isScanRunning: currentIsScanRunning,
    /** Duration of observed silence; non-null only when `scanStallState` is `stalled`. */
    scanStallSeconds: scanStallReport.seconds,
    /** Explicit probe state — read this instead of inferring health from a null duration. */
    scanStallState: scanStallReport.state,
  };
};
