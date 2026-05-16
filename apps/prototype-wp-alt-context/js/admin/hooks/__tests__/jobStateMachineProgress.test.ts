import { describe, expect, it } from 'vitest';

import { buildScanProgress } from '../jobStateMachineProgress';

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