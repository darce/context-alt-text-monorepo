import { useMemo } from 'react';

import type { BatchRunStatus, JobProgress, JobStatusResponse } from '../api/recognition/types/scan';
import { buildClusterProgress, buildScanProgress, buildStatusText, isScanRunning } from './jobStateMachineProgress';
import type { PipelinePhase } from './jobStateMachineUtils';
import type { PersistedJob } from './useJobPersistence';
import type { JobStatus } from './useJobProgressStream';
import { useMonotonicScanProgress } from './useMonotonicScanProgress';

interface UseJobStateMachineDerivedStateOptions {
  currentPhase: PipelinePhase;
  activeJobIds: string[];
  activeJobs: PersistedJob[];
  latestScanJob: PersistedJob | null;
  latestJobId: string | null;
  scanPending: boolean;
  clusterPending: boolean;
  waitingForCompletion: boolean;
  scanStatus: JobStatusResponse | undefined;
  batchRunStatus?: BatchRunStatus;
  sseStatus: JobStatus;
  sseProgress: JobProgress | null;
  stalledForSeconds: number | null | undefined;
}

export const useJobStateMachineDerivedState = ({
  currentPhase,
  activeJobIds,
  activeJobs,
  latestScanJob,
  latestJobId,
  scanPending,
  clusterPending,
  waitingForCompletion,
  scanStatus,
  batchRunStatus,
  sseStatus,
  sseProgress,
  stalledForSeconds,
}: UseJobStateMachineDerivedStateOptions) => {
  const statusText = useMemo(
    () =>
      buildStatusText({
        clusterPending,
        sseStatus,
        sseProgress,
        activeJobIds,
        scanStatus,
        batchRunStatus,
        latestJobId,
        scanPending,
      }),
    [activeJobIds, batchRunStatus, clusterPending, latestJobId, scanPending, scanStatus, sseProgress, sseStatus],
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
    () => buildClusterProgress(currentPhase, sseProgress),
    [currentPhase, sseProgress],
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

  const scanStallSeconds = useMemo(() => {
    if (typeof stalledForSeconds !== 'number') {
      return null;
    }

    return currentPhase === 'idle' ? null : stalledForSeconds;
  }, [currentPhase, stalledForSeconds]);

  return {
    statusText,
    scanProgress,
    clusterProgress,
    isScanRunning: currentIsScanRunning,
    scanStallSeconds,
  };
};