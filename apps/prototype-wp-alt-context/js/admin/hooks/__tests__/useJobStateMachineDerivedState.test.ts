import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { BatchRunStatus, JobProgress } from '../../api/recognition/types/scan';
import type { PersistedJob } from '../useJobPersistence';
import {
  SCAN_STALL_STATE,
  deriveScanStallReport,
  useJobStateMachineDerivedState,
} from '../useJobStateMachineDerivedState';

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

const baseProps = {
  currentPhase: 'scanning' as const,
  activeJobIds: ['scan-1'],
  activeJobs: [
    {
      id: 'scan-1',
      type: 'scan',
      startedAt: 1,
      totalItems: 20,
    } as PersistedJob,
  ],
  latestScanJob: { id: 'scan-1', type: 'scan', startedAt: 1, totalItems: 20 } as PersistedJob,
  latestJobId: 'scan-1',
  scanPending: false,
  clusterPending: false,
  waitingForCompletion: false,
  scanStatus: undefined,
  sseStatus: 'running' as const,
  stalledForSeconds: null,
};

describe('useJobStateMachineDerivedState monotonic guard', () => {
  it('clamps scanProgress.completed when a later batch-run snapshot regresses within the same run', () => {
    const initialBatchRunStatus = makeBatchRunStatus({ completed_total: 12 });
    const { result, rerender } = renderHook(
      ({ batchRunStatus, sseProgress }: { batchRunStatus: BatchRunStatus; sseProgress: JobProgress | null }) =>
        useJobStateMachineDerivedState({
          ...baseProps,
          batchRunStatus,
          sseProgress,
        }),
      {
        initialProps: {
          batchRunStatus: initialBatchRunStatus,
          sseProgress: null,
        },
      },
    );

    expect(result.current.scanProgress?.completed).toBe(12);

    rerender({
      batchRunStatus: makeBatchRunStatus({ completed_total: 8 }),
      sseProgress: null,
    });

    expect(result.current.scanProgress?.completed).toBe(12);
  });

  it('resets the monotonic floor when the run id flips to a new batch run', () => {
    const { result, rerender } = renderHook(
      ({ batchRunStatus }: { batchRunStatus: BatchRunStatus }) =>
        useJobStateMachineDerivedState({
          ...baseProps,
          batchRunStatus,
          sseProgress: null,
        }),
      {
        initialProps: {
          batchRunStatus: makeBatchRunStatus({ id: 'run-1', completed_total: 12 }),
        },
      },
    );

    expect(result.current.scanProgress?.completed).toBe(12);

    rerender({
      batchRunStatus: makeBatchRunStatus({ id: 'run-2', completed_total: 3 }),
    });

    expect(result.current.scanProgress?.completed).toBe(3);
  });
});

describe('scan stall probe fidelity [WBUX6-W3-L2-02]', () => {
  const running = { currentPhase: 'scanning' as const, probeObserving: true };

  it('reports a real reading as stalled and carries the duration', () => {
    expect(deriveScanStallReport({ ...running, stalledForSeconds: 31 })).toEqual({
      state: SCAN_STALL_STATE.STALLED,
      seconds: 31,
    });
  });

  it('reports live only when the detector is running and explicitly says "no stall"', () => {
    expect(deriveScanStallReport({ ...running, stalledForSeconds: null })).toEqual({
      state: SCAN_STALL_STATE.LIVE,
      seconds: null,
    });
  });

  it('reports unobserved — never live — when the detector is not running (dead/disabled stream)', () => {
    // useJobProgressStream nulls stalledForSeconds when the tab is not primary,
    // the browser is offline, or there is no job id. Null must not read as healthy.
    expect(deriveScanStallReport({ currentPhase: 'scanning', stalledForSeconds: null, probeObserving: false })).toEqual(
      { state: SCAN_STALL_STATE.UNOBSERVED, seconds: null },
    );
  });

  it('reports unobserved when no reading exists at all (undefined is not "no stall")', () => {
    expect(deriveScanStallReport({ ...running, stalledForSeconds: undefined })).toEqual({
      state: SCAN_STALL_STATE.UNOBSERVED,
      seconds: null,
    });
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, -5])(
    'rejects the corrupt reading %p as unobserved rather than trusting it (sr-005)',
    (reading) => {
      expect(deriveScanStallReport({ ...running, stalledForSeconds: reading })).toEqual({
        state: SCAN_STALL_STATE.UNOBSERVED,
        seconds: null,
      });
    },
  );

  it('suppresses the probe entirely while idle, even with a live reading', () => {
    expect(deriveScanStallReport({ currentPhase: 'idle', stalledForSeconds: 90, probeObserving: true })).toEqual({
      state: SCAN_STALL_STATE.IDLE,
      seconds: null,
    });
  });

  it('exposes the state alongside the duration from the hook', () => {
    const { result, rerender } = renderHook(
      ({ stalledForSeconds, probeObserving }: { stalledForSeconds: number | null; probeObserving: boolean }) =>
        useJobStateMachineDerivedState({
          ...baseProps,
          batchRunStatus: makeBatchRunStatus(),
          sseProgress: null,
          stalledForSeconds,
          probeObserving,
        }),
      { initialProps: { stalledForSeconds: null as number | null, probeObserving: true } },
    );

    expect(result.current.scanStallState).toBe(SCAN_STALL_STATE.LIVE);
    expect(result.current.scanStallSeconds).toBeNull();

    rerender({ stalledForSeconds: 44, probeObserving: true });
    expect(result.current.scanStallState).toBe(SCAN_STALL_STATE.STALLED);
    expect(result.current.scanStallSeconds).toBe(44);

    rerender({ stalledForSeconds: null, probeObserving: false });
    expect(result.current.scanStallState).toBe(SCAN_STALL_STATE.UNOBSERVED);
    expect(result.current.scanStallSeconds).toBeNull();
  });

  it('defaults to unobserved when the caller supplies no liveness evidence', () => {
    const { result } = renderHook(() =>
      useJobStateMachineDerivedState({
        ...baseProps,
        batchRunStatus: makeBatchRunStatus(),
        sseProgress: null,
      }),
    );

    expect(result.current.scanStallState).toBe(SCAN_STALL_STATE.UNOBSERVED);
  });
});
