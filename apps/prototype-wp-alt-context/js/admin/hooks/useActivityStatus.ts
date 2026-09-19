import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react';
import { useMutation } from '@tanstack/react-query';

import {
  cancelBulkDescribeRun,
  DESCRIBE_RUN_PHASE,
  DESCRIBE_RUN_STATUS,
  DESCRIBE_RUN_TERMINAL_CODE,
  fetchDescribeRunItems,
  GPU_STATE,
  isGpuState,
  submitBulkDescribeRun,
  type DescribeRunItem,
  type DescribeRunResponse,
  type DescribeRunStatus,
  type GpuState,
} from '../api/describeApi';
import { toDescriptionHistoryRun, toWorkbench } from '../navigation/appLinks';
import { useActiveDescribeRun } from './activeDescribeRun';
import {
  DESCRIBE_RUN_SETTLE_OUTCOME,
  pendingTerminalRuns,
  settleRun,
  subscribeDescribeOperationStore,
  type DescribeRunSettleOutcome,
} from './describeOperationStore';
import { persistRunContext } from './useBulkDescribe';
import { useDescribeRunProgress, type DescribeRunProgress } from './useDescribeRunProgress';
import { useGpuServiceStatus } from './useGpuServiceStatus';

export { STALL_PHASE, stallThresholdMs } from './jobMachine';

export const ACTIVITY_KIND = {
  IDLE: 'idle',
  SCANNING: 'scanning',
  WARMING: 'warming',
  DESCRIBING: 'describing',
  DONE: 'done',
  FAILED: 'failed',
} as const;

export type ActivityKind = (typeof ACTIVITY_KIND)[keyof typeof ACTIVITY_KIND];

export const ACTIVITY_REASON = {
  GPU_WARMUP_TIMEOUT: 'gpu_warmup_timeout',
  DESCRIBE_POLL_ERROR: 'describe_poll_error',
  GPU_STATUS_UNAVAILABLE: 'gpu_status_unavailable',
  CANCELLED: 'cancelled',
  FAILED: 'failed',
  SCAN_FAILED: 'scan_failed',
} as const;

export type ActivityReason = (typeof ACTIVITY_REASON)[keyof typeof ACTIVITY_REASON];

/** Item statuses that do not need a warmup-timeout resubmit (sr-007). */
const FINISHED_DESCRIBE_ITEM_STATUS = {
  COMPLETED: DESCRIBE_RUN_STATUS.COMPLETED,
  SKIPPED: 'skipped',
} as const;

const FINISHED_DESCRIBE_ITEM_STATUSES: ReadonlySet<string> = new Set(
  Object.values(FINISHED_DESCRIBE_ITEM_STATUS),
);

type WarmupResubmitResult =
  | { kind: 'exhausted' }
  | { kind: 'submitted'; response: DescribeRunResponse };

const unfinishedMediaIdsFromItems = (items: readonly DescribeRunItem[]): number[] =>
  items
    .filter((item) => !FINISHED_DESCRIBE_ITEM_STATUSES.has(item.status))
    .map((item) => item.media_id);

/** Stable authority snapshot consumed by the strip and by spa-activity-toasts (C7). */
export interface ActivityStatus {
  kind: ActivityKind;
  progress: number | null;
  etaSeconds: number | null;
  reason: string | null;
  canCancel: boolean;
  runId: string | null;
  gpuState: GpuState | null;
  retryable: boolean;
  draftCount: number;
}

export interface ActivityStatusActions {
  onCancel: (() => void) | null;
  onRetry: (() => void) | null;
  reviewDraftsHref: string | null;
  backToRunHref: string | null;
}

export interface ScanActivitySource {
  isScanning: boolean;
  isCancelling?: boolean;
  progress?: { completed: number; total: number } | null;
  etaSeconds?: number | null;
  errorMessage?: string | null;
  jobId?: string | null;
  cancelScan?: () => void;
  retryScan?: () => void;
}

export interface UseActivityStatusParams {
  scan?: ScanActivitySource;
}

export interface UseActivityStatusResult {
  status: ActivityStatus;
  actions: ActivityStatusActions;
  isCancelling: boolean;
}

export interface ScanActivityInput {
  isScanning: boolean;
  isCancelling?: boolean;
  progressFraction: number | null;
  etaSeconds: number | null;
  errorMessage: string | null;
  jobId: string | null;
}

export interface DescribeActivityInput {
  runId: string | null;
  progress: DescribeRunProgress;
}

