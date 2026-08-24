import type { BatchRunStatus, JobStatusResponse } from '../api/recognition/types/scan';
import type { PersistedJob } from './useJobPersistence';

export type PipelinePhase = 'idle' | 'scanning' | 'clustering' | 'projecting';

type ScanJobStatus = JobStatusResponse['status'];

// Terminal partial-success: some items succeeded, some failed. The description-service emits
// completed_with_errors as a terminal status, so recognition-job consumers must treat it as a
// completed scan (refresh/finalize). Centralized so the check is not scattered as `=== 'completed'`
// literals across hooks (sr-007, BND-1).
export const SCAN_SUCCESS_STATUSES = ['completed', 'completed_with_errors'] as const satisfies readonly ScanJobStatus[];

// Accepts any status string (REST JobStatusResponse['status'] OR the SSE JobStatus channel, which
// also carries non-REST values like 'clustering'), so both channels can share one terminal check.
export const isScanSuccessStatus = (status: string | undefined): boolean =>
  status !== undefined && (SCAN_SUCCESS_STATUSES as readonly string[]).includes(status);

// Terminal = succeeded (incl. partial) or hard-failed.
export const isScanTerminalStatus = (status: string | undefined): boolean =>
  isScanSuccessStatus(status) || status === 'failed';

export const isScanActiveStatus = (status: string | undefined): boolean =>
  status !== undefined && status.length > 0 && !isScanTerminalStatus(status);

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
  const backendClusteringActive = scanStatus?.type === 'clustering' && !isScanTerminalStatus(scanStatus.status);
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
