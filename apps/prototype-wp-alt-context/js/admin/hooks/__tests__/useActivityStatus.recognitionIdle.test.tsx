// @vitest-environment jsdom
/**
 * Boundary between background GPU status and the activity strip.
 *
 * An idle or healthy face scan with no describe run must not read as failed
 * only because the background Description Service status is unavailable. Live
 * scan, describe, and real terminal evidence must keep their own classification.
 */
import type { QueryClient } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../api/config';
import {
  DESCRIBE_RUN_PHASE,
  DESCRIBE_RUN_STATUS,
  GPU_STATE,
  type DescribeRunResponse,
  type GpuState,
} from '../../api/describeApi';
import { GPU_INTENT_ACTION, GPU_INTENT_STATUS, type GpuStatusResponse } from '../../api/gpuApi';
import * as gpuApi from '../../api/gpuApi';
import { queryKeys } from '../../api/queryKeys';
import { _resetDescribeOperationStoreForTests } from '../describeOperationStore';
import type { DescribeRunProgress } from '../useDescribeRunProgress';
import { buildTestQueryClient, createQueryWrapper } from '../../test-utils/queryClient';
import {
  ACTIVITY_KIND,
  ACTIVITY_REASON,
  resolveActivityStatus,
  useActivityStatus,
  type DescribeActivityInput,
  type GpuActivityInput,
  type ScanActivityInput,
} from '../useActivityStatus';

vi.mock('../../api/gpuApi', async (importOriginal) => {
  const actual = await importOriginal<typeof gpuApi>();
  return { ...actual, fetchGpuStatus: vi.fn() };
});

const fetchGpuStatusMock = vi.mocked(gpuApi.fetchGpuStatus);

const TENANT = 'tenant-a';
const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set([
  DESCRIBE_RUN_STATUS.COMPLETED,
  DESCRIBE_RUN_STATUS.COMPLETED_WITH_ERRORS,
  DESCRIBE_RUN_STATUS.FAILED,
  DESCRIBE_RUN_STATUS.CANCELLED,
]);

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
  const run = describeRun(runOverrides);
  return {
    run,
    status: run.status,
    progressFraction: (run.completed + run.failed + run.skipped) / run.total,
    etaSeconds: run.eta_seconds,
    gpuState: (run.gpu_state as GpuState | null | undefined) ?? GPU_STATE.UNKNOWN,
    isWarming: run.phase === DESCRIBE_RUN_PHASE.WARMING,
    isTerminal: TERMINAL_RUN_STATUSES.has(run.status),
    stalledForSeconds: null,
    isPolling: true,
    isFrozen: false,
    isError: false,
    error: null,
    retry: vi.fn(),
    ...overrides,
  };
};

