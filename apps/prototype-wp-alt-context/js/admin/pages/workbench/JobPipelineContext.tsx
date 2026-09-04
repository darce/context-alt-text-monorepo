import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useRecognitionJobHistory } from '../../hooks/useRecognitionJobHistory';
import { useJobStateMachine } from '../../hooks/useJobStateMachine';
import { useWorkbenchNav } from './WorkbenchNavContext';
import type { BatchRunStatus, JobProgress } from '../../api/recognition/types/scan';
import type { ClusterResponse } from '../../api/recognition';
import type { PipelinePhase } from '../../hooks/jobStateMachineUtils';
import type { ProjectionSyncState } from '../../hooks/useJobStateMachineEffects';
import type { RecognitionHistorySource } from '../../hooks/recognitionJobHistoryUtils';

/**
 * Live-run presentation bundle for ScanActionPanel. Carries the derivations
 * formerly inlined at the call site: display jobId (`latestJobId ?? jobId`),
 * the active-progress ternary, and `isSynced`.
 */
export interface ScanRunViewModel {
  isScanning: boolean;
  isCancelling?: boolean;
  statusText?: string;
  jobId?: string | null;
  errorMessage?: string | null;
  /** When set, ScanActionPanel shows manual Retry clustering after auto-retry ceiling. */
  onRetryClustering?: () => void;
  progress?: JobProgress | null;
  batchRunStatus?: BatchRunStatus | null;
  stallSeconds?: number | null;
  etaSeconds?: number | null;
  isSynced?: boolean;
}

export interface PipelineStatusModel {
  currentPhase: PipelinePhase;
  projectionSyncState: ProjectionSyncState;
  projectionError: string | null;
  isOnline: boolean;
  scanProgress: JobProgress | null;
  clusterProgress: JobProgress | null;
  clusterMessage: string | null;
}

export interface JobHistoryModel {
  jobId: string | undefined | null;
  latestJobId: string | undefined | null;
  activeJobIds: string[];
  jobHistory: string[];
  jobStatuses: Record<string, string>;
  historySource: RecognitionHistorySource;
}

export interface JobPipelineContextValue {
  scanRun: ScanRunViewModel;
  status: PipelineStatusModel;
  history: JobHistoryModel;
  scan: (mediaIds: number[]) => void;
  /** Starts a scan and settles when that run reaches a terminal outcome. Bounded; never hangs. */
  scanAndWait: (mediaIds: number[]) => Promise<void>;
  cancelScan: (jobIds: string[]) => void;
  cluster: () => void;
  retryClustering: () => void;
  retryProjectionSync: () => void;
  retryScanStream: () => void;
  handleSelectJobFromHistory: (id: string) => void;
  clearHistory: () => void;
}

const JobPipelineContext = createContext<JobPipelineContextValue | null>(null);

/**
 * Fail-fast bound on identification *start* (RES-03, CARD-09 bounded waiting).
 * `scan()` must report `isScanRunning` within this window or the waiter rejects.
 * This is deliberately NOT a bound on the run itself: a healthy in-flight run is
 * never killed by this deadline.
 */
export const SCAN_START_TIMEOUT_MS = 15_000;

/**
 * Bound on *silence* once identification is running (RES-13, DIAG-07). Re-armed on
 * every observed progress change, so it fires only when a started run stops
 * reporting. Must comfortably exceed a cold GPU warm-up (~2 min); the sibling
 * bounded poll `SPLIT_TIMEOUT_MS` uses 120s for a much smaller unit of work.
 * It is NOT the stream stall-banner window (30s) — that window warns, it does not kill.
 */
export const SCAN_PROGRESS_TIMEOUT_MS = 300_000;

type ScanWaiter = {
  resolve: () => void;
  reject: (error: Error) => void;
  started: boolean;
  progressKey: string;
  timeoutId: number;
};

const scanWaitFailedMessage = (): string => __('People identification failed. Nothing was described.', 'alt-context');
const scanWaitCancelledMessage = (): string => __('People identification was cancelled.', 'alt-context');
const scanWaitSupersededMessage = (): string =>
  __('People identification was superseded by a newer run.', 'alt-context');

