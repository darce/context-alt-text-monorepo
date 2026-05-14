import { describe, expect, it } from 'vitest';

import { buildScanProgress } from '../jobStateMachineUtils';
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