const idleDescribe = (): DescribeActivityInput => ({
  runId: null,
  progress: {
    run: null,
    status: null,
    progressFraction: null,
    etaSeconds: null,
    gpuState: GPU_STATE.UNKNOWN,
    isWarming: false,
    isTerminal: false,
    stalledForSeconds: null,
    isPolling: false,
    isFrozen: false,
    isError: false,
    error: null,
    retry: vi.fn(),
  },
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

const installTenant = (): void => {
  resetConfigCache();
  registerConfig({
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {},
    tenant_id: TENANT,
  });
};

describe('resolveActivityStatus with background GPU status unavailable', () => {
  it('does not fail an idle face scan with no describe run just because GPU status is unavailable', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: idleDescribe(),
      gpu: gpuInput({ isError: true, gpuState: GPU_STATE.UNKNOWN }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.IDLE);
  });

  it('keeps an active face scan visible while GPU status is unavailable', () => {
    const status = resolveActivityStatus({
      scan: idleScan({ isScanning: true, progressFraction: 0.5, etaSeconds: 12, jobId: 'job-1' }),
      describe: idleDescribe(),
      gpu: gpuInput({ isError: true, gpuState: GPU_STATE.UNKNOWN }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.SCANNING);
    expect(status.progress).toBe(0.5);
    expect(status.canCancel).toBe(true);
  });

  it('keeps a live describe run visible and cancellable while GPU status is unavailable', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-1',
        progress: describeProgress({ progressFraction: 0.25, etaSeconds: 40 }),
      },
      gpu: gpuInput({ isError: true, gpuState: GPU_STATE.UNKNOWN, isRunPending: true }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.DESCRIBING);
    expect(status.runId).toBe('run-1');
    expect(status.canCancel).toBe(true);
    expect(status.retryable).toBe(false);
  });

  it('keeps a describe poll error visible and retryable while GPU status is unavailable', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-1',
        progress: describeProgress({ isError: true, isPolling: false, error: new Error('timeout') }),
      },
      gpu: gpuInput({ isError: true, gpuState: GPU_STATE.UNKNOWN, isRunPending: true }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(status.reason).toBe(ACTIVITY_REASON.DESCRIBE_POLL_ERROR);
    expect(status.retryable).toBe(true);
    expect(status.canCancel).toBe(true);
  });

  it('keeps a scan error visible and retryable while GPU status is unavailable', () => {
    const status = resolveActivityStatus({
      scan: idleScan({ errorMessage: 'People identification failed.' }),
      describe: idleDescribe(),
      gpu: gpuInput({ isError: true, gpuState: GPU_STATE.UNKNOWN }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(status.reason).toBe(ACTIVITY_REASON.SCAN_FAILED);
    expect(status.retryable).toBe(true);
  });

  it('classifies a real failed describe run by its own terminal evidence, not as GPU status unavailable', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-1',
        progress: describeProgress(
          {},
          {
            status: DESCRIBE_RUN_STATUS.FAILED,
            phase: DESCRIBE_RUN_PHASE.FAILED,
            completed: 1,
            failed: 3,
            eta_seconds: null,
          },
        ),
      },
      gpu: gpuInput({ isError: true, gpuState: GPU_STATE.UNKNOWN }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.FAILED);
    expect(status.reason).toBe(ACTIVITY_REASON.FAILED);
  });

  it('keeps a real completed describe run as done while GPU status is unavailable', () => {
    const status = resolveActivityStatus({
      scan: idleScan(),
      describe: {
        runId: 'run-1',
        progress: describeProgress(
          {},
          {
            status: DESCRIBE_RUN_STATUS.COMPLETED,
            phase: DESCRIBE_RUN_PHASE.COMPLETE,
            completed: 4,
            failed: 0,
            eta_seconds: null,
          },
        ),
      },
      gpu: gpuInput({ isError: true, gpuState: GPU_STATE.UNKNOWN }),
    });
    expect(status.kind).toBe(ACTIVITY_KIND.DONE);
    expect(status.draftCount).toBe(4);
    expect(status.retryable).toBe(false);
  });
});

describe('useActivityStatus after a transient GPU status failure', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    installTenant();
    _resetDescribeOperationStoreForTests();
    sessionStorage.clear();
    fetchGpuStatusMock.mockResolvedValue(statusResponse());
  });

  afterEach(async () => {
    await queryClient?.cancelQueries();
    queryClient?.clear();
    _resetDescribeOperationStoreForTests();
    sessionStorage.clear();
    resetConfigCache();
    cleanup();
  });

  it('does not keep a transient GPU status failure as sticky strip state after GPU status recovers', async () => {
    fetchGpuStatusMock.mockRejectedValueOnce(new Error('gpu down'));
    queryClient = buildTestQueryClient();
    const { result } = renderHook(() => useActivityStatus(), { wrapper: createQueryWrapper(queryClient) });

    await waitFor(() => expect(queryClient.getQueryState(queryKeys.gpu.status())?.status).toBe('error'));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: queryKeys.gpu.status(), exact: true });
    });

    await waitFor(() => expect(result.current.status.kind).toBe(ACTIVITY_KIND.IDLE));
  });
});
