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
  clearDescribeRunContext,
  clearDescribeSuggestContext,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  DESCRIBE_RUN_RESUME_STATUS,
  DESCRIBE_RUN_SETTLE_OUTCOME,
  describeOperationMediaStorageKey,
  describeOperationRunStorageKey,
  getDescribeRunContext,
  getDescribeSuggestContext,
  getLastSettledRun,
  pendingTerminalRuns,
  putDescribeOperationContext,
  settleRun,
  useDescribeRunContext,
  useDescribeSuggestContext,
  type DescribeOperationContext,
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

const suggestContext = (
  overrides: Partial<DescribeOperationContextInput> = {},
): DescribeOperationContextInput => ({
  version: DESCRIBE_OPERATION_CONTEXT_VERSION,
  kind: DESCRIBE_OPERATION_KIND.SUGGEST,
  id: 'op-lease-1',
  media_id: 42,
  startup_id: 'startup-1',
  started_at: 1_700_000_000_000,
  warming_started_at: 1_700_000_000_000,
  startup_budget_seconds: 510,
  request: { writeAlt: true, force: false },
  ...overrides,
});

const durableContext = (context: DescribeOperationContextInput): DescribeOperationContext => ({
  ...context,
  persistence: 'durable',
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

describe('describeOperationStore', () => {
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

  it('persists a run context in sessionStorage keyed by tenant', () => {
    const context = runContext();
    putDescribeOperationContext(context);

    expect(getDescribeRunContext()).toEqual(durableContext(context));
    expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).toBe(
      JSON.stringify(context),
    );
    expect(sessionStorage.getItem(describeOperationRunStorageKey(FOREIGN_TENANT))).toBeNull();
  });

  it('persists operation_id/startup_id/started_at per media id', () => {
    const context = suggestContext();
    putDescribeOperationContext(context);

    expect(getDescribeSuggestContext(42)).toEqual(durableContext(context));
    expect(sessionStorage.getItem(describeOperationMediaStorageKey(TENANT, 42))).toBe(
      JSON.stringify(context),
    );
    expect(getDescribeSuggestContext(99)).toBeNull();
  });

  it('rehydrates from sessionStorage after a memory reset (reload)', () => {
    putDescribeOperationContext(runContext({ id: 'run-reload' }));
    putDescribeOperationContext(suggestContext({ id: 'op-reload' }));
    _resetDescribeOperationStoreForTests();

    expect(getDescribeRunContext()).toEqual(
      durableContext(runContext({ id: 'run-reload' })),
    );
    expect(getDescribeSuggestContext(42)).toEqual(
      durableContext(suggestContext({ id: 'op-reload' })),
    );
  });

  it('keeps a run resumable when a storage read errors once', () => {
    const context = runContext({ id: 'run-read-retry' });
    const key = describeOperationRunStorageKey(TENANT);
    sessionStorage.setItem(key, JSON.stringify(context));
    _resetDescribeOperationStoreForTests();

    const removeItem = vi.spyOn(Storage.prototype, 'removeItem');
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementationOnce(() => {
      throw new Error('sessionStorage unavailable');
    });
    expect(getDescribeRunContext()).toBeNull();
    expect(removeItem).not.toHaveBeenCalled();

    expect(sessionStorage.getItem(key)).toBe(JSON.stringify(context));
    expect(getDescribeRunContext()).toEqual(durableContext(context));
    getItem.mockRestore();
    removeItem.mockRestore();
  });

  it('marks a snapshot memory_only when sessionStorage cannot write', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });

    putDescribeOperationContext(runContext({ id: 'run-memory-only' }));

    expect(getDescribeRunContext()).toEqual({
      ...runContext({ id: 'run-memory-only' }),
      persistence: 'memory_only',
    });
    setItem.mockRestore();
  });

  it('ignores a foreign-tenant storage key', () => {
    sessionStorage.setItem(
      describeOperationRunStorageKey(FOREIGN_TENANT),
      JSON.stringify(runContext({ id: 'run-foreign' })),
    );
    sessionStorage.setItem(
      describeOperationMediaStorageKey(FOREIGN_TENANT, 42),
      JSON.stringify(suggestContext({ id: 'op-foreign' })),
    );

    expect(getDescribeRunContext()).toBeNull();
    expect(getDescribeSuggestContext(42)).toBeNull();
  });

  it('keeps the in-memory fallback isolated when the configured tenant changes', () => {
    putDescribeOperationContext(runContext({ id: 'run-tenant-a' }));
    putDescribeOperationContext(suggestContext({ id: 'op-tenant-a' }));

    installTenant(FOREIGN_TENANT);
    expect(getDescribeRunContext()).toBeNull();
    expect(getDescribeSuggestContext(42)).toBeNull();

    putDescribeOperationContext(runContext({ id: 'run-tenant-b' }));
    putDescribeOperationContext(suggestContext({ id: 'op-tenant-b' }));
    expect(getDescribeRunContext()?.id).toBe('run-tenant-b');
    expect(getDescribeSuggestContext(42)?.id).toBe('op-tenant-b');

    installTenant(TENANT);
    expect(getDescribeRunContext()?.id).toBe('run-tenant-a');
    expect(getDescribeSuggestContext(42)?.id).toBe('op-tenant-a');

    installTenant(FOREIGN_TENANT);
    clearDescribeRunContext();
    clearDescribeSuggestContext(42);
    installTenant(TENANT);
    expect(getDescribeRunContext()?.id).toBe('run-tenant-a');
    expect(getDescribeSuggestContext(42)?.id).toBe('op-tenant-a');
  });

  it('discards an unknown version instead of partially applying it', () => {
    sessionStorage.setItem(
      describeOperationRunStorageKey(TENANT),
      JSON.stringify({ ...runContext(), version: 2 }),
    );

    expect(getDescribeRunContext()).toBeNull();
    expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).toBeNull();
  });

  it('expires a context once startup_budget_seconds elapses from the persisted start', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_700_000_000_000);
    putDescribeOperationContext(
      suggestContext({
        started_at: 1_700_000_000_000,
        warming_started_at: 1_700_000_000_000,
        startup_budget_seconds: 30,
      }),
    );

    expect(getDescribeSuggestContext(42)).not.toBeNull();

    vi.setSystemTime(1_700_000_000_000 + 30_000);
    _resetDescribeOperationStoreForTests();
    expect(getDescribeSuggestContext(42)).toBeNull();
    expect(sessionStorage.getItem(describeOperationMediaStorageKey(TENANT, 42))).toBeNull();
  });

  it('does not store a suggest context whose startup budget has already elapsed at put time', () => {
    putDescribeOperationContext(
      suggestContext({
        started_at: 1_700_000_000_000 - 511_000,
        warming_started_at: 1_700_000_000_000 - 511_000,
        startup_budget_seconds: 510,
      }),
    );

    expect(getDescribeSuggestContext(42)).toBeNull();
    expect(sessionStorage.getItem(describeOperationMediaStorageKey(TENANT, 42))).toBeNull();
  });

  it('does not expire a run that has no service-advertised startup budget', () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_700_000_000_000);
    putDescribeOperationContext(runContext({ started_at: 1_700_000_000_000 }));

    vi.setSystemTime(1_700_000_000_000 + 86_400_000);
    _resetDescribeOperationStoreForTests();
    expect(getDescribeRunContext()?.id).toBe('run-1');
  });

  it('clears run storage on explicit clear', () => {
    putDescribeOperationContext(runContext());
    clearDescribeRunContext();

    expect(getDescribeRunContext()).toBeNull();
    expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).toBeNull();
  });

  it('does not resurrect a cleared run when removeItem fails', () => {
    const context = runContext({ id: 'run-clear-failed' });
    putDescribeOperationContext(context);
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('sessionStorage unavailable');
    });

    clearDescribeRunContext();
    expect(getDescribeRunContext()).toBeNull();
    _resetDescribeOperationStoreForTests();
    expect(getDescribeRunContext()).toBeNull();
    expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).toBe(
      JSON.stringify(context),
    );

    removeItem.mockRestore();
  });

  it('clears only the matching media slot', () => {
    putDescribeOperationContext(suggestContext({ media_id: 42, id: 'op-42' }));
    putDescribeOperationContext(suggestContext({ media_id: 7, id: 'op-7' }));
    clearDescribeSuggestContext(42);

    expect(getDescribeSuggestContext(42)).toBeNull();
    expect(getDescribeSuggestContext(7)?.id).toBe('op-7');
  });

  it('notifies useSyncExternalStore consumers when the run context changes', () => {
    const { result } = renderHook(() => useDescribeRunContext());
    expect(result.current).toBeNull();

    act(() => {
      putDescribeOperationContext(runContext({ id: 'run-live' }));
    });
    expect(result.current?.id).toBe('run-live');

    act(() => {
      clearDescribeRunContext();
    });
    expect(result.current).toBeNull();
  });

  it('rehydrates a seeded suggest context into the hook after reload', () => {
    sessionStorage.setItem(
      describeOperationMediaStorageKey(TENANT, 42),
      JSON.stringify(suggestContext({ id: 'op-seeded' })),
    );
    _resetDescribeOperationStoreForTests();

    const { result } = renderHook(() => useDescribeSuggestContext(42));
    expect(result.current?.id).toBe('op-seeded');
    expect(result.current?.startup_id).toBe('startup-1');
    expect(result.current?.started_at).toBe(1_700_000_000_000);
  });

  it('treats a missing startup_id as null instead of discarding the context', () => {
    sessionStorage.setItem(
      describeOperationRunStorageKey(TENANT),
      JSON.stringify({
        version: 1,
        kind: 'run',
        id: 'run-no-startup',
        started_at: 1_700_000_000_000,
        request: { writeAlt: false, force: false },
      }),
    );
    _resetDescribeOperationStoreForTests();

    expect(getDescribeRunContext()).toEqual(
      durableContext(runContext({ id: 'run-no-startup', startup_id: null })),
    );
  });

  it('accepts operation_id as the persisted id alias used by Suggest resume', () => {
    sessionStorage.setItem(
      describeOperationMediaStorageKey(TENANT, 42),
      JSON.stringify({
        version: 1,
        kind: 'suggest',
        operation_id: 'op-alias',
        media_id: 42,
        startup_id: null,
        started_at: 1_700_000_000_000,
        request: { writeAlt: false, force: true },
      }),
    );
    _resetDescribeOperationStoreForTests();

    expect(getDescribeSuggestContext(42)?.id).toBe('op-alias');
  });

  it('does not treat a Suggest operation_id alias as a bulk run id', () => {
    const key = describeOperationRunStorageKey(TENANT);
    sessionStorage.setItem(
      key,
      JSON.stringify({
        version: 1,
        kind: 'run',
        operation_id: 'op-not-a-run',
        startup_id: null,
        started_at: 1_700_000_000_000,
        request: { writeAlt: false, force: false },
      }),
    );
    _resetDescribeOperationStoreForTests();

    expect(getDescribeRunContext()).toBeNull();
    expect(sessionStorage.getItem(key)).toBeNull();
  });

  it('keeps an in-memory run when no tenant is configured so existing callers still work', () => {
    resetConfigCache();
    registerConfig({
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {},
    });
    _resetDescribeOperationStoreForTests();
    sessionStorage.clear();

    putDescribeOperationContext(runContext({ id: 'run-memory' }));
    expect(getDescribeRunContext()?.id).toBe('run-memory');
    expect(sessionStorage.length).toBe(0);
  });

  it('marks an expired run needs_terminal_check on remount instead of deleting it', () => {
    const context = runContext({
      id: 'run-expired',
      startup_budget_seconds: 30,
    });
    putDescribeOperationContext(context);
    const key = describeOperationRunStorageKey(TENANT);
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem');

    vi.setSystemTime(1_700_000_000_000 + 30_000);
    _resetDescribeOperationStoreForTests();

    expect(getDescribeRunContext()).toBeNull();
    expect(removeItem).not.toHaveBeenCalled();
    expect(pendingTerminalRuns()).toEqual([
      {
        ...durableContext(context),
        status: DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK,
      },
    ]);
    expect(JSON.parse(sessionStorage.getItem(key) ?? 'null')).toEqual({
      ...context,
      status: DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK,
    });
    removeItem.mockRestore();
  });

  it('does not remove an expired in-session run during subscribe purge', () => {
    const context = runContext({
      id: 'run-subscribe-expired',
      startup_budget_seconds: 30,
    });
    putDescribeOperationContext(context);
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem');

    vi.setSystemTime(1_700_000_000_000 + 30_000);
    const { result } = renderHook(() => useDescribeRunContext());

    expect(result.current).toBeNull();
    expect(removeItem).not.toHaveBeenCalled();
    expect(pendingTerminalRuns()[0]?.id).toBe('run-subscribe-expired');
    expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).not.toBeNull();
    removeItem.mockRestore();
  });

  it('settleRun purges a pending terminal run after the polled outcome is reported', () => {
    putDescribeOperationContext(
      runContext({
        id: 'run-settle',
        startup_budget_seconds: 30,
      }),
    );
    vi.setSystemTime(1_700_000_000_000 + 30_000);
    _resetDescribeOperationStoreForTests();
    expect(pendingTerminalRuns()).toHaveLength(1);

    const removeItem = vi.spyOn(Storage.prototype, 'removeItem');
    settleRun('run-settle', DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED);

    expect(removeItem).toHaveBeenCalled();
    expect(pendingTerminalRuns()).toEqual([]);
    expect(getDescribeRunContext()).toBeNull();
    expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).toBeNull();
    expect(getLastSettledRun()).toEqual({
      id: 'run-settle',
      outcome: DESCRIBE_RUN_SETTLE_OUTCOME.COMPLETED,
    });
    removeItem.mockRestore();
  });

  it('settleRun ignores a different run id and an unknown outcome', () => {
    putDescribeOperationContext(
      runContext({
        id: 'run-keep',
        startup_budget_seconds: 30,
      }),
    );
    vi.setSystemTime(1_700_000_000_000 + 30_000);
    _resetDescribeOperationStoreForTests();

    settleRun('run-other', DESCRIBE_RUN_SETTLE_OUTCOME.FAILED);
    expect(pendingTerminalRuns()[0]?.id).toBe('run-keep');

    settleRun('run-keep', 'not-an-outcome' as never);
    expect(pendingTerminalRuns()[0]?.id).toBe('run-keep');
    expect(getLastSettledRun()).toBeNull();
  });

  it('does not list an in-budget run as pending terminal', () => {
    putDescribeOperationContext(
      runContext({
        id: 'run-live',
        startup_budget_seconds: 30,
      }),
    );
    expect(pendingTerminalRuns()).toEqual([]);
    expect(getDescribeRunContext()?.id).toBe('run-live');
  });

  it('persists progress_mounted on the run record across remount', () => {
    const context = runContext({ id: 'run-progress', progress_mounted: true });
    putDescribeOperationContext(context);
    const stored = sessionStorage.getItem(describeOperationRunStorageKey(TENANT));
    expect(JSON.parse(stored ?? 'null')).toEqual(context);

    _resetDescribeOperationStoreForTests();
    expect(getDescribeRunContext()).toEqual(durableContext(context));

    const { result } = renderHook(() => useActiveDescribeRun());
    expect(result.current).toEqual({ runId: 'run-progress', progressMounted: true });
  });

  it('setDescribeProgressMounted writes progress_mounted into sessionStorage', () => {
    setActiveDescribeRunId('run-mounted');
    const setItem = vi.spyOn(Storage.prototype, 'setItem');

    act(() => {
      setDescribeProgressMounted(true);
    });

    expect(setItem).toHaveBeenCalled();
    const persisted = sessionStorage.getItem(describeOperationRunStorageKey(TENANT));
    expect(persisted).not.toBeNull();
    expect(JSON.parse(persisted ?? '{}').progress_mounted).toBe(true);
    expect(JSON.parse(persisted ?? '{}').id).toBe('run-mounted');

    _resetDescribeOperationStoreForTests();
    expect(getDescribeRunContext()?.progress_mounted).toBe(true);

    const { result } = renderHook(() => useActiveDescribeRun());
    expect(result.current).toEqual({ runId: 'run-mounted', progressMounted: true });
    setItem.mockRestore();
  });
});
