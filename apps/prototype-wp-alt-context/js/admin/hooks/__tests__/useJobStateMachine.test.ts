import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest';
import { useJobStateMachine } from '../useJobStateMachine';
import { useJobPersistence } from '../useJobPersistence';
import { useQueryClient } from '@tanstack/react-query';

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
  useAcknowledgeProjection: vi.fn(() => ({ mutateAsync: vi.fn() })),
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
    (useJobPersistence as Mock).mockReturnValue({
      activeJobs: [{ id: 'job-2', type: 'clustering' }],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });
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

    const { result } = renderHook(() => useJobStateMachine());
    expect(result.current.currentPhase).toBe('projecting');
    expect(result.current.latestJobId).toBe('job-2');
  });

  it('falls back to idle when awaiting_projection is cached but no active jobs remain', async () => {
    const { useCombinedScanStatus } = await import('../useRecognitionHooks');
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

    const { result } = renderHook(() => useJobStateMachine());
    expect(result.current.currentPhase).toBe('idle');
    expect(result.current.latestJobId).toBeNull();
  });

  it('syncs and acknowledges projected results before clearing the clustering job', async () => {
    const removeJob = vi.fn();
    const invalidateQueries = vi.fn();
    const syncMutateAsync = vi.fn().mockResolvedValue({
      synced: true,
      reason: 'ok',
      last_snapshot_version: 123,
      last_synced_at: '2026-03-09T10:00:00Z',
      is_stale: false,
    });
    const acknowledgeMutateAsync = vi.fn().mockResolvedValue({ status: 'acknowledged', snapshot_version: 123 });
    const { useCombinedScanStatus, useAcknowledgeProjection } = await import('../useRecognitionHooks');
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
    (useAcknowledgeProjection as Mock).mockReturnValue({ mutateAsync: acknowledgeMutateAsync });

    renderHook(() => useJobStateMachine());

    await waitFor(() => {
      expect(syncMutateAsync).toHaveBeenCalledTimes(1);
      expect(acknowledgeMutateAsync).toHaveBeenCalledWith({ jobId: 'job-2', snapshotVersion: 123 });
      expect(removeJob).toHaveBeenCalledWith('job-2');
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
