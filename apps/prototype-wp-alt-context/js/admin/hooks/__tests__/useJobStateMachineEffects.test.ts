import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useJobStateMachineEffects } from '../useJobStateMachineEffects';

describe('useJobStateMachineEffects', () => {
  it('does not trigger manual clustering when the backend already transitioned the scan job', async () => {
    const invalidateQueries = vi.fn();
    const removeJob = vi.fn();
    const cluster = vi.fn();
    const setIsWaitingForScanCompletion = vi.fn();

    renderHook(() =>
      useJobStateMachineEffects({
        scanStatus: {
          id: 'job-1',
          type: 'clustering',
          status: 'completed',
          progress: {
            completed: 14,
            total: 14,
            phase: 'clustering',
            clusters_created: 3,
          },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
          message: 'Clustering identities',
        },
        queryClient: { invalidateQueries } as never,
        activeJobIds: ['job-1'],
        activeJobs: [{ id: 'job-1', type: 'scan', startedAt: Date.now(), totalItems: 500 }],
        isWaitingForScanCompletion: true,
        setIsWaitingForScanCompletion,
        latestScanJob: { id: 'job-1', type: 'scan', startedAt: Date.now(), totalItems: 500 },
        sseStatus: 'completed',
        removeJob,
        cluster,
        latestClusterJob: null,
        currentPhase: 'scanning',
      }),
    );

    await waitFor(() => {
      expect(removeJob).toHaveBeenCalledWith('job-1');
    });
    expect(cluster).not.toHaveBeenCalled();
  });
});