export interface GpuActivityInput {
  gpuState: GpuState;
  reason: string | null;
  isError: boolean;
  isRunPending: boolean;
}

export interface ResolveActivityStatusInput {
  scan: ScanActivityInput;
  describe: DescribeActivityInput;
  gpu: GpuActivityInput;
}

const emptyScan = (): ScanActivityInput => ({
  isScanning: false,
  isCancelling: false,
  progressFraction: null,
  etaSeconds: null,
  errorMessage: null,
  jobId: null,
});

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const progressFractionFromCounts = (completed: number, total: number): number | null => {
  if (total <= 0) {
    return null;
  }
  return Math.min(1, Math.max(0, completed / total));
};

const scanProgressFraction = (progress: ScanActivitySource['progress']): number | null => {
  if (progress === undefined || progress === null) {
    return null;
  }
  return progressFractionFromCounts(progress.completed, progress.total);
};

const parseWarmupTimeout = (run: DescribeRunResponse | null): { retryable: boolean } | null => {
  const terminal = run?.terminal;
  if (!isRecord(terminal) || terminal.code !== DESCRIBE_RUN_TERMINAL_CODE.GPU_WARMUP_TIMEOUT) {
    return null;
  }
  return { retryable: terminal.retryable === true };
};

const describeDraftCount = (run: DescribeRunResponse | null): number => run?.completed ?? 0;

const describeCanCancel = (progress: DescribeRunProgress): boolean =>
  progress.run !== null && progress.run.cancel_requested !== true && !progress.isTerminal && !progress.isError;

const gpuIsWarming = (gpuState: GpuState): boolean =>
  gpuState === GPU_STATE.STARTING || gpuState === GPU_STATE.WARMING;

const mapDescribeStatusToSettleOutcome = (status: DescribeRunStatus): DescribeRunSettleOutcome => {
  switch (status) {
    case DESCRIBE_RUN_STATUS.COMPLETED:
      return DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED;
    case DESCRIBE_RUN_STATUS.COMPLETED_WITH_ERRORS:
      return DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED_WITH_ERRORS;
    case DESCRIBE_RUN_STATUS.FAILED:
      return DESCRIBE_RUN_SETTLE_OUTCOME.FAILED;
    case DESCRIBE_RUN_STATUS.CANCELLED:
      return DESCRIBE_RUN_SETTLE_OUTCOME.CANCELLED;
    default:
      return DESCRIBE_RUN_SETTLE_OUTCOME.UNRESOLVED;
  }
};

const snapshot = (
  kind: ActivityKind,
  fields: Omit<ActivityStatus, 'kind'>,
): ActivityStatus => ({ kind, ...fields });

const idleFields = (gpuState: GpuState | null): Omit<ActivityStatus, 'kind'> => ({
  progress: null,
  etaSeconds: null,
  reason: null,
  canCancel: false,
  runId: null,
  gpuState,
  retryable: false,
  draftCount: 0,
});

