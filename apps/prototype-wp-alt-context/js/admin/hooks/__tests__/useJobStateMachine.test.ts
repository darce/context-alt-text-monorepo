import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { useJobStateMachine } from '../useJobStateMachine';
import { useJobPersistence } from '../useJobPersistence';
import { useQueryClient } from '@tanstack/react-query';

const createDeferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });

  return { promise, resolve, reject };
};

// Mocks
vi.mock('../useJobPersistence');
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: vi.fn(),
}));
vi.mock('../useJobProgressStream', () => ({
  useJobProgressStream: vi.fn(() => ({
    progress: null,
    status: 'pending',
    isOnline: true,
    etaSeconds: null,
    isPrimary: true,
  })),
}));
vi.mock('../useRecognitionHooks', () => ({
  useScanIdentities: vi.fn(() => ({ mutate: vi.fn() })),
  useClusterIdentities: vi.fn(() => ({ mutate: vi.fn() })),
  useCancelScanJobs: vi.fn(() => ({ mutate: vi.fn() })),
  useCombinedScanStatus: vi.fn(() => ({ scanStatusQuery: { data: null } })),
}));
vi.mock('../useSyncTrigger', () => ({
  useSyncTrigger: vi.fn(() => ({ mutateAsync: vi.fn() })),
}));