export const JobPipelineProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { setAdvancedOpen } = useWorkbenchNav();
  const [clusterMessage, setClusterMessage] = useState<string | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);

  const {
    jobId,
    jobHistory,
    jobStatuses,
    historySource = 'unavailable',
    rememberJob,
    selectJob,
    forgetJob,
    clearHistory,
  } = useRecognitionJobHistory();

  const {
    isScanRunning,
    isCancellingScan,
    currentPhase,
    projectionSyncState,
    projectionError,
    statusText,
    scanProgress,
    clusterProgress,
    batchRunStatus,
    scanStallSeconds,
    etaSeconds,
    isOnline,
    isPrimary,
    latestJobId,
    activeJobIds,
    scan,
    cancelScan,
    cluster,
    retryClustering,
    canRetryClustering,
    retryProjectionSync,
    retryScanStream,
  } = useJobStateMachine({
    jobId,
    onJobNotFound: (staleJobId: string) => {
      forgetJob(staleJobId);
    },
    onScanStart: () => {
      setScanError(null);
    },
    onScanComplete: (jobIds: string[]) => {
      if (jobIds.length > 0) {
        rememberJob(jobIds[0]);
      }
      setClusterMessage(null);
    },
    onScanError: (message: string) => {
      setScanError(message);
    },
    onClusterComplete: (data: ClusterResponse) => {
      setScanError(null);
      setClusterMessage(
        sprintf(
          __('Created %d clusters for %d identities.', 'alt-context'),
          data.clusters_created,
          data.total_identities_clustered,
        ),
      );
    },
    onClusterError: (message: string) => {
      setScanError(message);
    },
  });

  const scanWaiterRef = useRef<ScanWaiter | null>(null);
  const activeJobIdsRef = useRef<string[]>(activeJobIds);
  const cancelScanRef = useRef(cancelScan);
  useEffect(() => {
    activeJobIdsRef.current = activeJobIds;
    cancelScanRef.current = cancelScan;
  }, [activeJobIds, cancelScan]);

  const armWaiterDeadline = useCallback((waiter: ScanWaiter, timeoutMs: number): void => {
    window.clearTimeout(waiter.timeoutId);
    waiter.timeoutId = window.setTimeout(() => {
      if (scanWaiterRef.current !== waiter) {
        return;
      }
      scanWaiterRef.current = null;
      // The bound that gives up must also free what it was waiting on (RES-04/RES-20):
      // aborting a started run without cancelling it would orphan a live scan.
      const jobIds = activeJobIdsRef.current;
      if (waiter.started && jobIds.length > 0) {
        cancelScanRef.current(jobIds);
      }
      waiter.reject(new Error(scanWaitFailedMessage()));
    }, timeoutMs);
  }, []);

  const scanAndWait = useCallback(
    (mediaIds: number[]) =>
      new Promise<void>((resolve, reject) => {
        const superseded = scanWaiterRef.current;
        if (superseded) {
          scanWaiterRef.current = null;
          superseded.reject(new Error(scanWaitSupersededMessage()));
        }
        const waiter: ScanWaiter = {
          resolve: () => {
            window.clearTimeout(waiter.timeoutId);
            resolve();
          },
          reject: (error: Error) => {
            window.clearTimeout(waiter.timeoutId);
            reject(error);
          },
          started: false,
          progressKey: '',
          timeoutId: 0,
        };
        scanWaiterRef.current = waiter;
        armWaiterDeadline(waiter, SCAN_START_TIMEOUT_MS);
        setScanError(null);
        scan(mediaIds);
      }),
    [armWaiterDeadline, scan],
  );

  const cancelScanAndReject = useCallback(
    (jobIds: string[]) => {
      const waiter = scanWaiterRef.current;
      scanWaiterRef.current = null;
      waiter?.reject(new Error(scanWaitCancelledMessage()));
      cancelScan(jobIds);
    },
    [cancelScan],
  );

  // Liveness signature of the in-flight run: any change here is evidence of progress.
  const scanProgressKey = [
    scanProgress?.completed ?? '',
    scanProgress?.total ?? '',
    scanProgress?.phase ?? '',
    batchRunStatus?.completed_total ?? '',
    batchRunStatus?.failed_total ?? '',
  ].join(':');

  useEffect(() => {
    const waiter = scanWaiterRef.current;
    if (!waiter) return;
    if (scanError) {
      scanWaiterRef.current = null;
      waiter.reject(new Error(scanError));
      return;
    }
    if (isScanRunning) {
      // Bound the silence, not the duration: re-arm on start and on every observed
      // progress change so a slow-but-alive run (cold GPU warm-up) is not aborted.
      if (!waiter.started || waiter.progressKey !== scanProgressKey) {
        waiter.started = true;
        waiter.progressKey = scanProgressKey;
        armWaiterDeadline(waiter, SCAN_PROGRESS_TIMEOUT_MS);
      }
      return;
    }
    if (!waiter.started) return;
    scanWaiterRef.current = null;
    if (batchRunStatus?.terminal_state && batchRunStatus.completed_total === 0 && batchRunStatus.failed_total > 0) {
      waiter.reject(new Error(scanWaitFailedMessage()));
      return;
    }
    waiter.resolve();
  }, [armWaiterDeadline, batchRunStatus, isScanRunning, scanError, scanProgressKey]);

  useEffect(
    () => () => {
      const waiter = scanWaiterRef.current;
      if (!waiter) {
        return;
      }
      scanWaiterRef.current = null;
      waiter.reject(new Error(scanWaitCancelledMessage()));
    },
    [],
  );

  const handleSelectJobFromHistory = React.useCallback(
    (id: string): void => {
      selectJob(id);
      setAdvancedOpen(true);
    },
    [selectJob, setAdvancedOpen],
  );

  const value = useMemo<JobPipelineContextValue>(
    () => ({
      scanRun: {
        isScanning: isScanRunning,
        isCancelling: isCancellingScan,
        statusText,
        jobId: latestJobId ?? jobId,
        errorMessage: scanError,
        onRetryClustering: canRetryClustering
          ? () => {
              setScanError(null);
              retryClustering();
            }
          : undefined,
        progress:
          (currentPhase === 'clustering' || currentPhase === 'projecting') && clusterProgress
            ? clusterProgress
            : scanProgress,
        batchRunStatus,
        stallSeconds: scanStallSeconds,
        etaSeconds,
        isSynced: !isPrimary && !!latestJobId,
      },
      status: {
        currentPhase,
        projectionSyncState,
        projectionError,
        isOnline,
        scanProgress,
        clusterProgress,
        clusterMessage,
      },
      history: {
        jobId,
        latestJobId,
        activeJobIds,
        jobHistory,
        jobStatuses,
        historySource,
      },
      scan,
      scanAndWait,
      cancelScan: cancelScanAndReject,
      cluster,
      retryClustering,
      retryProjectionSync,
      retryScanStream,
      handleSelectJobFromHistory,
      clearHistory,
    }),
    [
      isScanRunning,
      isCancellingScan,
      statusText,
      latestJobId,
      jobId,
      scanError,
      canRetryClustering,
      retryClustering,
      currentPhase,
      clusterProgress,
      scanProgress,
      batchRunStatus,
      scanStallSeconds,
      etaSeconds,
      isPrimary,
      projectionSyncState,
      projectionError,
      isOnline,
      clusterMessage,
      activeJobIds,
      jobHistory,
      jobStatuses,
      historySource,
      scan,
      scanAndWait,
      cancelScanAndReject,
      cluster,
      retryProjectionSync,
      retryScanStream,
      handleSelectJobFromHistory,
      clearHistory,
    ],
  );

  return <JobPipelineContext.Provider value={value}>{children}</JobPipelineContext.Provider>;
};

export const useJobPipeline = (): JobPipelineContextValue => {
  const context = useContext(JobPipelineContext);
  if (!context) {
    throw new Error('useJobPipeline must be used within a JobPipelineProvider');
  }
  return context;
};
