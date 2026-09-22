import { createElement, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../api/config';
import {
  DESCRIBE_RUN_PHASE,
  DESCRIBE_RUN_STATUS,
  DESCRIBE_RUN_TERMINAL_CODE,
  GPU_STATE,
  type DescribeRunItem,
  type DescribeRunItemsResponse,
  type DescribeRunResponse,
} from '../../api/describeApi';
import type { GpuState } from '../../api/describeApi';
import { GPU_INTENT_ACTION, GPU_INTENT_STATUS, type GpuStatusResponse } from '../../api/gpuApi';
import * as gpuApi from '../../api/gpuApi';
import * as describeApi from '../../api/describeApi';
import {
  _resetDescribeOperationStoreForTests,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  DESCRIBE_RUN_RESUME_STATUS,
  DESCRIBE_RUN_SETTLE_OUTCOME,
  getDescribeRunContext,
  getLastSettledRun,
  pendingTerminalRuns,
  putDescribeOperationContext,
} from '../describeOperationStore';
import type { DescribeRunProgress } from '../useDescribeRunProgress';
import { DEFAULT_STARTUP_BUDGET_SECONDS, STALL_PHASE, stallThresholdMs as jobStallThresholdMs } from '../jobMachine';
import {
  ACTIVITY_KIND,
  ACTIVITY_REASON,
  resolveActivityStatus,
  stallThresholdMs,
  useActivityStatus,
  type DescribeActivityInput,
  type GpuActivityInput,
  type ScanActivityInput,
} from '../useActivityStatus';

vi.mock('../../api/gpuApi', async (importOriginal) => {
  const actual = await importOriginal<typeof gpuApi>();
  return { ...actual, fetchGpuStatus: vi.fn() };
});

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return {
    ...actual,
    fetchBulkDescribeRun: vi.fn(),
    cancelBulkDescribeRun: vi.fn(),
    fetchDescribeRunItems: vi.fn(),
    submitBulkDescribeRun: vi.fn(),
  };
});

const fetchGpuStatusMock = vi.mocked(gpuApi.fetchGpuStatus);
const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);
const fetchDescribeRunItemsMock = vi.mocked(describeApi.fetchDescribeRunItems);
const submitBulkDescribeRunMock = vi.mocked(describeApi.submitBulkDescribeRun);

const TENANT = 'tenant-a';

const idleScan = (overrides: Partial<ScanActivityInput> = {}): ScanActivityInput => ({
  isScanning: false,
  isCancelling: false,
  progressFraction: null,
  etaSeconds: null,
  errorMessage: null,
  jobId: null,
  ...overrides,
});

const describeRun = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: TENANT,
  run_id: 'run-1',
  status: DESCRIBE_RUN_STATUS.RUNNING,
  phase: DESCRIBE_RUN_PHASE.DESCRIBING,
  completed: 1,
  failed: 0,
  skipped: 0,
  total: 4,
  cancel_requested: false,
  eta_seconds: 40,
  gpu_state: GPU_STATE.READY,
  recognition_enabled: true,
  ...overrides,
});

const describeProgress = (
  overrides: Partial<DescribeRunProgress> = {},
  runOverrides: Partial<DescribeRunResponse> = {},
): DescribeRunProgress => {
  const run = overrides.run === null ? null : describeRun({ ...runOverrides, ...overrides.run });
  return {
    run,
    status: run?.status ?? null,
    progressFraction: run !== null && run.total > 0 ? (run.completed + run.failed + run.skipped) / run.total : null,
    etaSeconds: run?.eta_seconds ?? null,
    gpuState: (run?.gpu_state as GpuState | null | undefined) ?? GPU_STATE.UNKNOWN,
    isWarming: run?.phase === DESCRIBE_RUN_PHASE.WARMING,
    isTerminal: run !== null && (run.status === DESCRIBE_RUN_STATUS.COMPLETED ||
      run.status === DESCRIBE_RUN_STATUS.COMPLETED_WITH_ERRORS ||
      run.status === DESCRIBE_RUN_STATUS.FAILED ||
      run.status === DESCRIBE_RUN_STATUS.CANCELLED),
    stalledForSeconds: null,
    isPolling: run !== null,
    isFrozen: false,
    isError: false,
    error: null,
    retry: vi.fn(),
    ...overrides,
  };
};

