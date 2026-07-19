import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../api/queryKeys';
import * as recognitionApi from '../../api/recognition';
import { useSyncTrigger } from '../useSyncTrigger';

vi.mock('../../api/recognition', () => ({
  triggerSync: vi.fn(),
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, queryClient };
};

const failedSyncResponse: recognitionApi.SyncTriggerResponse = {
  synced: false,
  reason: 'sync_failed',
  last_snapshot_version: 0,
  last_synced_at: null,
  is_stale: true,
  sync_health: 'offline',
  last_sync_result: 'unreachable',
};

const successfulSyncResponse: recognitionApi.SyncTriggerResponse = {
  synced: true,
  reason: 'ok',
  last_snapshot_version: 3,
  last_synced_at: '2026-02-19 12:00:00',
  is_stale: false,
  sync_health: 'healthy',
  last_sync_result: 'ok',
};

describe('useSyncTrigger', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not auto-trigger by default when projection is stale', async () => {
    const triggerSyncMock = vi.mocked(recognitionApi.triggerSync);
    triggerSyncMock.mockResolvedValue(failedSyncResponse);

    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useSyncTrigger(true), { wrapper });

    await act(async () => {
      await Promise.resolve();
    });

    expect(triggerSyncMock).not.toHaveBeenCalled();
    queryClient.clear();
  });

  it('triggers once when stale if auto-trigger is explicitly enabled', async () => {
    const triggerSyncMock = vi.mocked(recognitionApi.triggerSync);
    triggerSyncMock.mockResolvedValue(failedSyncResponse);

    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useSyncTrigger(true, true), { wrapper });

    await act(async () => {
      await Promise.resolve();
    });
    expect(triggerSyncMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(120_000);
      await Promise.resolve();
    });

    expect(triggerSyncMock).toHaveBeenCalledTimes(1);
    queryClient.clear();
  });

  it('re-attempts once when stale transitions from false back to true (auto mode)', async () => {
    const triggerSyncMock = vi.mocked(recognitionApi.triggerSync);
    triggerSyncMock.mockResolvedValue(successfulSyncResponse);

    const { wrapper, queryClient } = createWrapper();
    const { rerender } = renderHook(({ isStale }) => useSyncTrigger(isStale, true), {
      wrapper,
      initialProps: { isStale: true },
    });

    await act(async () => {
      await Promise.resolve();
    });
    expect(triggerSyncMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      rerender({ isStale: false });
      await Promise.resolve();
    });

    await act(async () => {
      rerender({ isStale: true });
      await Promise.resolve();
    });

    expect(triggerSyncMock).toHaveBeenCalledTimes(2);
    queryClient.clear();
  });

  it('does not retry on tab visibility changes after already attempting in current stale cycle', async () => {
    const triggerSyncMock = vi.mocked(recognitionApi.triggerSync);
    triggerSyncMock.mockResolvedValue(failedSyncResponse);

    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'hidden',
    });

    const { wrapper, queryClient } = createWrapper();
    renderHook(() => useSyncTrigger(true, true), { wrapper });

    await act(async () => {
      await Promise.resolve();
    });
    expect(triggerSyncMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      Object.defineProperty(document, 'visibilityState', {
        configurable: true,
        value: 'visible',
      });
      document.dispatchEvent(new Event('visibilitychange'));
      await Promise.resolve();
    });

    expect(triggerSyncMock).toHaveBeenCalledTimes(1);
    queryClient.clear();
  });

  it('invalidates suggestions.all root on successful sync (projection nests under it)', async () => {
    // TEST-06 predicted first failure if root invalidation regresses:
    // "expected invalidateQueries to have been called with { queryKey: ['suggestions'] }"
    // (viaSuggestionsAllRoot — projection is not targeted directly).
    const triggerSyncMock = vi.mocked(recognitionApi.triggerSync);
    triggerSyncMock.mockResolvedValue(successfulSyncResponse);

    const { wrapper, queryClient } = createWrapper();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useSyncTrigger(false), { wrapper });

    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.all });
    queryClient.clear();
  });
});