describe('useJobStateMachine', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });
    (useQueryClient as Mock).mockReturnValue({
      invalidateQueries: vi.fn(),
    });
  });

  it('initializes with idle phase', () => {
    const { result } = renderHook(() => useJobStateMachine());
    expect(result.current.currentPhase).toBe('idle');
    expect(result.current.isScanRunning).toBe(false);
  });

  it('reports scanning phase when scan job exists', () => {
    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [{ id: 'job-1', type: 'scan' }],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });
    const { result } = renderHook(() => useJobStateMachine());
    expect(result.current.currentPhase).toBe('scanning');
    expect(result.current.latestJobId).toBe('job-1');
  });

  it('reports clustering phase when clustering job exists', () => {
    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [
        { id: 'job-1', type: 'scan' },
        { id: 'job-2', type: 'clustering' },
      ],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });
    const { result } = renderHook(() => useJobStateMachine());
    expect(result.current.currentPhase).toBe('clustering');
    expect(result.current.latestJobId).toBe('job-2');
  });

  it('keeps scan progress separate from cluster progress', async () => {
    const { useJobProgressStream } = await import('../useJobProgressStream');
    const { useCombinedScanStatus } = await import('../useRecognitionHooks');

    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [
        { id: 'scan-1', type: 'scan', totalItems: 937 },
        { id: 'cluster-1', type: 'clustering', totalItems: 0 },
      ],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });
    (useJobProgressStream as Mock).mockReturnValue({
      progress: { completed: 750, total: 750, phase: 'complete' },
      status: 'completed',
      isOnline: true,
      etaSeconds: null,
      isPrimary: true,
    });
    (useCombinedScanStatus as Mock).mockReturnValue({
      scanStatusQuery: {
        data: {
          id: 'scan-1',
          type: 'analyze',
          status: 'completed',
          progress: { completed: 937, total: 937, phase: 'complete', images_processed: 937 },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
        },
      },
    });

    const { result } = renderHook(() => useJobStateMachine());

    expect(result.current.currentPhase).toBe('clustering');
    expect(result.current.scanProgress).toEqual({
      completed: 937,
      total: 937,
      phase: 'complete',
      images_processed: 937,
    });
    expect(result.current.clusterProgress).toEqual({
      completed: 750,
      total: 750,
      phase: 'complete',
    });
  });

  it('reports projecting phase when the backend exposes awaiting_projection', async () => {
    const { useCombinedScanStatus } = await import('../useRecognitionHooks');
    const { useSyncTrigger } = await import('../useSyncTrigger');
    const syncDeferred = createDeferred<{
      synced: boolean;
      reason: string;
      last_snapshot_version: number;
      last_synced_at: string;
      is_stale: boolean;
    }>();
    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [{ id: 'job-2', type: 'clustering' }],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });
    (useSyncTrigger as Mock).mockReturnValue({ mutateAsync: vi.fn(() => syncDeferred.promise) });
    (useCombinedScanStatus as Mock).mockReturnValue({
      scanStatusQuery: {
        data: {
          id: 'job-1',
          type: 'clustering',
          status: 'completed',
          progress: { completed: 10, total: 10, phase: 'awaiting_projection' },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
          snapshot_version: 123,
          source_job_id: 'job-2',
          projection_acknowledged_at: null,
        },
      },
    });

    const { result, unmount } = renderHook(() => useJobStateMachine());

    await waitFor(() => {
      expect(result.current.currentPhase).toBe('projecting');
      expect(result.current.latestJobId).toBe('job-2');
      expect(result.current.projectionSyncState).toBe('syncing');
    });

    await act(async () => {
      unmount();
      syncDeferred.resolve({
        synced: true,
        reason: 'ok',
        last_snapshot_version: 123,
        last_synced_at: '2026-03-09T10:00:00Z',
        is_stale: false,
      });
      await Promise.resolve();
    });
  });

  it('enters projecting phase when awaiting_projection is reported even without local active jobs', async () => {
    const { useCombinedScanStatus } = await import('../useRecognitionHooks');
    const { useSyncTrigger } = await import('../useSyncTrigger');
    const syncDeferred = createDeferred<{
      synced: boolean;
      reason: string;
      last_snapshot_version: number;
      last_synced_at: string;
      is_stale: boolean;
    }>();
    (useSyncTrigger as Mock).mockReturnValue({ mutateAsync: vi.fn(() => syncDeferred.promise) });
    (useCombinedScanStatus as Mock).mockReturnValue({
      scanStatusQuery: {
        data: {
          id: 'job-1',
          type: 'clustering',
          status: 'completed',
          progress: { completed: 10, total: 10, phase: 'awaiting_projection' },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
          snapshot_version: 123,
          source_job_id: 'job-2',
          projection_acknowledged_at: null,
        },
      },
    });

    const { result, unmount } = renderHook(() => useJobStateMachine());

    await waitFor(() => {
      expect(result.current.currentPhase).toBe('projecting');
      expect(result.current.projectionSyncState).toBe('syncing');
    });

    await act(async () => {
      unmount();
      syncDeferred.resolve({
        synced: true,
        reason: 'ok',
        last_snapshot_version: 123,
        last_synced_at: '2026-03-09T10:00:00Z',
        is_stale: false,
      });
      await Promise.resolve();
    });
  });

  it('forgets remembered jobs when status polling returns 404', async () => {
    const { useCombinedScanStatus } = await import('../useRecognitionHooks');
    const onJobNotFound = vi.fn();

    (useCombinedScanStatus as Mock).mockReturnValue({
      scanStatusQuery: {
        data: null,
        error: new Error('Request failed (404)'),
      },
      multiScanStatus: [],
    });

    renderHook(() =>
      useJobStateMachine({
        jobId: 'stale-job',
        onJobNotFound,
      }),
    );

    await waitFor(() => {
      expect(onJobNotFound).toHaveBeenCalledWith('stale-job');
    });
  });

  it('syncs projected results and leaves them ready for review', async () => {
    const removeJob = vi.fn();
    const invalidateQueries = vi.fn();
    const syncMutateAsync = vi.fn().mockResolvedValue({
      synced: true,
      reason: 'ok',
      last_snapshot_version: 123,
      last_synced_at: '2026-03-09T10:00:00Z',
      is_stale: false,
    });
    const { useCombinedScanStatus } = await import('../useRecognitionHooks');
    const { useSyncTrigger } = await import('../useSyncTrigger');

    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [{ id: 'job-2', type: 'clustering' }],
      addJob: vi.fn(),
      removeJob,
    });
    (useQueryClient as Mock).mockReturnValue({
      invalidateQueries,
    });
    (useCombinedScanStatus as Mock).mockReturnValue({
      scanStatusQuery: {
        data: {
          id: 'job-2',
          type: 'clustering',
          status: 'completed',
          progress: { completed: 10, total: 10, phase: 'awaiting_projection' },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
          snapshot_version: 123,
          source_job_id: 'job-2',
          projection_acknowledged_at: null,
        },
      },
    });
    (useSyncTrigger as Mock).mockReturnValue({ mutateAsync: syncMutateAsync });

    const { result } = renderHook(() => useJobStateMachine());

    await waitFor(() => {
      expect(syncMutateAsync).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      await syncMutateAsync.mock.results[0]?.value;
    });

    await waitFor(() => {
      expect(result.current.projectionSyncState).toBe('ready');
      expect(removeJob).not.toHaveBeenCalled();
      expect(invalidateQueries).toHaveBeenCalled();
    });
  });

  it('reports clustering phase when backend auto-chained clustering without a local cluster job', async () => {
    const { useCombinedScanStatus } = await import('../useRecognitionHooks');
    (useCombinedScanStatus as Mock).mockReturnValue({
      scanStatusQuery: {
        data: {
          id: 'analyze-1',
          type: 'clustering',
          status: 'running',
          progress: { completed: 50, total: 150, phase: 'clustering' },
          started_at: new Date().toISOString(),
          finished_at: null,
        },
      },
    });

    const { result } = renderHook(() => useJobStateMachine());

    expect(result.current.currentPhase).toBe('clustering');
    expect(result.current.isScanRunning).toBe(true);
  });

  it('connects SSE to the backend job id when in backend-driven clustering', async () => {
    const { useCombinedScanStatus } = await import('../useRecognitionHooks');
    (useCombinedScanStatus as Mock).mockReturnValue({
      scanStatusQuery: {
        data: {
          id: 'analyze-1',
          type: 'clustering',
          status: 'running',
          progress: { completed: 50, total: 150, phase: 'clustering' },
          started_at: new Date().toISOString(),
          finished_at: null,
        },
      },
    });

    const { result } = renderHook(() => useJobStateMachine());

    expect(result.current.latestJobId).toBe('analyze-1');
  });

  it('returns idle when backend clustering job completes and no active jobs remain', async () => {
    const { useCombinedScanStatus } = await import('../useRecognitionHooks');
    (useCombinedScanStatus as Mock).mockReturnValue({
      scanStatusQuery: {
        data: {
          id: 'analyze-1',
          type: 'clustering',
          status: 'completed',
          progress: { completed: 150, total: 150, phase: 'complete' },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
        },
      },
    });

    const { result } = renderHook(() => useJobStateMachine());

    expect(result.current.currentPhase).toBe('idle');
    expect(result.current.latestJobId).toBeNull();
  });
});
