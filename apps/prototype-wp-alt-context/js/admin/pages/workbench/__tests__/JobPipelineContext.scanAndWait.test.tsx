/**
 * WBUX-6 L2 — scanAndWait waiter: bounded start, bounded silence, fail-fast terminal
 * outcomes (RES-03 / RES-13 / CARD-09 bounded waiting, TEST-15 mutant coverage).
 */
import React from 'react';
import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { BatchRunStatus, JobProgress } from '../../../api/recognition/types/scan';
import {
  JobPipelineProvider,
  SCAN_PROGRESS_TIMEOUT_MS,
  SCAN_START_TIMEOUT_MS,
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

const progressAt = (completed: number): JobProgress => ({ completed, total: 10, phase: 'detecting' });

const { machine, captured } = vi.hoisted(() => {
  const machine = {
    isScanRunning: false,
    isCancellingScan: false,
    currentPhase: 'idle' as const,
    projectionSyncState: 'idle' as const,
    projectionError: null as string | null,
    statusText: '',
    scanProgress: null as JobProgress | null,
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

/** Internal test invariant (sr-005): the probe always renders inside the provider. */
function pipeline(): JobPipelineContextValue {
  const value = ctxRef.current;
  if (!value) {
    throw new Error('JobPipeline context was not captured by the probe');
  }
  return value;
}

const Probe = (): null => {
  ctxRef.current = useJobPipeline();
  return null;
};

const PipelineTree = ({
  running,
  batchRunStatus = null,
  scanProgress = null,
  activeJobIds = [],
}: {
  running: boolean;
  batchRunStatus?: BatchRunStatus | null;
  scanProgress?: JobProgress | null;
  activeJobIds?: string[];
}): React.JSX.Element => {
  machine.isScanRunning = running;
  machine.batchRunStatus = batchRunStatus;
  machine.scanProgress = scanProgress;
  machine.activeJobIds = activeJobIds;
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
    machine.scanProgress = null;
    machine.activeJobIds = [];
    machine.scan.mockReset();
    machine.cancelScan.mockReset();
    captured.onScanError = undefined;
  });

  it('resolves after isScanRunning goes true then false', async () => {
    const { rerender } = render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = pipeline().scanAndWait([1]);
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
      promise = pipeline().scanAndWait([1]);
    });
    const rejected = expect(promise).rejects.toThrow('boom');

    act(() => {
      captured.onScanError?.('boom');
    });

    await rejected;
  });

  it('rejects with cancelled when cancelScan runs while a waiter is pending', async () => {
    render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = pipeline().scanAndWait([1]);
    });
    const rejected = expect(promise).rejects.toThrow(/cancelled/);

    act(() => {
      pipeline().cancelScan(['j1']);
    });

    await rejected;
    expect(machine.cancelScan).toHaveBeenCalledWith(['j1']);
  });

  it('does not settle while isScanRunning never goes true (started-gate mutant)', async () => {
    const { rerender } = render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = pipeline().scanAndWait([1]);
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
    void promise.catch(() => undefined);
  });

  it('rejects when a started batch ends with zero completed and failures', async () => {
    const { rerender } = render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = pipeline().scanAndWait([1]);
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
      first = pipeline().scanAndWait([1]);
    });
    const rejected = expect(first).rejects.toThrow('People identification was superseded by a newer run.');
    act(() => {
      second = pipeline().scanAndWait([2]);
    });
    void second.catch(() => undefined);

    await rejected;
  });

  it('rejects with the failed message when the scan never starts (start deadline)', async () => {
    vi.useFakeTimers();
    try {
      render(<PipelineTree running={false} />);

      let promise!: Promise<void>;
      act(() => {
        promise = pipeline().scanAndWait([1]);
      });
      const rejected = expect(promise).rejects.toThrow('People identification failed. Nothing was described.');

      await act(async () => {
        await vi.advanceTimersByTimeAsync(SCAN_START_TIMEOUT_MS);
      });

      await rejected;
      // Nothing started, so there is no job to cancel.
      expect(machine.cancelScan).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps waiting on a healthy in-flight run far past the start deadline', async () => {
    vi.useFakeTimers();
    try {
      const { rerender } = render(<PipelineTree running={false} />);

      let promise!: Promise<void>;
      act(() => {
        promise = pipeline().scanAndWait([1]);
      });
      const settlement = trackSettlement(promise);

      act(() => {
        rerender(<PipelineTree running={true} scanProgress={progressAt(0)} activeJobIds={['j1']} />);
      });

      // Ten minutes of a slow-but-alive run (cold GPU warm-up is ~2 min), reporting
      // progress every 60s. An absolute deadline on the whole operation kills this.
      for (let tick = 1; tick <= 10; tick += 1) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(60_000);
        });
        act(() => {
          rerender(<PipelineTree running={true} scanProgress={progressAt(tick)} activeJobIds={['j1']} />);
        });
      }

      expect(settlement.settled).toBe(false);
      expect(machine.cancelScan).not.toHaveBeenCalled();

      act(() => {
        rerender(<PipelineTree running={false} scanProgress={progressAt(10)} activeJobIds={['j1']} />);
      });
      await expect(promise).resolves.toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it('aborts a started run that goes silent and cancels the live scan', async () => {
    vi.useFakeTimers();
    try {
      const { rerender } = render(<PipelineTree running={false} />);

      let promise!: Promise<void>;
      act(() => {
        promise = pipeline().scanAndWait([1]);
      });
      const rejected = expect(promise).rejects.toThrow('People identification failed. Nothing was described.');

      act(() => {
        rerender(<PipelineTree running={true} scanProgress={progressAt(1)} activeJobIds={['j1', 'j2']} />);
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(SCAN_PROGRESS_TIMEOUT_MS);
      });

      await rejected;
      // A bound that gives up must free the resource it was waiting on (RES-04/RES-20).
      expect(machine.cancelScan).toHaveBeenCalledWith(['j1', 'j2']);
    } finally {
      vi.useRealTimers();
    }
  });

  it('rejects when the provider unmounts with a pending waiter', async () => {
    const { unmount } = render(<PipelineTree running={false} />);

    let promise!: Promise<void>;
    act(() => {
      promise = pipeline().scanAndWait([1]);
    });
    const rejected = expect(promise).rejects.toThrow('People identification was cancelled.');
    act(() => {
      unmount();
    });

    await rejected;
  });

  describe('bound values', () => {
    // These guard the constants themselves: without them a `= 1` mutant on either
    // bound leaves every behavioural test above green (the suite keys off the constant).
    it('gives the scan a start window longer than a single stream reconnect', () => {
      expect(SCAN_START_TIMEOUT_MS).toBeGreaterThanOrEqual(10_000);
      expect(SCAN_START_TIMEOUT_MS).toBeLessThanOrEqual(60_000);
    });

    it('gives a running scan a silence window well past a cold GPU warm-up', () => {
      // GPU warm-up is ~2 min; the 30s stream stall window is a banner, not a kill switch.
      expect(SCAN_PROGRESS_TIMEOUT_MS).toBeGreaterThanOrEqual(240_000);
      expect(SCAN_PROGRESS_TIMEOUT_MS).toBeGreaterThan(SCAN_START_TIMEOUT_MS);
    });
  });
});
