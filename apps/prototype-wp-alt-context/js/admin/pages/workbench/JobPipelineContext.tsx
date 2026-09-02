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

  const scanWaiterRef = useRef<{ resolve: () => void; reject: (error: Error) => void; started: boolean } | null>(
    null,
  );
  const scanAndWait = useCallback(
    (mediaIds: number[]) =>
      new Promise<void>((resolve, reject) => {
        scanWaiterRef.current?.reject(
          new Error(__('People identification was superseded by a newer run.', 'alt-context')),
        );
        scanWaiterRef.current = { resolve, reject, started: false };
        setScanError(null);
        scan(mediaIds);
      }),
    [scan],
  );
  const cancelScanAndReject = useCallback(
    (jobIds: string[]) => {
      const waiter = scanWaiterRef.current;
      scanWaiterRef.current = null;
      waiter?.reject(new Error(__('People identification was cancelled.', 'alt-context')));
      cancelScan(jobIds);
    },
    [cancelScan],
  );
  useEffect(() => {
    const waiter = scanWaiterRef.current;
    if (!waiter) return;
    if (scanError) {
      scanWaiterRef.current = null;
      waiter.reject(new Error(scanError));
      return;
    }
    if (isScanRunning) {
      waiter.started = true;
      return;
    }
    if (!waiter.started) return;
    scanWaiterRef.current = null;
    if (batchRunStatus?.terminal_state && batchRunStatus.completed_total === 0 && batchRunStatus.failed_total > 0) {
      waiter.reject(new Error(__('People identification failed. Nothing was described.', 'alt-context')));
      return;
    }
    waiter.resolve();
  }, [isScanRunning, scanError, batchRunStatus]);

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
