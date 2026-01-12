import { __, sprintf } from '@wordpress/i18n';

import type { JobProgress, JobStatusResponse } from '../api/recognition/types/scan';
import type { PersistedJob } from './useJobPersistence';
import type { JobStatus } from './useJobProgressStream';

export type JobPhase = 'idle' | 'scanning' | 'clustering';

export const getLatestJobByType = (jobs: PersistedJob[], type: PersistedJob['type']): PersistedJob | null => {
  const typedJobs = jobs.filter((job) => job.type === type);
  return typedJobs[typedJobs.length - 1] ?? null;
};

export const deriveJobPhase = (latestScanJob: PersistedJob | null, latestClusterJob: PersistedJob | null): JobPhase => {
  if (latestClusterJob) {
    return 'clustering';
  }
  if (latestScanJob) {
    return 'scanning';
  }
  return 'idle';
};

export const deriveLatestJobId = (
  currentPhase: JobPhase,
  latestScanJob: PersistedJob | null,
  latestClusterJob: PersistedJob | null,
): string | null => {
  if (currentPhase === 'clustering') {
    return latestClusterJob?.id ?? null;
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
  if (clusterPending || sseStatus === 'clustering') {
    if (sseProgress && sseStatus === 'clustering') {
      return sprintf(__('Clustering %d/%d identities…', 'alt-context'), sseProgress.completed, sseProgress.total);
    }
    return __('Clustering faces…', 'alt-context');
  }

  if (activeJobIds.length > 0) {
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
  activeJobIds: string[];
  activeJobs: PersistedJob[];
  sseProgress: JobProgress | null;
  latestScanJob: PersistedJob | null;
  fallbackProgress: JobProgress | null | undefined;
}

export const buildScanProgress = ({
  activeJobIds,
  activeJobs,
  sseProgress,
  latestScanJob,
  fallbackProgress,
}: ScanProgressParams): JobProgress | null => {
  if (activeJobIds.length === 0) {
    return fallbackProgress ?? null;
  }

  const scanJobs = activeJobs.filter((job) => job.type === 'scan');
  if (scanJobs.length > 1 && sseProgress) {
    const totalItems = scanJobs.reduce((sum, job) => sum + job.totalItems, 0);
    const currentJobIndex = scanJobs.findIndex((job) => job.id === latestScanJob?.id);
    const completedJobs = currentJobIndex >= 0 ? currentJobIndex : 0;
    const completedFromPriorJobs = scanJobs.slice(0, completedJobs).reduce((sum, job) => sum + job.totalItems, 0);
    return {
      completed: completedFromPriorJobs + sseProgress.completed,
      total: totalItems,
    };
  }

  return sseProgress;
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
