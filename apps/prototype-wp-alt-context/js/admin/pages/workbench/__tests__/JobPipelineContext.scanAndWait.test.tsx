/**
 * WBUX-6 L2b — scanAndWait waiter (RES-03 fail-fast, TEST-15).
 */
import React from 'react';
import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { BatchRunStatus } from '../../../api/recognition/types/scan';
import {
  JobPipelineProvider,
  SCAN_AND_WAIT_TIMEOUT_MS,
  useJobPipeline,
  type JobPipelineContextValue,
} from '../JobPipelineContext';

const failedBatchStatus = (overrides: Partial<BatchRunStatus> = {}): BatchRunStatus => ({
  id: 'run-fail',
  submitted_total: 1,
  accepted_total: 1,
  completed_total: 0,
  failed_total: 2,
  cancelled_total: 0,
  unreadable_media_ids: [],
  failed_batches: [],
  child_job_ids: ['j1'],
  terminal_state: true,
  ...overrides,
});

const { machine, captured } = vi.hoisted(() => {
  const machine = {
    isScanRunning: false,
    isCancellingScan: false,
    currentPhase: 'idle' as const,
    projectionSyncState: 'idle' as const,
    projectionError: null as string | null,
    statusText: '',
    scanProgress: null,
    clusterProgress: null,
    batchRunStatus: null as BatchRunStatus | null,
    scanStallSeconds: null as number | null,
    etaSeconds: null as number | null,
    isOnline: true,
    isPrimary: true,
    latestJobId: null as string | null,
    activeJobIds: [] as string[],
    scan: vi.fn(),
    cancelScan: vi.fn(),
    cluster: vi.fn(),
    retryClustering: vi.fn(),
    canRetryClustering: false,
    retryProjectionSync: vi.fn(),
    retryScanStream: vi.fn(),
  };
  const captured: { onScanError?: (message: string) => void } = {};
  return { machine, captured };
});

vi.mock('../../../hooks/useJobStateMachine', () => ({
  useJobStateMachine: (options: { onScanError?: (message: string) => void }) => {
    captured.onScanError = options.onScanError;
    return { ...machine };
  },
}));

vi.mock('../../../hooks/useRecognitionJobHistory', () => ({
  useRecognitionJobHistory: () => ({
    jobId: null,
    latestJobId: null,
    activeJobIds: [],
    jobHistory: [],
    jobStatuses: {},
    historySource: 'unavailable',
    rememberJob: vi.fn(),
    selectJob: vi.fn(),
    forgetJob: vi.fn(),
    clearHistory: vi.fn(),
  }),
}));

vi.mock('../WorkbenchNavContext', () => ({
  useWorkbenchNav: () => ({ setAdvancedOpen: vi.fn() }),
}));

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

const ctxRef: { current: JobPipelineContextValue | null } = { current: null };

const Probe = (): null => {
  ctxRef.current = useJobPipeline();
  return null;
};

const PipelineTree = ({
  running,
  batchRunStatus = null,
}: {
  running: boolean;
  batchRunStatus?: BatchRunStatus | null;
}): React.JSX.Element => {
  machine.isScanRunning = running;
  machine.batchRunStatus = batchRunStatus;
  return (
    <JobPipelineProvider>
      <Probe />
    </JobPipelineProvider>
  );
};

const trackSettlement = (promise: Promise<void>): { settled: boolean } => {
  const state = { settled: false };
  void promise.then(
    () => {
      state.settled = true;
    },
    () => {
      state.settled = true;
    },
  );
  return state;
};

describe('JobPipelineContext.scanAndWait', () => {
  beforeEach(() => {
    ctxRef.current = null;
    machine.isScanRunning = false;
    machine.batchRunStatus = null;
    machine.scan.mockReset();
    machine.cancelScan.mockReset();
    captured.onScanError = undefined;
  });

  it('resolves after isScanRunning goes true then false', async () => {
    const { rerender } = render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = ctxRef.current!.scanAndWait([1]);
    });
    expect(machine.scan).toHaveBeenCalledWith([1]);

    act(() => {
      rerender(<PipelineTree running={true} />);
    });
    act(() => {
      rerender(<PipelineTree running={false} />);
    });

    await expect(promise).resolves.toBeUndefined();
  });

  it('rejects with onScanError message', async () => {
    render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = ctxRef.current!.scanAndWait([1]);
    });
    const rejected = expect(promise).rejects.toThrow('boom');

    act(() => {
      captured.onScanError!('boom');
    });

    await rejected;
  });

  it('rejects with cancelled when cancelScan runs while a waiter is pending', async () => {
    render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = ctxRef.current!.scanAndWait([1]);
    });
    const rejected = expect(promise).rejects.toThrow(/cancelled/);

    act(() => {
      ctxRef.current!.cancelScan(['j1']);
    });

    await rejected;
    expect(machine.cancelScan).toHaveBeenCalledWith(['j1']);
  });

  it('does not settle while isScanRunning never goes true (started-gate mutant)', async () => {
    const { rerender } = render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = ctxRef.current!.scanAndWait([1]);
    });
    const settlement = trackSettlement(promise);

    // Force the waiter effect to re-run without ever flipping isScanRunning.
    // Deleting `if (!waiter.started) return` must resolve here.
    act(() => {
      rerender(
        <PipelineTree
          running={false}
          batchRunStatus={failedBatchStatus({
            terminal_state: false,
            completed_total: 0,
            failed_total: 0,
          })}
        />,
      );
    });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(settlement.settled).toBe(false);
    expect(machine.scan).toHaveBeenCalledWith([1]);
  });

  it('rejects when a started batch ends with zero completed and failures', async () => {
    const { rerender } = render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = ctxRef.current!.scanAndWait([1]);
    });
    act(() => {
      rerender(<PipelineTree running={true} />);
    });
    const rejected = expect(promise).rejects.toThrow('People identification failed. Nothing was described.');
    act(() => {
      rerender(<PipelineTree running={false} batchRunStatus={failedBatchStatus()} />);
    });

    await rejected;
  });

  it('rejects the first waiter when a second scanAndWait supersedes it', async () => {
    render(<PipelineTree running={false} />);

    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = ctxRef.current!.scanAndWait([1]);
    });
    const rejected = expect(first).rejects.toThrow('People identification was superseded by a newer run.');
    act(() => {
      second = ctxRef.current!.scanAndWait([2]);
    });
    void second.catch(() => undefined);

    await rejected;
  });

  it('rejects with the failed message when isScanRunning never toggles (timeout)', async () => {
    vi.useFakeTimers();
    try {
      render(<PipelineTree running={false} />);

      let promise!: Promise<void>;
      act(() => {
        promise = ctxRef.current!.scanAndWait([1]);
      });
      const rejected = expect(promise).rejects.toThrow('People identification failed. Nothing was described.');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(SCAN_AND_WAIT_TIMEOUT_MS);
      });

      await rejected;
    } finally {
      vi.useRealTimers();
    }
  });

  it('rejects when the provider unmounts with a pending waiter', async () => {
    const { unmount } = render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = ctxRef.current!.scanAndWait([1]);
    });
    const rejected = expect(promise).rejects.toThrow('People identification was cancelled.');
    act(() => {
      unmount();
    });

    await rejected;
  });
});
