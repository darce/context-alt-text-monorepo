import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { PropsWithChildren, ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../api/config';
import { queryKeys } from '../../api/queryKeys';
import { fetchTenantUsage } from '../../api/usageApi';
import { buildTestQueryClient } from '../../test-utils/queryClient';
import { createAppQueryClient } from '../../utils/appQueryClient';
import { _resetCooldownForTests, isCoolingDown } from '../../utils/recognitionCooldown';
import { isCooldownSignal } from '../../utils/retryPolicy';
import {
  _resetActiveDescribeRunForTests,
  clearActiveDescribeRunId,
  setActiveDescribeRunId,
} from '../activeDescribeRun';
import { _resetDescribeOperationStoreForTests } from '../describeOperationStore';
import { TENANT_USAGE_STALE_TIME_MS, TenantUsageUnavailableError, useTenantUsage } from '../useTenantUsage';

const usageBody = {
  tenant_id: '00000000-0000-4000-8000-000000000001',
  used: 120,
  reserved: 8,
  remaining: 372,
  allowance: 500,
  period_start: '2026-10-01T00:00:00Z',
  period_end: '2026-11-01T00:00:00Z',
  period: { start: '2026-10-01T00:00:00Z', end: '2026-11-01T00:00:00Z' },
  as_of: '2026-10-26T09:30:00Z',
  status: 'paid_active',
  data_source: 'authoritative',
};

const fetchMock = vi.fn<typeof fetch>();

const renderUsage = (client: QueryClient) =>
  renderHook(() => useTenantUsage(), {
    wrapper: ({ children }: PropsWithChildren): ReactElement => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });

beforeEach(() => {
  resetConfigCache();
  registerConfig({
    nonce: 'abcdef1234',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: { usage: 'https://example.test/wp-json/acx/v1/usage' },
    tenant_id: 'tenant-usage-test',
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
  sessionStorage.clear();
  _resetDescribeOperationStoreForTests();
  _resetActiveDescribeRunForTests();
  _resetCooldownForTests();
  resetConfigCache();
});

describe('useTenantUsage', () => {
  it('reads with a 60 s stale time and refetches on window focus', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(new Response(JSON.stringify(usageBody), { status: 200 })));
    const client = buildTestQueryClient();

    const { result } = renderUsage(client);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const query = client.getQueryCache().find({ queryKey: queryKeys.usage.tenant() });
    expect(TENANT_USAGE_STALE_TIME_MS).toBe(60_000);
    expect(query?.options).toMatchObject({ staleTime: 60_000, refetchOnWindowFocus: true });
  });

  it('re-reads the balance when the active describe run settles', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(new Response(JSON.stringify(usageBody), { status: 200 })));
    setActiveDescribeRunId('run-1');

    const { result } = renderUsage(buildTestQueryClient());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    act(() => {
      clearActiveDescribeRunId('run-1');
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('does not re-read while no run has settled', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(new Response(JSON.stringify(usageBody), { status: 200 })));

    const { result, rerender } = renderUsage(buildTestQueryClient());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    rerender();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('keeps a throttled usage read from arming the shared recognition cooldown [rg-003]', async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response('{"code":"rate_limited"}', { status: 429, headers: { 'Retry-After': '30' } })),
    );
    // Precondition: the raw usage error IS a cooldown signal, so this test can go red.
    const rawError: unknown = await fetchTenantUsage().catch((error: unknown) => error);
    expect(isCooldownSignal(rawError)).toBe(true);

    const { result } = renderUsage(createAppQueryClient());
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeInstanceOf(TenantUsageUnavailableError);
    expect(isCoolingDown()).toBe(false);
  });
});
