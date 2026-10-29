// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../api/config';
import {
  _resetActiveDescribeRunForTests,
  setActiveDescribeRunId,
  setDescribeProgressMounted,
  useActiveDescribeRun,
} from '../activeDescribeRun';
import {
  _resetDescribeOperationStoreForTests,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  DESCRIBE_RUN_RESUME_STATUS,
  DESCRIBE_RUN_SETTLE_OUTCOME,
  describeOperationRunStorageKey,
  getDescribeRunContext,
  getLastSettledRun,
  pendingTerminalRuns,
  putDescribeOperationContext,
  settleRun,
  type DescribeOperationContextInput,
} from '../describeOperationStore';

import { GPU_STATE } from '../../api/describeApi';
import { ACTIVITY_KIND } from '../useActivityStatus';
import { useGpuStateToasts } from '../useGpuStateToasts';

const toastState = vi.hoisted(() => ({
  info: vi.fn(), success: vi.fn(), error: vi.fn(), activity: vi.fn(),
}));
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }));
vi.mock('../../context/ToastContext', () => ({ useToast: () => toastState }));
vi.mock('../useActivityStatus', async (importOriginal) => ({
  ...await importOriginal<typeof import('../useActivityStatus')>(),
  useActivityStatus: () => toastState.activity(),
}));

const TENANT = 'tenant-a';
const FOREIGN_TENANT = 'tenant-b';

const runContext = (
  overrides: Partial<DescribeOperationContextInput> = {},
): DescribeOperationContextInput => ({
  version: DESCRIBE_OPERATION_CONTEXT_VERSION,
  kind: DESCRIBE_OPERATION_KIND.RUN,
  id: 'run-1',
  startup_id: 'startup-1',
  started_at: 1_700_000_000_000,
  request: { writeAlt: false, force: false },
  ...overrides,
});

const installTenant = (tenantId: string): void => {
  resetConfigCache();
  registerConfig({
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {},
    tenant_id: tenantId,
  });
};

describe('activeDescribeRun', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(1_700_000_000_000);
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    _resetActiveDescribeRunForTests();
    installTenant(TENANT);
    setDescribeProgressMounted(false);
    setActiveDescribeRunId(null);
  });

  afterEach(() => {
    setActiveDescribeRunId(null);
    setDescribeProgressMounted(false);
    _resetActiveDescribeRunForTests();
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    resetConfigCache();
    vi.useRealTimers();
  });

  it('keeps a pending terminal run when a new live run is set', () => {
    const context = runContext({
      id: 'run-expired',
      startup_budget_seconds: 30,
    });
    putDescribeOperationContext(context);

    vi.setSystemTime(1_700_000_000_000 + 30_000);
    _resetDescribeOperationStoreForTests();

    expect(getDescribeRunContext()).toBeNull();
    expect(pendingTerminalRuns()).toHaveLength(1);
    expect(pendingTerminalRuns()[0]?.id).toBe('run-expired');

    setActiveDescribeRunId('new');

    expect(getDescribeRunContext()?.id).toBe('new');
    expect(pendingTerminalRuns().map((run) => run.id)).toContain('run-expired');
    expect(pendingTerminalRuns().find((run) => run.id === 'run-expired')?.status).toBe(
      DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK,
    );

    _resetDescribeOperationStoreForTests();
    expect(getDescribeRunContext()?.id).toBe('new');
    expect(pendingTerminalRuns().map((run) => run.id)).toContain('run-expired');
  });

  it('settleRun still reports a parked pending run after a new live run is set', () => {
    putDescribeOperationContext(
      runContext({
        id: 'run-expired',
        startup_budget_seconds: 30,
      }),
    );
    vi.setSystemTime(1_700_000_000_000 + 30_000);
    _resetDescribeOperationStoreForTests();
    setActiveDescribeRunId('new');

    settleRun('run-expired', DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED);

    expect(pendingTerminalRuns().map((run) => run.id)).not.toContain('run-expired');
    expect(getLastSettledRun()).toEqual({
      id: 'run-expired',
      outcome: DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED,
    });
    expect(getDescribeRunContext()?.id).toBe('new');
  });

  it('counts overlapping mounts and floors extra unmounts at zero', () => {
    const { result } = renderHook(() => useActiveDescribeRun());
    act(() => {
      setDescribeProgressMounted(true);
      setDescribeProgressMounted(true);
      setDescribeProgressMounted(false);
    });
    expect(result.current.progressMounted).toBe(true);
    act(() => setDescribeProgressMounted(false));
    expect(result.current.progressMounted).toBe(false);
    act(() => {
      setDescribeProgressMounted(false);
      setDescribeProgressMounted(true);
    });
    expect(result.current.progressMounted).toBe(true);
  });

  it('reload preserves the run without restoring a legacy mounted view', () => {
    sessionStorage.setItem(describeOperationRunStorageKey(TENANT), JSON.stringify({
      ...runContext(), progress_mounted: true,
    }));
    _resetActiveDescribeRunForTests();
    _resetDescribeOperationStoreForTests();
    const { result } = renderHook(() => useActiveDescribeRun());
    expect(result.current).toEqual({ runId: 'run-1', progressMounted: false });
  });

  it.each([
    [ACTIVITY_KIND.DONE, 'success', DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED],
    [ACTIVITY_KIND.FAILED, 'error', DESCRIBE_RUN_SETTLE_OUTCOME.FAILED],
  ] as const)('rehydrated run emits warm-up and %s outcome without a progress view', (kind, toast, outcome) => {
    sessionStorage.setItem(describeOperationRunStorageKey(TENANT), JSON.stringify({
      ...runContext(), progress_mounted: true,
    }));
    _resetDescribeOperationStoreForTests();
    _resetActiveDescribeRunForTests();
    toastState.info.mockClear();
    toastState.success.mockClear();
    toastState.error.mockClear();
    let status = { kind: ACTIVITY_KIND.IDLE, runId: getDescribeRunContext()!.id, gpuState: GPU_STATE.STOPPED };
    toastState.activity.mockImplementation(() => ({ status, actions: {} }));
    const { rerender } = renderHook(() => useGpuStateToasts());
    status = { ...status, kind: ACTIVITY_KIND.WARMING as typeof status.kind, gpuState: GPU_STATE.STARTING as typeof status.gpuState };
    rerender();
    expect(toastState.info).toHaveBeenCalled();
    act(() => settleRun('run-1', outcome));
    status = { ...status, kind: kind as typeof status.kind };
    rerender();
    expect(toastState[toast]).toHaveBeenCalled();
  });

  it('does not copy tenant A progress_mounted onto tenant B live run', () => {
    setActiveDescribeRunId('a-run');
    setDescribeProgressMounted(true);
    expect(getDescribeRunContext()).not.toHaveProperty('progress_mounted');

    installTenant(FOREIGN_TENANT);
    setActiveDescribeRunId('b-run');

    const live = getDescribeRunContext();
    expect(live?.id).toBe('b-run');
    expect(live).not.toHaveProperty('progress_mounted');

    const persisted = sessionStorage.getItem(describeOperationRunStorageKey(FOREIGN_TENANT));
    expect(persisted).not.toBeNull();
    expect(JSON.parse(persisted ?? '{}').progress_mounted).toBeUndefined();
    expect(JSON.parse(persisted ?? '{}').id).toBe('b-run');
  });
});