export const resolveActivityStatus = (input: ResolveActivityStatusInput): ActivityStatus => {
  const { scan, describe, gpu } = input;
  const run = describe.progress.run;
  const runGpu = isGpuState(describe.progress.gpuState)
    ? describe.progress.gpuState
    : isGpuState(run?.gpu_state)
      ? run.gpu_state
      : null;
  const gpuState = describe.runId !== null && gpu.isRunPending ? (runGpu ?? gpu.gpuState) : gpu.gpuState;
  const describeLive =
    describe.runId !== null && !describe.progress.isTerminal && !describe.progress.isError;

  if (scan.isScanning) {
    return snapshot(ACTIVITY_KIND.SCANNING, {
      progress: scan.progressFraction,
      etaSeconds: scan.etaSeconds,
      reason: null,
      canCancel: scan.isCancelling !== true,
      runId: describe.runId,
      gpuState,
      retryable: false,
      draftCount: describeDraftCount(run),
    });
  }

  if (describe.progress.isError) {
    return snapshot(ACTIVITY_KIND.FAILED, {
      progress: describe.progress.progressFraction,
      etaSeconds: null,
      reason: ACTIVITY_REASON.DESCRIBE_POLL_ERROR,
      canCancel: false,
      runId: describe.runId,
      gpuState,
      retryable: true,
      draftCount: describeDraftCount(run),
    });
  }

  const warmupTimeout = parseWarmupTimeout(run);
  const describeWarming =
    describeLive &&
    (describe.progress.isWarming === true ||
      run?.phase === DESCRIBE_RUN_PHASE.WARMING ||
      gpuIsWarming(runGpu ?? GPU_STATE.UNKNOWN));

  if (describeWarming) {
    return snapshot(ACTIVITY_KIND.WARMING, {
      progress: describe.progress.progressFraction,
      etaSeconds: describe.progress.etaSeconds,
      reason: null,
      canCancel: describeCanCancel(describe.progress),
      runId: describe.runId,
      gpuState,
      retryable: false,
      draftCount: describeDraftCount(run),
    });
  }

  if (describeLive) {
    return snapshot(ACTIVITY_KIND.DESCRIBING, {
      progress: describe.progress.progressFraction,
      etaSeconds: describe.progress.etaSeconds,
      reason: null,
      canCancel: describeCanCancel(describe.progress),
      runId: describe.runId,
      gpuState,
      retryable: false,
      draftCount: describeDraftCount(run),
    });
  }

  if (describe.progress.isTerminal && describe.progress.status !== null) {
    if (
      describe.progress.status === DESCRIBE_RUN_STATUS.FAILED ||
      describe.progress.status === DESCRIBE_RUN_STATUS.CANCELLED ||
      run?.phase === DESCRIBE_RUN_PHASE.FAILED ||
      run?.phase === DESCRIBE_RUN_PHASE.CANCELLED
    ) {
      const cancelled = describe.progress.status === DESCRIBE_RUN_STATUS.CANCELLED;
      return snapshot(ACTIVITY_KIND.FAILED, {
        progress: describe.progress.progressFraction,
        etaSeconds: null,
        reason: warmupTimeout
          ? ACTIVITY_REASON.GPU_WARMUP_TIMEOUT
          : cancelled
            ? ACTIVITY_REASON.CANCELLED
            : ACTIVITY_REASON.FAILED,
        canCancel: false,
        runId: describe.runId ?? run?.run_id ?? null,
        gpuState,
        retryable: warmupTimeout?.retryable === true,
        draftCount: describeDraftCount(run),
      });
    }
    return snapshot(ACTIVITY_KIND.DONE, {
      progress: describe.progress.progressFraction,
      etaSeconds: null,
      reason: null,
      canCancel: false,
      runId: describe.runId ?? run?.run_id ?? null,
      gpuState,
      retryable: false,
      draftCount: describeDraftCount(run),
    });
  }

  if (scan.errorMessage !== null && scan.errorMessage !== '') {
    return snapshot(ACTIVITY_KIND.FAILED, {
      ...idleFields(gpuState),
      reason: ACTIVITY_REASON.SCAN_FAILED,
      retryable: true,
    });
  }

  if (gpu.isError) {
    return snapshot(ACTIVITY_KIND.FAILED, {
      ...idleFields(gpu.gpuState),
      reason: ACTIVITY_REASON.GPU_STATUS_UNAVAILABLE,
      retryable: true,
    });
  }

  if (gpuIsWarming(gpu.gpuState)) {
    return snapshot(ACTIVITY_KIND.WARMING, {
      ...idleFields(gpu.gpuState),
      canCancel: false,
    });
  }

  return snapshot(ACTIVITY_KIND.IDLE, idleFields(gpuState));
};

const pendingTerminalRunId = (): string | null => pendingTerminalRuns()[0]?.id ?? null;

const toScanInput = (scan: ScanActivitySource | undefined): ScanActivityInput => {
  if (scan === undefined) {
    return emptyScan();
  }
  return {
    isScanning: scan.isScanning,
    isCancelling: scan.isCancelling === true,
    progressFraction: scanProgressFraction(scan.progress),
    etaSeconds: scan.etaSeconds ?? null,
    errorMessage: scan.errorMessage ?? null,
    jobId: scan.jobId ?? null,
  };
};

