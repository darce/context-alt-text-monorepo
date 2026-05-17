import { describe, expect, it } from 'vitest';

import type { BatchRunStatus } from '../../api/recognition/types/scan';
import { buildScanProgress, buildStatusText, enforceMonotonicProgress } from '../jobStateMachineProgress';

const makeBatchRunStatus = (overrides: Partial<BatchRunStatus> = {}): BatchRunStatus => ({
  id: 'run-1',
  submitted_total: 20,
  accepted_total: 20,
  completed_total: 10,
  failed_total: 0,
  cancelled_total: 0,
  unreadable_media_ids: [],
  failed_batches: [],
  child_job_ids: [],
  terminal_state: false,
  ...overrides,
});

describe('buildScanProgress', () => {
  it('keeps completed scan totals when clustering starts before the fallback scan payload catches up', () => {
    const result = buildScanProgress({
      currentPhase: 'clustering',
      activeJobIds: ['scan-1', 'cluster-1'],
      activeJobs: [
        { id: 'scan-1', type: 'scan', startedAt: 1, totalItems: 10 },
        { id: 'cluster-1', type: 'clustering', startedAt: 2, totalItems: 0 },
      ],
      sseProgress: { completed: 15, total: 21, phase: 'clustering' },
      latestScanJob: { id: 'scan-1', type: 'scan', startedAt: 1, totalItems: 10 },
      batchRunStatus: undefined,
      fallbackProgress: {
        completed: 0,
        total: 10,
        phase: 'detecting',
        images_processed: 0,
      },
    });

    expect(result).toEqual({
      completed: 10,
      total: 10,
      phase: 'complete',
      images_processed: 10,
    });
  });
});

describe('buildStatusText batch-run denominator', () => {
  it('uses processed total (completed + failed + cancelled) when failures are present', () => {
    const batchRunStatus = makeBatchRunStatus({
      submitted_total: 20,
      completed_total: 10,
      failed_total: 3,
      cancelled_total: 2,
    });

    const text = buildStatusText({
      clusterPending: false,
      sseStatus: 'running',
      sseProgress: null,
      activeJobIds: [],
      scanStatus: undefined,
      batchRunStatus,
      latestJobId: null,
      scanPending: false,
    });

    expect(text).toContain('15/20');
    expect(text).toContain('3 failed');
  });
});

describe('enforceMonotonicProgress', () => {
  it('returns next unchanged when there is no prior snapshot', () => {
    const next = { completed: 5, total: 20, phase: 'detecting' as const, images_processed: 5 };
    expect(enforceMonotonicProgress(null, next)).toEqual(next);
  });

  it('returns null when both prev and next are null', () => {
    expect(enforceMonotonicProgress(null, null)).toBeNull();
  });

  it('preserves prev when next is null', () => {
    const prev = { completed: 3, total: 10, phase: 'detecting' as const };
    expect(enforceMonotonicProgress(prev, null)).toBe(prev);
  });

  it('clamps a regressing batch-run completed total to the prior maximum', () => {
    const prev = { completed: 12, total: 20, phase: 'detecting' as const, images_processed: 12 };
    const next = { completed: 8, total: 20, phase: 'detecting' as const, images_processed: 8 };
    expect(enforceMonotonicProgress(prev, next)).toEqual({
      completed: 12,
      total: 20,
      phase: 'detecting',
      images_processed: 12,
    });
  });

  it('clamps an SSE fallback completed regression while preserving the new phase', () => {
    const prev = { completed: 15, total: 20, phase: 'detecting' as const };
    const next = { completed: 7, total: 20, phase: 'clustering' as const };
    const result = enforceMonotonicProgress(prev, next);
    expect(result?.completed).toBe(15);
    expect(result?.phase).toBe('clustering');
  });

  it('clamps a regressing faces_found while passing through monotonic counts', () => {
    const prev = { completed: 10, total: 20, phase: 'detecting' as const, faces_found: 7 };
    const next = { completed: 11, total: 20, phase: 'detecting' as const, faces_found: 4 };
    expect(enforceMonotonicProgress(prev, next)).toMatchObject({
      completed: 11,
      faces_found: 7,
    });
  });

  it('passes through a strictly larger snapshot unchanged', () => {
    const prev = { completed: 3, total: 10, phase: 'detecting' as const, images_processed: 3, faces_found: 1 };
    const next = { completed: 7, total: 10, phase: 'detecting' as const, images_processed: 7, faces_found: 3 };
    expect(enforceMonotonicProgress(prev, next)).toEqual(next);
  });

  it('keeps images_processed monotonic when next omits the field but completed advances', () => {
    const prev = { completed: 5, total: 10, phase: 'detecting' as const, images_processed: 8 };
    const next = { completed: 9, total: 10, phase: 'detecting' as const };
    expect(enforceMonotonicProgress(prev, next)).toMatchObject({
      completed: 9,
      images_processed: 9,
    });
  });
});