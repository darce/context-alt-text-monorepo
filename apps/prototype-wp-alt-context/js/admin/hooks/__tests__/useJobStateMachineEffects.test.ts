import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { BatchRunStatus } from '../../api/recognition';
import { resetConfigCache } from '../../api/config';
import { queryKeys } from '../../api/queryKeys';
import { SYNC_VOCABULARY } from '../../pages/workbench/syncVocabulary';
import type { PipelinePhase } from '../jobStateMachineUtils';
import { useJobStateMachineEffects, type ProjectionSyncState } from '../useJobStateMachineEffects';

describe('useJobStateMachineEffects', () => {
  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {},
      tenant_id: 'test-tenant-id',
    };
    resetConfigCache();
  });
  const buildTerminalBatchRunStatus = (): BatchRunStatus => ({
    id: 'batch-run-1',
    submitted_total: 14,
    accepted_total: 14,
    completed_total: 14,
    failed_total: 0,
    cancelled_total: 0,
    unreadable_media_ids: [],
    failed_batches: [],
    child_job_ids: [],
    terminal_state: true,
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
    batchRunStatus: undefined,
    queryClient: { invalidateQueries: vi.fn(), refetchQueries: vi.fn().mockResolvedValue(undefined) } as never,
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
    setProjectionError: vi.fn<(message: string | null) => void>(),
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
        queryClient: { invalidateQueries, refetchQueries: vi.fn().mockResolvedValue(undefined) } as never,
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

  it('fires the identity/cluster/suggestion refresh when a scan completes with errors (BND-1)', async () => {
    // completed_with_errors is a terminal partial-success the description-service emits; the
    // consumer must refresh findings exactly as it does for a clean 'completed' scan. Before the
    // fix the effect only matched status === 'completed', so a partial-success scan silently
    // skipped the refresh.
    const base = buildBaseOptions();
    const invalidateQueries = vi.fn();

    renderHook(() =>
      useJobStateMachineEffects({
        ...base,
        scanStatus: { ...base.scanStatus, status: 'completed_with_errors' },
        queryClient: { invalidateQueries, refetchQueries: vi.fn().mockResolvedValue(undefined) } as never,
        batchRunStatus: undefined,
        isWaitingForScanCompletion: false,
        currentPhase: 'scanning',
        latestClusterJob: null,
        sseStatus: 'pending',
      }),
    );

    await waitFor(() => {
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
    });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.all });
  });

  it('cleans up the cluster job + refreshes when clustering completes with errors over SSE (BND-1-AUDIT-2)', async () => {
    // SSE channel: completed_with_errors is terminal. Before the fix `clusteringCompleted` only
    // matched 'completed'|'failed', so a partial-success clustering run never removed the job and
    // never invalidated identities/clusters — the UI stayed stuck in the clustering phase.
    const base = buildBaseOptions();
    const removeJob = vi.fn();
    const invalidateQueries = vi.fn();

    renderHook(() =>
      useJobStateMachineEffects({
        ...base,
        scanStatus: { ...base.scanStatus, status: 'running' },
        sseStatus: 'completed_with_errors',
        currentPhase: 'clustering',
        latestClusterJob: { id: 'cluster-1', type: 'clustering', startedAt: Date.now(), totalItems: 5 },
        removeJob,
        queryClient: { invalidateQueries, refetchQueries: vi.fn().mockResolvedValue(undefined) } as never,
      }),
    );

    await waitFor(() => expect(removeJob).toHaveBeenCalledWith('cluster-1'));
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
  });

  it('keeps projection failures retryable after the backend leaves projecting', async () => {
    const options = buildBaseOptions();
    const syncMutateAsync = vi
      .fn()
      .mockRejectedValueOnce(new Error(SYNC_VOCABULARY.resultsErrorHeadline))
      .mockResolvedValueOnce({
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
      expect(options.setProjectionError).toHaveBeenCalledWith(SYNC_VOCABULARY.resultsErrorHeadline);
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

  it('force-refetches every visible findings query when projection sync reaches ready', async () => {
    const options = buildBaseOptions();
    const refetchQueries = vi.fn().mockResolvedValue(undefined);
    options.queryClient = { invalidateQueries: vi.fn(), refetchQueries } as never;
    options.syncTrigger = {
      mutateAsync: vi.fn().mockResolvedValue({
        synced: true,
        reason: 'ok',
        last_snapshot_version: 123,
        last_synced_at: '2026-06-05T10:00:00Z',
        is_stale: false,
      }),
    } as never;

    renderHook(() => useJobStateMachineEffects(options));

    await waitFor(() => {
      expect(options.setProjectionSyncState).toHaveBeenCalledWith('ready');
    });

    await waitFor(() => {
      // scanRecomputeCompletion: assignment family via projection.all; keep merge/name/media/topUnlabeled.
      expect(refetchQueries).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.projection.all });
      expect(refetchQueries).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.mergePending() });
      expect(refetchQueries).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.namePending() });
      expect(refetchQueries).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.topUnlabeled('test-tenant-id') });
      expect(refetchQueries).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
    });
  });

  it('does not force findings refetch when projection sync fails', async () => {
    const options = buildBaseOptions();
    const refetchQueries = vi.fn().mockResolvedValue(undefined);
    options.queryClient = { invalidateQueries: vi.fn(), refetchQueries } as never;
    options.syncTrigger = {
      mutateAsync: vi.fn().mockResolvedValue({
        synced: false,
        reason: 'sync_failed',
        last_snapshot_version: null,
        last_synced_at: null,
        is_stale: true,
      }),
    } as never;

    renderHook(() => useJobStateMachineEffects(options));

    await waitFor(() => {
      expect(options.setProjectionSyncState).toHaveBeenCalledWith('error');
    });

    expect(refetchQueries).not.toHaveBeenCalled();
  });

  it('routes non-sync_failed projection failures through SYNC_VOCABULARY (UXP4-BRV-01)', async () => {
    const options = buildBaseOptions();
    options.syncTrigger = {
      mutateAsync: vi.fn().mockResolvedValue({
        synced: false,
        reason: 'not_ready',
        last_snapshot_version: null,
        last_synced_at: null,
        is_stale: true,
      }),
    } as never;

    renderHook(() => useJobStateMachineEffects(options));

    await waitFor(() => {
      expect(options.setProjectionSyncState).toHaveBeenCalledWith('error');
      expect(options.setProjectionError).toHaveBeenCalledWith(SYNC_VOCABULARY.resultsSyncFailed);
    });

    const errorArgs = options.setProjectionError.mock.calls.map((call) => call[0]);
    expect(errorArgs).not.toContain('Syncing results failed.');
    expect(errorArgs.every((msg) => msg !== 'Syncing results failed.')).toBe(true);
  });

  it('routes non-Error projection catch fallback through SYNC_VOCABULARY (UXP4-BRV-01)', async () => {
    const options = buildBaseOptions();
    options.syncTrigger = {
      mutateAsync: vi.fn().mockRejectedValue('network-down'),
    } as never;

    renderHook(() => useJobStateMachineEffects(options));

    await waitFor(() => {
      expect(options.setProjectionSyncState).toHaveBeenCalledWith('error');
      expect(options.setProjectionError).toHaveBeenCalledWith(SYNC_VOCABULARY.resultsSyncFailed);
    });

    const errorArgs = options.setProjectionError.mock.calls.map((call) => call[0]);
    expect(errorArgs).not.toContain('Syncing results failed.');
  });
});
