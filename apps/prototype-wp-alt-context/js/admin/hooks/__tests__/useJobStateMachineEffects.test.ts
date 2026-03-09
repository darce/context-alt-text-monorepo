import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useJobStateMachineEffects } from '../useJobStateMachineEffects';

describe('useJobStateMachineEffects', () => {
  const buildBaseOptions = () => ({
    scanStatus: {
      id: 'job-2',
      type: 'clustering' as const,
      status: 'completed' as const,
      progress: {
        completed: 10,
        total: 10,
        phase: 'awaiting_projection' as const,
      },
      started_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
      snapshot_version: 123,
      source_job_id: 'job-2',
      projection_acknowledged_at: null,
    },
    queryClient: { invalidateQueries: vi.fn() } as never,
    activeJobIds: ['job-2'],
    activeJobs: [{ id: 'job-2', type: 'clustering' as const, startedAt: Date.now(), totalItems: 10 }],
    isWaitingForScanCompletion: false,
    setIsWaitingForScanCompletion: vi.fn(),
    latestScanJob: null,
    sseStatus: 'completed' as const,
    removeJob: vi.fn(),
    cluster: vi.fn(),
    latestClusterJob: { id: 'job-2', type: 'clustering' as const, startedAt: Date.now(), totalItems: 10 },
    currentPhase: 'projecting' as const,
    syncTrigger: { mutateAsync: vi.fn() } as never,
    acknowledgeProjection: { mutateAsync: vi.fn() } as never,
    projectionSyncNonce: 0,
    setProjectionSyncState: vi.fn(),
    setProjectionError: vi.fn(),
  });

  it('does not trigger manual clustering when the backend already transitioned the scan job', async () => {
    const invalidateQueries = vi.fn();
    const removeJob = vi.fn();
    const cluster = vi.fn();
    const setIsWaitingForScanCompletion = vi.fn();
    const setProjectionSyncState = vi.fn();
    const setProjectionError = vi.fn();

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
        syncTrigger: { mutateAsync: vi.fn() } as never,
        acknowledgeProjection: { mutateAsync: vi.fn() } as never,
        projectionSyncNonce: 0,
        setProjectionSyncState,
        setProjectionError,
      }),
    );

    await waitFor(() => {
      expect(removeJob).toHaveBeenCalledWith('job-1');
    });
    expect(cluster).not.toHaveBeenCalled();
  });

  it('records projection sync failures and retries when the nonce changes', async () => {
    const options = buildBaseOptions();
    const syncMutateAsync = vi
      .fn()
      .mockRejectedValueOnce(new Error('Waiting for service…'))
      .mockResolvedValueOnce({
        synced: true,
        reason: 'ok',
        last_snapshot_version: 123,
        last_synced_at: '2026-03-09T10:00:00Z',
        is_stale: false,
      });
    const acknowledgeMutateAsync = vi.fn().mockResolvedValue({ status: 'acknowledged', snapshot_version: 123 });

    options.syncTrigger = { mutateAsync: syncMutateAsync } as never;
    options.acknowledgeProjection = { mutateAsync: acknowledgeMutateAsync } as never;

    const { rerender } = renderHook((props) => useJobStateMachineEffects(props), {
      initialProps: options,
    });

    await waitFor(() => {
      expect(options.setProjectionSyncState).toHaveBeenCalledWith('error');
      expect(options.setProjectionError).toHaveBeenCalledWith('Waiting for service…');
    });

    rerender({
      ...options,
      projectionSyncNonce: 1,
    });

    await waitFor(() => {
      expect(syncMutateAsync).toHaveBeenCalledTimes(2);
      expect(acknowledgeMutateAsync).toHaveBeenCalledWith({ jobId: 'job-2', snapshotVersion: 123 });
      expect(options.removeJob).toHaveBeenCalledWith('job-2');
    });
  });
});
