import type { BatchRunStatus, JobStatusResponse } from '../api/recognition/types/scan';
import type { PersistedJob } from './useJobPersistence';

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
  batchRunStatus?: BatchRunStatus,
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
  if (batchRunStatus) {
    if (!batchRunStatus.terminal_state) {
      return 'scanning';
    }
    if (batchRunStatus.failed_total > 0 || batchRunStatus.cancelled_total > 0) {
      return 'idle';
    }
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