const idleDescribe = (): DescribeActivityInput => ({
  runId: null,
  progress: describeProgress({ run: null, status: null, progressFraction: null, etaSeconds: null, isPolling: false }),
});

const gpuInput = (overrides: Partial<GpuActivityInput> = {}): GpuActivityInput => ({
  gpuState: GPU_STATE.STOPPED,
  reason: null,
  isError: false,
  isRunPending: false,
  ...overrides,
});

const statusResponse = (state: GpuState = GPU_STATE.STOPPED): GpuStatusResponse => ({
  gpu_state: {
    state,
    instance_id: null,
    written_at: 1_700_000_000,
    reason: null,
    since: null,
    intent: GPU_INTENT_ACTION.AUTO,
    intent_expires_at: null,
    intent_status: GPU_INTENT_STATUS.NONE,
    honoured_nonce: null,
    lease_expires_at: null,
    instance_running_since: null,
    last_transition_reason: 'unknown',
  },
  snapshot_age_seconds: 12,
  snapshot_fresh: true,
  intent: null,
  load: { has_work: false, written_at: 1_700_000_004, fresh: true },
  server_time: '2026-09-07T12:00:00Z',
});

let queryClient: QueryClient;

const createWrapper = () => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return wrapper;
};

const installTenant = (): void => {
  resetConfigCache();
  registerConfig({
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {},
    tenant_id: TENANT,
  });
};

const describeItem = (mediaId: number, status: string): DescribeRunItem => ({
  media_id: mediaId,
  status,
  alt_text_draft: null,
  caption: null,
  provenance: null,
  tier: null,
  result_generation: 0,
  existing_alt: false,
});

const itemsResponse = (
  runId: string,
  items: DescribeRunItem[],
): DescribeRunItemsResponse => ({
  run_id: runId,
  items,
});

const warmupTimeoutRun = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse =>
  Object.assign(
    describeRun({
      status: DESCRIBE_RUN_STATUS.FAILED,
      phase: DESCRIBE_RUN_PHASE.FAILED,
      completed: 1,
      failed: 1,
      skipped: 0,
      total: 3,
      eta_seconds: null,
      gpu_state: GPU_STATE.STOPPED,
      ...overrides,
    }),
    {
      terminal: {
        code: DESCRIBE_RUN_TERMINAL_CODE.GPU_WARMUP_TIMEOUT,
        retryable: true,
        startup_budget_seconds: 510,
      },
    },
  );

const seedWarmupTimeoutRun = (runId = 'run-1'): void => {
  putDescribeOperationContext({
    version: DESCRIBE_OPERATION_CONTEXT_VERSION,
    kind: DESCRIBE_OPERATION_KIND.RUN,
    id: runId,
    startup_id: null,
    started_at: Date.now(),
    request: { writeAlt: false, force: false },
  });
  fetchBulkDescribeRunMock.mockImplementation(async (id: string) => {
    if (id === runId) {
      return warmupTimeoutRun({ run_id: runId });
    }
    return describeRun({
      run_id: id,
      status: DESCRIBE_RUN_STATUS.PENDING,
      phase: DESCRIBE_RUN_PHASE.WARMING,
      completed: 0,
      eta_seconds: 90,
      gpu_state: GPU_STATE.WARMING,
    });
  });
};