export const useActivityStatus = (params: UseActivityStatusParams = {}): UseActivityStatusResult => {
  const scan = params.scan;
  const { runId: activeRunId } = useActiveDescribeRun();
  const pendingRunId = useSyncExternalStore(
    subscribeDescribeOperationStore,
    pendingTerminalRunId,
    pendingTerminalRunId,
  );
  const describeRunId = activeRunId ?? pendingRunId;
  const describeProgress = useDescribeRunProgress(describeRunId);
  const describeLive =
    describeRunId !== null && !describeProgress.isTerminal && !describeProgress.isError;
  const gpu = useGpuServiceStatus({ isRunPending: describeLive });
  const cancelMutation = useMutation({
    mutationFn: cancelBulkDescribeRun,
  });
  const resubmitInFlightRef = useRef(false);
  const resubmitMutation = useMutation<WarmupResubmitResult, Error, string>({
    mutationFn: async (runId) => {
      const itemsResponse = await fetchDescribeRunItems(runId);
      const unfinishedIds = unfinishedMediaIdsFromItems(itemsResponse.items);
      if (unfinishedIds.length === 0) {
        return { kind: 'exhausted' };
      }
      const response = await submitBulkDescribeRun(unfinishedIds);
      return { kind: 'submitted', response };
    },
    onSuccess: (result) => {
      if (result.kind === 'submitted') {
        persistRunContext(result.response);
      }
    },
    onSettled: () => {
      resubmitInFlightRef.current = false;
    },
  });
  const lastTerminalRef = useRef<ActivityStatus | null>(null);

  useEffect(() => {
    if (pendingRunId === null || pendingRunId !== describeRunId) {
      return;
    }
    if (describeProgress.isTerminal && describeProgress.status !== null) {
      settleRun(pendingRunId, mapDescribeStatusToSettleOutcome(describeProgress.status));
      return;
    }
    if (describeProgress.isError) {
      settleRun(pendingRunId, DESCRIBE_RUN_SETTLE_OUTCOME.UNRESOLVED);
    }
  }, [
    describeProgress.isError,
    describeProgress.isTerminal,
    describeProgress.status,
    describeRunId,
    pendingRunId,
  ]);

  const resolved = resolveActivityStatus({
    scan: toScanInput(scan),
    describe: { runId: describeRunId, progress: describeProgress },
    gpu: {
      gpuState: gpu.gpuState,
      reason: gpu.reason,
      isError: gpu.isError,
      isRunPending: describeLive,
    },
  });

  if (
    resolved.kind === ACTIVITY_KIND.DONE ||
    resolved.kind === ACTIVITY_KIND.FAILED
  ) {
    lastTerminalRef.current = resolved;
  } else if (
    resolved.kind === ACTIVITY_KIND.SCANNING ||
    resolved.kind === ACTIVITY_KIND.WARMING ||
    resolved.kind === ACTIVITY_KIND.DESCRIBING
  ) {
    lastTerminalRef.current = null;
  }

  const status =
    resolved.kind === ACTIVITY_KIND.IDLE && lastTerminalRef.current !== null
      ? lastTerminalRef.current
      : resolved;

  const isCancelling = scan?.isCancelling === true || cancelMutation.isPending;

  const actions = useMemo<ActivityStatusActions>(() => {
    const canCancel = status.canCancel && !isCancelling;
    const onCancel = canCancel
      ? () => {
          if (scan?.isScanning === true) {
            scan.cancelScan?.();
            return;
          }
          if (status.runId !== null) {
            cancelMutation.mutate(status.runId);
          }
        }
      : null;
    const onRetry = ((): (() => void) | null => {
      if (status.kind !== ACTIVITY_KIND.FAILED || !status.retryable) {
        return null;
      }
      if (status.reason === ACTIVITY_REASON.SCAN_FAILED) {
        return () => {
          scan?.retryScan?.();
        };
      }
      if (status.reason === ACTIVITY_REASON.GPU_STATUS_UNAVAILABLE) {
        return () => {
          gpu.refetch();
        };
      }
      if (status.reason === ACTIVITY_REASON.GPU_WARMUP_TIMEOUT) {
        if (
          status.runId === null ||
          resubmitMutation.isPending ||
          resubmitMutation.data?.kind === 'exhausted'
        ) {
          return null;
        }
        const runId = status.runId;
        return () => {
          if (resubmitInFlightRef.current || resubmitMutation.isPending) {
            return;
          }
          resubmitInFlightRef.current = true;
          resubmitMutation.mutate(runId);
        };
      }
      return () => {
        describeProgress.retry();
      };
    })();
    return {
      onCancel,
      onRetry,
      reviewDraftsHref:
        status.kind === ACTIVITY_KIND.DONE && status.runId !== null
          ? toDescriptionHistoryRun(status.runId)
          : null,
      backToRunHref:
        status.kind === ACTIVITY_KIND.WARMING || status.kind === ACTIVITY_KIND.DESCRIBING
          ? toWorkbench()
          : null,
    };
  }, [cancelMutation, describeProgress, gpu, isCancelling, resubmitMutation, scan, status]);

  return { status, actions, isCancelling };
};
