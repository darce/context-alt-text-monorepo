import { __, sprintf } from '@wordpress/i18n';

import type { JobProgress, JobStatusResponse } from '../api/recognition/types/scan';
import type { PersistedJob } from './useJobPersistence';
import type { JobStatus } from './useJobProgressStream';

export type PipelinePhase = 'idle' | 'scanning' | 'clustering' | 'projecting';
export type JobPhase = PipelinePhase;

export const getLatestJobByType = (jobs: PersistedJob[], type: PersistedJob['type']): PersistedJob | null => {
  const typedJobs = jobs.filter((job) => job.type === type);
  return typedJobs[typedJobs.length - 1] ?? null;
};

export const derivePipelinePhase = (
  latestScanJob: PersistedJob | null,
  latestClusterJob: PersistedJob | null,
  scanStatus: JobStatusResponse | undefined,
): PipelinePhase => {
  // Trust the backend when it reports awaiting_projection.  The previous guard
  // `(latestClusterJob || latestScanJob)` prevented entering 'projecting' when
  // the backend auto-chains a clustering job because the scan job is removed
  // from activeJobs on SSE completion and no local clustering entry exists.
  if (scanStatus?.progress?.phase === 'awaiting_projection') {
    return 'projecting';
  }
  // Backend auto-chained a clustering job; frontend never registered a local cluster entry.
  // Guard: only treat as active when backend reports a non-terminal state so stale cached
  // responses do not lock the UI in the clustering phase after the job finishes.
  const backendClusteringActive =
    scanStatus?.type === 'clustering' && scanStatus.status !== 'completed' && scanStatus.status !== 'failed';
  if (backendClusteringActive) {
    return 'clustering';
  }
  if (latestClusterJob) {
    return 'clustering';
  }
  if (latestScanJob) {
    return 'scanning';
  }
  return 'idle';
};

export const deriveJobPhase = derivePipelinePhase;

export const deriveLatestJobId = (
  currentPhase: PipelinePhase,
  latestScanJob: PersistedJob | null,
  latestClusterJob: PersistedJob | null,
  scanStatus?: JobStatusResponse,
): string | null => {
  if (currentPhase === 'clustering' || currentPhase === 'projecting') {
    // Fall back to the backend job id so the SSE stream can connect even when
    // the frontend never registered a local cluster job entry.
    return latestClusterJob?.id ?? scanStatus?.id ?? null;
  }
  if (currentPhase === 'scanning') {
    return latestScanJob?.id ?? null;
  }
  return null;
};

interface StatusTextParams {
  clusterPending: boolean;
  sseStatus: JobStatus;
  sseProgress: JobProgress | null;
  activeJobIds: string[];
  scanStatus: JobStatusResponse | undefined;
  latestJobId: string | null;
  scanPending: boolean;
}

export const buildStatusText = ({
  clusterPending,
  sseStatus,
  sseProgress,
  activeJobIds,
  scanStatus,
  latestJobId,
  scanPending,
}: StatusTextParams): string | undefined => {
  if (clusterPending || sseProgress?.phase === 'clustering') {
    if (sseProgress) {
      return sprintf(__('Clustering %d/%d identities…', 'alt-context'), sseProgress.completed, sseProgress.total);
    }
    return __('Clustering faces…', 'alt-context');
  }

  if (sseProgress?.phase === 'awaiting_projection' || scanStatus?.progress?.phase === 'awaiting_projection') {
    return __('Syncing projected results…', 'alt-context');
  }

  if (activeJobIds.length > 0) {
    if (sseProgress?.phase === 'queued') {
      return sprintf(__('Queued %d items…', 'alt-context'), sseProgress.total);
    }
    if (sseProgress?.phase === 'detecting') {
      const processed = sseProgress.images_processed ?? sseProgress.completed;
      const faces = sseProgress.faces_found;
      if (typeof faces === 'number') {
        return sprintf(
          __('Detecting faces… %d/%d processed · %d faces found', 'alt-context'),
          processed,
          sseProgress.total,
          faces,
        );
      }
      return sprintf(__('Detecting faces… %d/%d processed', 'alt-context'), processed, sseProgress.total);
    }
    if (sseStatus === 'completed') {
      return 'completed';
    }
    if (sseStatus === 'failed') {
      return 'failed';
    }

    if (scanStatus?.id === latestJobId && scanStatus.message) {
      return scanStatus.message;
    }

    return sseStatus === 'pending' ? __('Starting scan…', 'alt-context') : __('Processing media…', 'alt-context');
  }

  const statusMessage = scanStatus?.message;
  const statusValue = scanStatus?.status;
  if (statusMessage && statusValue !== 'completed' && statusValue !== 'failed') {
    return statusMessage;
  }
  return statusValue ?? (scanPending ? __('Starting scan…', 'alt-context') : undefined);
};

interface ScanProgressParams {
  currentPhase: PipelinePhase;
  activeJobIds: string[];
  activeJobs: PersistedJob[];
  sseProgress: JobProgress | null;
  latestScanJob: PersistedJob | null;
  fallbackProgress: JobProgress | null | undefined;
}

export const buildScanProgress = ({
  currentPhase,
  activeJobIds,
  activeJobs,
  sseProgress,
  latestScanJob,
  fallbackProgress,
}: ScanProgressParams): JobProgress | null => {
  if (currentPhase === 'clustering' || currentPhase === 'projecting') {
    return fallbackProgress ?? null;
  }

  if (activeJobIds.length === 0) {
    return fallbackProgress ?? null;
  }

  const scanJobs = activeJobs.filter((job) => job.type === 'scan');
  if (scanJobs.length > 1 && sseProgress) {
    const totalItems = scanJobs.reduce((sum, job) => sum + job.totalItems, 0);
    const currentJobIndex = scanJobs.findIndex((job) => job.id === latestScanJob?.id);
    const completedJobs = currentJobIndex >= 0 ? currentJobIndex : 0;
    const completedFromPriorJobs = scanJobs.slice(0, completedJobs).reduce((sum, job) => sum + job.totalItems, 0);
    const currentProcessed = sseProgress.images_processed ?? sseProgress.completed;
    const aggregatedCompleted = completedFromPriorJobs + sseProgress.completed;
    const aggregatedProcessed = completedFromPriorJobs + currentProcessed;
    return {
      completed: aggregatedCompleted,
      total: totalItems,
      ...(sseProgress.phase ? { phase: sseProgress.phase } : {}),
      ...(typeof currentProcessed === 'number' ? { images_processed: aggregatedProcessed } : {}),
      ...(typeof sseProgress.faces_found === 'number' ? { faces_found: sseProgress.faces_found } : {}),
    };
  }

  return sseProgress;
};

export const buildClusterProgress = (
  currentPhase: PipelinePhase,
  sseProgress: JobProgress | null,
): JobProgress | null => {
  if (currentPhase === 'clustering' || currentPhase === 'projecting') {
    return sseProgress;
  }
  return null;
};

interface ScanRunningParams {
  scanPending: boolean;
  waitingForCompletion: boolean;
  activeJobIds: string[];
  sseStatus: JobStatus;
  scanStatus: JobStatusResponse | undefined;
}

export const isScanRunning = ({
  scanPending,
  waitingForCompletion,
  activeJobIds,
  sseStatus,
  scanStatus,
}: ScanRunningParams): boolean => {
  if (scanPending || waitingForCompletion) {
    return true;
  }
  if (activeJobIds.length > 0) {
    return sseStatus === 'pending' || sseStatus === 'running';
  }
  const status = scanStatus?.status;
  return status === 'pending' || status === 'running';
};