describe('resolveActivityStatus', () => {
  it('re-exports G3 stallThresholdMs for warming vs processing', () => {
    expect(stallThresholdMs).toBe(jobStallThresholdMs);
    expect(stallThresholdMs(STALL_PHASE.WARMING)).toBe(DEFAULT_STARTUP_BUDGET_SECONDS * 1000);
    expect(stallThresholdMs(STALL_PHASE.PROCESSING)).toBe(30_000);
  });

  it('returns idle when scan, describe, and GPU are quiet', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: idleDescribe(),
      gpu: gpuInput(),
    });
    expect(status).toMatchObject({
      kind: ACTIVITY_KIND.IDLE,
      progress: null,
      etaSeconds: null,
      reason: null,
      canCancel: false,
    });
  });

  it('prefers scanning over describe and GPU warm-up', () => {
    const status = resolveActivityStatus({
      scan: idleScan({
        isScanning: true,
        progressFraction: 0.5,
        etaSeconds: 12,
        jobId: 'job-1',
      }),
      describe: {
        runId: 'run-1',
        progress: describeProgress({ isWarming: true }, { phase: DESCRIBE_RUN_PHASE.WARMING }),
      },
      gpu: gpuInput({ gpuState: GPU_STATE.WARMING, isRunPending: true }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.SCANNING);
    expect(status.progress).toBe(0.5);
    expect(status.etaSeconds).toBe(12);
    expect(status.canCancel).toBe(true);
  });

  it('maps a live warming describe run to warming with cancel', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-1',
        progress: describeProgress(
          { isWarming: true, progressFraction: 0, etaSeconds: 180 },
          { phase: DESCRIBE_RUN_PHASE.WARMING, gpu_state: GPU_STATE.STARTING, eta_seconds: 180, completed: 0 },
        ),
      },
      gpu: gpuInput({ gpuState: GPU_STATE.STARTING, isRunPending: true }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.WARMING);
    expect(status.etaSeconds).toBe(180);
    expect(status.canCancel).toBe(true);
    expect(status.gpuState).toBe(GPU_STATE.STARTING);
    expect(status.warmingObservation?.status).toBe('unknown');
  });

  it('keeps fresh stopped evidence provisional and preserves unknown stale evidence', () => {
    const freshStoppedStatus = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-fresh-stopped',
        progress: describeProgress(
          { isWarming: true },
          {
            run_id: 'run-fresh-stopped',
            startup_id: 'startup-fresh-stopped',
            phase: DESCRIBE_RUN_PHASE.WARMING,
            gpu_state: GPU_STATE.STARTING,
          },
        ),
      },
      gpu: gpuInput({
        gpuState: GPU_STATE.STOPPED,
        isRunPending: true,
        snapshotFresh: true,
        data: statusResponse(GPU_STATE.STOPPED),
      }),
    });
    expect(freshStoppedStatus.kind).toBe(ACTIVITY_KIND.WARMING);
    expect(freshStoppedStatus.warmingObservation?.status).toBe('waiting');
    expect(freshStoppedStatus.warmingObservation?.evidence).toBe('stopped');

    const staleStatus = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-stale-status',
        progress: describeProgress(
          { isWarming: true },
          {
            run_id: 'run-stale-status',
            startup_id: 'startup-stale-status',
            phase: DESCRIBE_RUN_PHASE.WARMING,
            gpu_state: GPU_STATE.WARMING,
          },
        ),
      },
      gpu: gpuInput({
        gpuState: GPU_STATE.WARMING,
        isRunPending: true,
        snapshotFresh: false,
        data: { ...statusResponse(GPU_STATE.WARMING), snapshot_fresh: false },
      }),
    });
    expect(staleStatus.kind).toBe(ACTIVITY_KIND.WARMING);
    expect(staleStatus.warmingObservation?.status).toBe('unknown');
  });

  it('maps describing progress to describing', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-1',
        progress: describeProgress(),
      },
      gpu: gpuInput({ gpuState: GPU_STATE.READY, isRunPending: true }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.DESCRIBING);
    expect(status.progress).toBe(0.25);
    expect(status.etaSeconds).toBe(40);
    expect(status.canCancel).toBe(true);
    expect(status.draftCount).toBe(1);
  });

  it('maps completed describe to done with draft count', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-1',
        progress: describeProgress(
          { isTerminal: true, isPolling: false },
          {
            status: DESCRIBE_RUN_STATUS.COMPLETED,
            phase: DESCRIBE_RUN_PHASE.COMPLETE,
            completed: 3,
            failed: 0,
            eta_seconds: null,
          },
        ),
      },
      gpu: gpuInput({ gpuState: GPU_STATE.READY }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.DONE);
    expect(status.canCancel).toBe(false);
    expect(status.draftCount).toBe(3);
    expect(status.retryable).toBe(false);
  });

  it('maps C2 gpu_warmup_timeout as failed and retryable', () => {
    const failedRun = Object.assign(
      describeRun({
        status: DESCRIBE_RUN_STATUS.FAILED,
        phase: DESCRIBE_RUN_PHASE.FAILED,
        completed: 0,
        eta_seconds: null,
        gpu_state: GPU_STATE.STOPPED,
      }),
      { terminal: { code: 'gpu_warmup_timeout', retryable: true, startup_budget_seconds: 510 } },
    );
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-1',
        progress: describeProgress({ isTerminal: true, isPolling: false, run: failedRun }),
      },
      gpu: gpuInput({ gpuState: GPU_STATE.STOPPED }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(status.reason).toBe(ACTIVITY_REASON.GPU_WARMUP_TIMEOUT);
    expect(status.retryable).toBe(true);
    expect(status.canCancel).toBe(false);
  });

  it('treats a describe poll error as failed and retryable', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-1',
        progress: describeProgress({
          isError: true,
          isPolling: false,
          error: new Error('timeout'),
        }),
      },
      gpu: gpuInput({ isRunPending: true }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(status.reason).toBe(ACTIVITY_REASON.DESCRIBE_POLL_ERROR);
    expect(status.retryable).toBe(true);
  });

  it('maps idle GPU starting/warming to warming without cancel', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: idleDescribe(),
      gpu: gpuInput({ gpuState: GPU_STATE.WARMING }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.WARMING);
    expect(status.canCancel).toBe(false);
  });

  it('maps idle GPU status errors to failed with retry', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: idleDescribe(),
      gpu: gpuInput({ isError: true, gpuState: GPU_STATE.UNKNOWN }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(status.reason).toBe(ACTIVITY_REASON.GPU_STATUS_UNAVAILABLE);
    expect(status.retryable).toBe(true);
  });

  it('maps a scan error to failed when nothing else is live', () => {
    const status = resolveActivityStatus({
      scan: idleScan({ errorMessage: 'People identification failed.' }),
      describe: idleDescribe(),
      gpu: gpuInput(),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(status.reason).toBe(ACTIVITY_REASON.SCAN_FAILED);
    expect(status.retryable).toBe(true);
  });

  it('does not treat degraded GPU as a failed run', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: idleDescribe(),
      gpu: gpuInput({ gpuState: GPU_STATE.DEGRADED, reason: 'probe_failed' }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.IDLE);
    expect(status.gpuState).toBe(GPU_STATE.DEGRADED);
    expect(status.canCancel).toBe(false);
  });
});

