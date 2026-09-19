import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../api/config';
import {
  _resetActiveDescribeRunForTests,
  setActiveDescribeRunId,
  setDescribeProgressMounted,
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

  it('does not copy tenant A progress_mounted onto tenant B live run', () => {
    setActiveDescribeRunId('a-run');
    setDescribeProgressMounted(true);
    expect(getDescribeRunContext()?.progress_mounted).toBe(true);

    installTenant(FOREIGN_TENANT);
    setActiveDescribeRunId('b-run');

    const live = getDescribeRunContext();
    expect(live?.id).toBe('b-run');
    expect(live?.progress_mounted).toBeUndefined();

    const persisted = sessionStorage.getItem(describeOperationRunStorageKey(FOREIGN_TENANT));
    expect(persisted).not.toBeNull();
    expect(JSON.parse(persisted ?? '{}').progress_mounted).toBeUndefined();
    expect(JSON.parse(persisted ?? '{}').id).toBe('b-run');
  });
});
