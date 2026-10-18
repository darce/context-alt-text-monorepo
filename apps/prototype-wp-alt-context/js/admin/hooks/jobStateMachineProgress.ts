import { __, sprintf } from '@wordpress/i18n';

import type { BatchRunStatus, JobProgress, JobStatusResponse } from '../api/recognition/types/scan';
import { JOB_PHASE_PRESENTATION } from '../pages/workbench/phasePresentation';
import { formatClusterQueuedStatus } from './clusterAutoRetry';
import type { PersistedJob } from './useJobPersistence';
import type { JobStatus } from './useJobProgressStream';
import { isScanSuccessStatus, isScanTerminalStatus, type PipelinePhase } from './jobStateMachineUtils';

interface StatusTextParams {
  clusterPending: boolean;
  /** Seconds until the next bounded cluster auto-retry (honest queued status). */
  clusterQueuedSeconds?: number | null;
  sseStatus: JobStatus;
  sseProgress: JobProgress | null;
  activeJobIds: string[];
  scanStatus: JobStatusResponse | undefined;
  batchRunStatus?: BatchRunStatus;
  latestJobId: string | null;
  scanPending: boolean;
}

export const buildStatusText = ({
  clusterPending,
  clusterQueuedSeconds,
  sseStatus,
  sseProgress,
  activeJobIds,
  scanStatus,
  batchRunStatus,
  latestJobId,
  scanPending,
}: StatusTextParams): string | undefined => {
  // Cross-signal precedence below (which signal wins) is behavior and stays
  // here; every phase-derived string comes from JOB_PHASE_PRESENTATION.
  // Queued auto-retry sits above live clustering progress so AGT-10 stays honest
  // while the mutation is idle between 429 attempts.
  if (typeof clusterQueuedSeconds === 'number' && clusterQueuedSeconds > 0) {
    return formatClusterQueuedStatus(clusterQueuedSeconds);
  }

  if (clusterPending || sseProgress?.phase === 'clustering') {
    if (sseProgress) {
      return JOB_PHASE_PRESENTATION.clustering.status({
        completed: sseProgress.completed,
        total: sseProgress.total,
      });
    }
    return JOB_PHASE_PRESENTATION.clustering.statusFallback;
  }

  if (sseProgress?.phase === 'awaiting_projection' || scanStatus?.progress?.phase === 'awaiting_projection') {
    return JOB_PHASE_PRESENTATION.awaiting_projection.statusFallback;
  }

  if (batchRunStatus && batchRunStatus.submitted_total > 0) {
    const processedTotal =
      batchRunStatus.completed_total + batchRunStatus.failed_total + batchRunStatus.cancelled_total;
    if (batchRunStatus.failed_total > 0) {
      return sprintf(
        __('Processed %1$d/%2$d (%3$d failed)', 'alt-context'),
        processedTotal,
        batchRunStatus.submitted_total,
        batchRunStatus.failed_total,
      );
    }

    if (!batchRunStatus.terminal_state) {
      return sprintf(__('Processed %1$d/%2$d images', 'alt-context'), processedTotal, batchRunStatus.submitted_total);
    }
  }

  if (activeJobIds.length > 0) {
    if (sseProgress?.phase === 'queued') {
      return JOB_PHASE_PRESENTATION.queued.status({
        completed: sseProgress.completed,
        total: sseProgress.total,
      });
    }
    if (sseProgress?.phase === 'detecting') {
      // Signal selection (images_processed over completed) stays here; the
      // faces-found copy variants live in the map's builder.
      const processed = sseProgress.images_processed ?? sseProgress.completed;
      const faces = sseProgress.faces_found;
      return JOB_PHASE_PRESENTATION.detecting.status({
        completed: processed,
        total: sseProgress.total,
        ...(typeof faces === 'number' ? { facesFound: faces } : {}),
      });
    }
    if (isScanSuccessStatus(sseStatus)) {
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
  if (statusMessage && !isScanTerminalStatus(statusValue)) {
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
  batchRunStatus?: BatchRunStatus;
  fallbackProgress: JobProgress | null | undefined;
}

const buildCompletedScanSnapshot = (
  currentPhase: PipelinePhase,
  scanJobs: PersistedJob[],
  latestScanJob: PersistedJob | null,
  fallbackProgress: JobProgress | null | undefined,
): JobProgress | null => {
  if (fallbackProgress && (fallbackProgress.phase === 'complete' || fallbackProgress.phase === 'awaiting_projection')) {
    return fallbackProgress;
  }

  const totalItems =
    scanJobs.length > 0
      ? scanJobs.reduce((sum, job) => sum + job.totalItems, 0)
      : (latestScanJob?.totalItems ?? fallbackProgress?.total ?? 0);
  if (totalItems <= 0) {
    return fallbackProgress ?? null;
  }

  return {
    completed: totalItems,
    total: totalItems,
    phase: currentPhase === 'projecting' ? 'awaiting_projection' : 'complete',
    images_processed: totalItems,
    ...(typeof fallbackProgress?.faces_found === 'number' ? { faces_found: fallbackProgress.faces_found } : {}),
  };
};

export const buildScanProgress = ({
  currentPhase,
  activeJobIds,
  activeJobs,
  sseProgress,
  latestScanJob,
  batchRunStatus,
  fallbackProgress,
}: ScanProgressParams): JobProgress | null => {
  const scanJobs = activeJobs.filter((job) => job.type === 'scan');

  if (batchRunStatus && batchRunStatus.submitted_total > 0) {
    const processedTotal =
      batchRunStatus.completed_total + batchRunStatus.failed_total + batchRunStatus.cancelled_total;
    return {
      completed: processedTotal,
      total: batchRunStatus.submitted_total,
      phase: batchRunStatus.terminal_state ? 'complete' : 'detecting',
      images_processed: processedTotal,
    };
  }

  if (currentPhase === 'clustering' || currentPhase === 'projecting') {
    return buildCompletedScanSnapshot(currentPhase, scanJobs, latestScanJob, fallbackProgress);
  }
  if (activeJobIds.length === 0) {
    return fallbackProgress ?? null;
  }

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
  fallbackProgress?: JobProgress | null,
): JobProgress | null => {
  if (currentPhase === 'clustering' || currentPhase === 'projecting') {
    if (sseProgress) {
      return sseProgress;
    }
    if (
      fallbackProgress &&
      (fallbackProgress.phase === 'clustering' || fallbackProgress.phase === 'awaiting_projection')
    ) {
      return fallbackProgress;
    }
  }
  return null;
};