describe('useActivityStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    installTenant();
    _resetDescribeOperationStoreForTests();
    sessionStorage.clear();
    fetchGpuStatusMock.mockResolvedValue(statusResponse());
    fetchBulkDescribeRunMock.mockResolvedValue(describeRun());
    fetchDescribeRunItemsMock.mockResolvedValue(itemsResponse('run-1', []));
    submitBulkDescribeRunMock.mockResolvedValue(
      describeRun({
        run_id: 'run-2',
        status: DESCRIBE_RUN_STATUS.PENDING,
        phase: DESCRIBE_RUN_PHASE.WARMING,
      }),
    );
  });

  afterEach(async () => {
    await queryClient?.cancelQueries();
    queryClient?.clear();
    _resetDescribeOperationStoreForTests();
    sessionStorage.clear();
    resetConfigCache();
    cleanup();
  });

  it('owns one idle GPU status poll while no describe run is live', async () => {
    const { result } = renderHook(() => useActivityStatus(), { wrapper: createWrapper() });

    await waitFor(() => expect(fetchGpuStatusMock).toHaveBeenCalledTimes(1));
    expect(result.current.status.kind).toBe(ACTIVITY_KIND.IDLE);
    expect(fetchBulkDescribeRunMock).not.toHaveBeenCalled();
  });

  it('pauses the GPU poll while a describe run is in flight', async () => {
    putDescribeOperationContext({
      version: DESCRIBE_OPERATION_CONTEXT_VERSION,
      kind: DESCRIBE_OPERATION_KIND.RUN,
      id: 'run-1',
      startup_id: null,
      started_at: Date.now(),
      request: { writeAlt: false, force: false },
    });
    fetchBulkDescribeRunMock.mockResolvedValue(
      describeRun({ phase: DESCRIBE_RUN_PHASE.WARMING, gpu_state: GPU_STATE.WARMING, eta_seconds: 90, completed: 0 }),
    );

    const { result } = renderHook(() => useActivityStatus(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.status.kind).toBe(ACTIVITY_KIND.WARMING));
    expect(fetchGpuStatusMock).not.toHaveBeenCalled();
    expect(fetchBulkDescribeRunMock).toHaveBeenCalled();
    expect(result.current.status.canCancel).toBe(true);
    expect(result.current.status.etaSeconds).toBe(90);
    expect(result.current.actions.onRetry).not.toBeNull();
  });

  it('composes an injected scan source as scanning', () => {
    const cancelScan = vi.fn();
    const { result } = renderHook(
      () =>
        useActivityStatus({
          scan: {
            isScanning: true,
            progress: { completed: 2, total: 8 },
            etaSeconds: 20,
            jobId: 'job-9',
            cancelScan,
          },
        }),
      { wrapper: createWrapper() },
    );

    expect(result.current.status.kind).toBe(ACTIVITY_KIND.SCANNING);
    expect(result.current.status.progress).toBe(0.25);
    expect(result.current.status.canCancel).toBe(true);
    result.current.actions.onCancel?.();
    expect(cancelScan).toHaveBeenCalledTimes(1);
  });

  it('settles a pending terminal run from the describe poll outcome', async () => {
    putDescribeOperationContext({
      version: DESCRIBE_OPERATION_CONTEXT_VERSION,
      kind: DESCRIBE_OPERATION_KIND.RUN,
      id: 'run-settle',
      startup_id: null,
      started_at: Date.now(),
      request: { writeAlt: false, force: false },
      status: DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK,
    });
    expect(pendingTerminalRuns()[0]?.id).toBe('run-settle');
    fetchBulkDescribeRunMock.mockResolvedValue(
      describeRun({
        run_id: 'run-settle',
        status: DESCRIBE_RUN_STATUS.COMPLETED,
        phase: DESCRIBE_RUN_PHASE.COMPLETE,
        completed: 4,
        eta_seconds: null,
      }),
    );

    const { result } = renderHook(() => useActivityStatus(), { wrapper: createWrapper() });

    await waitFor(() => expect(getLastSettledRun()?.outcome).toBe(DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED));
    expect(pendingTerminalRuns()).toEqual([]);
    expect(result.current.status.kind).toBe(ACTIVITY_KIND.DONE);
    expect(result.current.status.draftCount).toBe(4);
    expect(result.current.actions.reviewDraftsHref).toContain('run-settle');
  });

  it('resubmits unfinished items on GPU warmup-timeout Retry and persists the new run', async () => {
    seedWarmupTimeoutRun('run-old');
    fetchDescribeRunItemsMock.mockResolvedValue(
      itemsResponse('run-old', [
        describeItem(11, 'completed'),
        describeItem(12, 'skipped'),
        describeItem(13, 'failed'),
        describeItem(14, 'pending'),
      ]),
    );
    submitBulkDescribeRunMock.mockResolvedValue(
      describeRun({
        run_id: 'run-new',
        status: DESCRIBE_RUN_STATUS.PENDING,
        phase: DESCRIBE_RUN_PHASE.WARMING,
        gpu_state: GPU_STATE.WARMING,
        eta_seconds: 80,
        completed: 0,
      }),
    );

    const { result } = renderHook(() => useActivityStatus(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.status.reason).toBe(ACTIVITY_REASON.GPU_WARMUP_TIMEOUT));
    expect(result.current.status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(result.current.actions.onRetry).not.toBeNull();

    act(() => {
      result.current.actions.onRetry?.();
    });

    await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(1));
    expect(fetchDescribeRunItemsMock).toHaveBeenCalledWith('run-old');
    expect(submitBulkDescribeRunMock).toHaveBeenCalledWith([13, 14]);
    await waitFor(() => expect(getDescribeRunContext()?.id).toBe('run-new'));
    await waitFor(() => expect(result.current.status.runId).toBe('run-new'));
  });

  it('does not submit a second warmup-timeout resubmit while the first is pending', async () => {
    seedWarmupTimeoutRun('run-1');
    let resolveItems: ((value: DescribeRunItemsResponse) => void) | undefined;
    fetchDescribeRunItemsMock.mockReturnValue(
      new Promise((resolve) => {
        resolveItems = resolve;
      }),
    );

    const { result } = renderHook(() => useActivityStatus(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.actions.onRetry).not.toBeNull());
    act(() => {
      result.current.actions.onRetry?.();
      result.current.actions.onRetry?.();
    });

    // mutate() schedules mutationFn asynchronously; the in-flight ref must still drop the second click.
    await waitFor(() => expect(fetchDescribeRunItemsMock).toHaveBeenCalledTimes(1));
    expect(submitBulkDescribeRunMock).not.toHaveBeenCalled();
    await waitFor(() => expect(result.current.actions.onRetry).toBeNull());
    expect(fetchDescribeRunItemsMock).toHaveBeenCalledTimes(1);

    act(() => {
      resolveItems?.(
        itemsResponse('run-1', [describeItem(21, 'failed'), describeItem(22, 'completed')]),
      );
    });

    await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(1));
    expect(submitBulkDescribeRunMock).toHaveBeenCalledWith([21]);
  });

  it('keeps Retry available after a warmup-timeout resubmit failure', async () => {
    seedWarmupTimeoutRun('run-1');
    fetchDescribeRunItemsMock.mockResolvedValue(
      itemsResponse('run-1', [describeItem(31, 'failed')]),
    );
    submitBulkDescribeRunMock.mockRejectedValue(new Error('could not start run'));

    const { result } = renderHook(() => useActivityStatus(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.status.reason).toBe(ACTIVITY_REASON.GPU_WARMUP_TIMEOUT));
    act(() => {
      result.current.actions.onRetry?.();
    });

    await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.actions.onRetry).not.toBeNull());
    expect(result.current.status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(result.current.status.reason).toBe(ACTIVITY_REASON.GPU_WARMUP_TIMEOUT);
    expect(getDescribeRunContext()?.id).toBe('run-1');
  });

  it('does not submit when warmup-timeout items are already finished and hides Retry', async () => {
    seedWarmupTimeoutRun('run-1');
    fetchDescribeRunItemsMock.mockResolvedValue(
      itemsResponse('run-1', [describeItem(41, 'completed'), describeItem(42, 'skipped')]),
    );

    const { result } = renderHook(() => useActivityStatus(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.actions.onRetry).not.toBeNull());
    act(() => {
      result.current.actions.onRetry?.();
    });

    await waitFor(() => expect(fetchDescribeRunItemsMock).toHaveBeenCalledWith('run-1'));
    await waitFor(() => expect(result.current.actions.onRetry).toBeNull());
    expect(submitBulkDescribeRunMock).not.toHaveBeenCalled();
    expect(result.current.status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(result.current.status.reason).toBe(ACTIVITY_REASON.GPU_WARMUP_TIMEOUT);
  });

  it('retries SCAN_FAILED via the scan source without submitting a describe run', async () => {
    const retryScan = vi.fn();
    const { result } = renderHook(
      () =>
        useActivityStatus({
          scan: {
            isScanning: false,
            errorMessage: 'People identification failed.',
            retryScan,
          },
        }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.status.reason).toBe(ACTIVITY_REASON.SCAN_FAILED));
    act(() => {
      result.current.actions.onRetry?.();
    });
    expect(retryScan).toHaveBeenCalledTimes(1);
    expect(fetchDescribeRunItemsMock).not.toHaveBeenCalled();
    expect(submitBulkDescribeRunMock).not.toHaveBeenCalled();
  });

  it('retries GPU_STATUS_UNAVAILABLE via gpu refetch without submitting a describe run', async () => {
    fetchGpuStatusMock.mockRejectedValue(new Error('gpu down'));
    const { result } = renderHook(() => useActivityStatus(), { wrapper: createWrapper() });

    await waitFor(() =>
      expect(result.current.status.reason).toBe(ACTIVITY_REASON.GPU_STATUS_UNAVAILABLE),
    );
    const callsBefore = fetchGpuStatusMock.mock.calls.length;
    act(() => {
      result.current.actions.onRetry?.();
    });
    await waitFor(() => expect(fetchGpuStatusMock.mock.calls.length).toBeGreaterThan(callsBefore));
    expect(fetchDescribeRunItemsMock).not.toHaveBeenCalled();
    expect(submitBulkDescribeRunMock).not.toHaveBeenCalled();
  });
});
