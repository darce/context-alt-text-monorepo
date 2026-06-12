import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../api/recognition';
import { syncHealthPollingIntervals, useSyncHealth } from '../useSyncHealth';

vi.mock('../../api/recognition', async () => {
  const actual = await vi.importActual<typeof recognitionApi>('../../api/recognition');
  return {
    ...actual,
    fetchSyncHealth: vi.fn(),
  };
});

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('useSyncHealth', () => {
  it('polls sync health with at least 15s stale time', async () => {
    const fetchSyncHealthMock = vi.mocked(recognitionApi.fetchSyncHealth);
    fetchSyncHealthMock.mockResolvedValue({
      breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
      outbox: { pending: 0, failed: 0 },
      conflicts: { open: 0 },
      replays: { failed: null, source: 'unavailable_local' },
      last_pull: { at: null, ok: true },
      warnings: [],
    });

    const { result } = renderHook(() => useSyncHealth(), { wrapper });

    await waitFor(() => expect(fetchSyncHealthMock).toHaveBeenCalled());
    expect(result.current.data?.breaker.state).toBe('closed');
    expect(syncHealthPollingIntervals.staleTime).toBeGreaterThanOrEqual(15_000);
    expect(syncHealthPollingIntervals.refetchInterval).toBeGreaterThanOrEqual(15_000);
  });
});
