import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { BatchRunStatus } from '../../api/recognition';
import type { PipelinePhase } from '../jobStateMachineUtils';
import { useJobStateMachineEffects, type ProjectionSyncState } from '../useJobStateMachineEffects';

describe('useJobStateMachineEffects', () => {
  const buildTerminalBatchRunStatus = (): BatchRunStatus => ({
    batchRunId: 'batch-run-1',
    status: 'completed',
    submitted_total: 14,
    accepted_total: 14,
    completed_total: 14,
    failed_total: 0,
    terminal_state: true,
    jobs: [],
    started_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
  });

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
    activeJobs: [{ id: 'job-2', type: 'clustering' as const, startedAt: Date.now(), totalItems: 10 }],
    isWaitingForScanCompletion: false,
    setIsWaitingForScanCompletion: vi.fn(),
    sseStatus: 'completed' as const,
    removeJob: vi.fn(),
    cluster: vi.fn(),
    latestClusterJob: { id: 'job-2', type: 'clustering' as const, startedAt: Date.now(), totalItems: 10 },
    currentPhase: 'projecting' as PipelinePhase,
    syncTrigger: { mutateAsync: vi.fn() } as never,
    projectionSyncState: 'idle' as ProjectionSyncState,
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
        activeJobs: [{ id: 'job-1', type: 'scan', startedAt: Date.now(), totalItems: 500 }],
        batchRunStatus: buildTerminalBatchRunStatus(),
        isWaitingForScanCompletion: true,
        setIsWaitingForScanCompletion,
        sseStatus: 'completed',
        removeJob,
        cluster,
        latestClusterJob: null,
        currentPhase: 'scanning',
        syncTrigger: { mutateAsync: vi.fn() } as never,
        projectionSyncState: 'idle',
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

  it('keeps projection failures retryable after the backend leaves projecting', async () => {
    const options = buildBaseOptions();
    const syncMutateAsync = vi.fn().mockRejectedValueOnce(new Error('Waiting for service…')).mockResolvedValueOnce({
      synced: true,
      reason: 'ok',
      last_snapshot_version: 123,
      last_synced_at: '2026-03-09T10:00:00Z',
      is_stale: false,
    });

    options.syncTrigger = { mutateAsync: syncMutateAsync } as never;

    const { rerender } = renderHook((props) => useJobStateMachineEffects(props), {
      initialProps: options,
    });

    await waitFor(() => {
      expect(options.setProjectionSyncState).toHaveBeenCalledWith('error');
      expect(options.setProjectionError).toHaveBeenCalledWith('Waiting for service…');
    });

    rerender({
      ...options,
      currentPhase: 'idle',
      projectionSyncState: 'error',
      projectionSyncNonce: 1,
    });

    await waitFor(() => {
      expect(syncMutateAsync).toHaveBeenCalledTimes(2);
      expect(options.setProjectionSyncState).toHaveBeenCalledWith('ready');
      expect(options.setProjectionSyncState).not.toHaveBeenCalledWith('idle');
      expect(options.removeJob).not.toHaveBeenCalled();
    });
  });
});
