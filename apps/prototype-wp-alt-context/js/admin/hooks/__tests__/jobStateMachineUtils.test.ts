import { describe, expect, it } from 'vitest';

import type { JobStatusResponse } from '../../api/recognition';
import { buildScanProgress } from '../jobStateMachineProgress';
import {
  derivePipelinePhase,
  isScanActiveStatus,
  isScanSuccessStatus,
  isScanTerminalStatus,
} from '../jobStateMachineUtils';
import type { PersistedJob } from '../useJobPersistence';

const scanJob = (overrides: Partial<PersistedJob> = {}): PersistedJob => ({
  id: 'scan-1',
  type: 'scan',
  startedAt: Date.now(),
  totalItems: 10,
  ...overrides,
});

describe('buildScanProgress', () => {
  it('keeps the processed image count monotonic when clustering progress replaces scan progress', () => {
    const progress = buildScanProgress({
      currentPhase: 'clustering',
      activeJobIds: ['scan-1', 'cluster-1'],
      activeJobs: [scanJob(), { id: 'cluster-1', type: 'clustering', startedAt: Date.now(), totalItems: 4 }],
      sseProgress: { completed: 3, total: 4, phase: 'clustering' },
      latestScanJob: scanJob(),
      fallbackProgress: { completed: 3, total: 4, phase: 'clustering' },
    });

    expect(progress).toEqual({
      completed: 10,
      total: 10,
      phase: 'complete',
      images_processed: 10,
    });
  });

  it('keeps the processed image count monotonic while projection sync is pending', () => {
    const progress = buildScanProgress({
      currentPhase: 'projecting',
      activeJobIds: ['scan-1', 'cluster-1'],
      activeJobs: [scanJob(), { id: 'cluster-1', type: 'clustering', startedAt: Date.now(), totalItems: 4 }],
      sseProgress: { completed: 3, total: 4, phase: 'awaiting_projection' },
      latestScanJob: scanJob(),
      fallbackProgress: { completed: 3, total: 4, phase: 'clustering' },
    });

    expect(progress).toEqual({
      completed: 10,
      total: 10,
      phase: 'awaiting_projection',
      images_processed: 10,
    });
  });
});

describe('scan status helpers (BND-1)', () => {
  it('treats completed and completed_with_errors as success, but not failed/running/undefined', () => {
    expect(isScanSuccessStatus('completed')).toBe(true);
    expect(isScanSuccessStatus('completed_with_errors')).toBe(true);
    expect(isScanSuccessStatus('failed')).toBe(false);
    expect(isScanSuccessStatus('running')).toBe(false);
    // SSE-channel-only value (not in the REST union) — the widened string param must handle it.
    expect(isScanSuccessStatus('clustering')).toBe(false);
    expect(isScanSuccessStatus(undefined)).toBe(false);
  });

  it('treats success (incl. partial) and failed as terminal, running as non-terminal', () => {
    expect(isScanTerminalStatus('completed_with_errors')).toBe(true);
    expect(isScanTerminalStatus('failed')).toBe(true);
    expect(isScanTerminalStatus('running')).toBe(false);
  });

  it('derives active recognition statuses from the canonical terminal predicate', () => {
    expect(isScanActiveStatus('running')).toBe(true);
    expect(isScanActiveStatus('cancelled')).toBe(true);
    expect(isScanActiveStatus('completed')).toBe(false);
    expect(isScanActiveStatus('completed_with_errors')).toBe(false);
    expect(isScanActiveStatus('failed')).toBe(false);
    expect(isScanActiveStatus(undefined)).toBe(false);
  });
});

describe('derivePipelinePhase completed_with_errors handling (BND-1)', () => {
  const clusteringScanStatus = (status: JobStatusResponse['status']): JobStatusResponse => ({
    id: 'job-x',
    type: 'clustering',
    status,
    progress: { completed: 10, total: 10, phase: 'clustering' },
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
  });

  it('does not report a completed_with_errors backend clustering job as still clustering', () => {
    // Before the fix the active-guard used `status !== 'completed' && status !== 'failed'`, so a
    // terminal completed_with_errors clustering job read as active and locked the UI in clustering.
    const phase = derivePipelinePhase(null, null, clusteringScanStatus('completed_with_errors'), undefined);

    expect(phase).not.toBe('clustering');
    expect(phase).toBe(derivePipelinePhase(null, null, clusteringScanStatus('completed'), undefined));
  });
});
