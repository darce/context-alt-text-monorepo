import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../api/config';
import {
  _resetDescribeOperationStoreForTests,
  clearDescribeRunContext,
  clearDescribeSuggestContext,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  describeOperationMediaStorageKey,
  describeOperationRunStorageKey,
  getDescribeRunContext,
  getDescribeSuggestContext,
  putDescribeOperationContext,
  useDescribeRunContext,
  useDescribeSuggestContext,
  type DescribeOperationContext,
} from '../describeOperationStore';

const TENANT = 'tenant-a';
const FOREIGN_TENANT = 'tenant-b';

const runContext = (
  overrides: Partial<DescribeOperationContext> = {},
): DescribeOperationContext => ({
  version: DESCRIBE_OPERATION_CONTEXT_VERSION,
  kind: DESCRIBE_OPERATION_KIND.RUN,
  id: 'run-1',
  startup_id: 'startup-1',
  started_at: 1_700_000_000_000,
  request: { writeAlt: false, force: false },
  ...overrides,
});

const suggestContext = (
  overrides: Partial<DescribeOperationContext> = {},
): DescribeOperationContext => ({
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
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    installTenant(TENANT);
  });

  afterEach(() => {
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    resetConfigCache();
    vi.useRealTimers();
  });

  it('persists a run context in sessionStorage keyed by tenant', () => {
    const context = runContext();
    putDescribeOperationContext(context);

    expect(getDescribeRunContext()).toEqual(context);
    expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).toBe(
      JSON.stringify(context),
    );
    expect(sessionStorage.getItem(describeOperationRunStorageKey(FOREIGN_TENANT))).toBeNull();
  });

  it('persists operation_id/startup_id/started_at per media id', () => {
    const context = suggestContext();
    putDescribeOperationContext(context);

    expect(getDescribeSuggestContext(42)).toEqual(context);
    expect(sessionStorage.getItem(describeOperationMediaStorageKey(TENANT, 42))).toBe(
      JSON.stringify(context),
    );
    expect(getDescribeSuggestContext(99)).toBeNull();
  });

  it('rehydrates from sessionStorage after a memory reset (reload)', () => {
    putDescribeOperationContext(runContext({ id: 'run-reload' }));
    putDescribeOperationContext(suggestContext({ id: 'op-reload' }));
    _resetDescribeOperationStoreForTests();

    expect(getDescribeRunContext()).toEqual(runContext({ id: 'run-reload' }));
    expect(getDescribeSuggestContext(42)).toEqual(suggestContext({ id: 'op-reload' }));
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

  it('discards an unknown version instead of partially applying it', () => {
    sessionStorage.setItem(
      describeOperationRunStorageKey(TENANT),
      JSON.stringify({ ...runContext(), version: 2 }),
    );

    expect(getDescribeRunContext()).toBeNull();
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
      runContext({ id: 'run-no-startup', startup_id: null }),
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
});
