/**
 * WBUX-6 L2b — scanAndWait waiter (RES-03 fail-fast, TEST-15).
 */
import React from 'react';
import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { JobPipelineProvider, useJobPipeline, type JobPipelineContextValue } from '../JobPipelineContext';

const { machine, captured } = vi.hoisted(() => {
  const machine = {
    isScanRunning: false,
    isCancellingScan: false,
    currentPhase: 'idle',
    projectionSyncState: 'idle',
    projectionError: null,
    statusText: '',
    scanProgress: null,
    clusterProgress: null,
    batchRunStatus: null as null | { terminal_state: string; completed_total: number; failed_total: number },
    scanStallSeconds: null,
    etaSeconds: null,
    isOnline: true,
    isPrimary: true,
    latestJobId: null,
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

const PipelineTree = ({ running }: { running: boolean }): React.JSX.Element => {
  machine.isScanRunning = running;
  return (
    <JobPipelineProvider>
      <Probe />
    </JobPipelineProvider>
  );
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
});
