import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { BatchRunStatus, JobProgress } from '../../api/recognition/types/scan';
import type { PersistedJob } from '../useJobPersistence';
import { useJobStateMachineDerivedState } from '../useJobStateMachineDerivedState';

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
