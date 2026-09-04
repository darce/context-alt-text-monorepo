import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RECOVERY_DELAY_FLOOR_MS, useMediaIdentities } from '../useMediaIdentities';
import * as recognitionApi from '../../api/recognition';
import {
  _resetCooldownForTests,
  DEFAULT_COOLDOWN_SECONDS,
  openCooldown,
} from '../../utils/recognitionCooldown';

vi.mock('../../api/recognition', () => ({
  fetchMediaIdentities: vi.fn(),
}));

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

describe('useMediaIdentities', () => {
  const createWrapper = () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { wrapper, queryClient };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    _resetCooldownForTests();
  });

  afterEach(() => {
    _resetCooldownForTests();
    vi.useRealTimers();
  });

  it('fetches identities when enabled and media IDs exist', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    const identitiesDeferred = createDeferred<recognitionApi.MediaIdentitiesResponse>();
    fetchMediaIdentitiesMock.mockReturnValue(identitiesDeferred.promise);

    const { result } = renderHook(() => useMediaIdentities([1, 2], true), { wrapper });

    await waitFor(() => expect(fetchMediaIdentitiesMock).toHaveBeenCalledWith([1, 2]));

    await act(async () => {
      identitiesDeferred.resolve({ identities_by_media: {} });
      await identitiesDeferred.promise;
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    queryClient.clear();
  });

  it('does not issue a fetch when disabled or when IDs are empty', async () => {
    const { wrapper, queryClient } = createWrapper();

    renderHook(() => useMediaIdentities([], true), { wrapper });
    renderHook(() => useMediaIdentities([3], false), { wrapper });

    await waitFor(() => expect(recognitionApi.fetchMediaIdentities).not.toHaveBeenCalled());

    queryClient.clear();
  });

  it('does not React Query-retry on failure (retry:false pin; fails if hook default is removed)', async () => {
    // Wrapper deliberately enables client-level retries so a missing hook-level
    // `retry: false` would produce multiple attempts before the recovery floor.
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: 3, retryDelay: 1 } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    fetchMediaIdentitiesMock.mockRejectedValue(new Error('timeout'));

    const { result, unmount } = renderHook(() => useMediaIdentities([99], true), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    // Exactly one attempt before any recovery-floor deferred refetch.
    expect(fetchMediaIdentitiesMock).toHaveBeenCalledTimes(1);

    unmount();
    queryClient.clear();
  });

  it('S3-T5: one-shot recovery latch — arms once per error episode, floor delay, no re-arm on second error', async () => {
    vi.useFakeTimers();
    const { wrapper, queryClient } = createWrapper();
    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    fetchMediaIdentitiesMock.mockRejectedValue(new Error('timeout'));

    const { result, unmount } = renderHook(() => useMediaIdentities([42], true), { wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const afterFirstError = fetchMediaIdentitiesMock.mock.calls.length;
    expect(afterFirstError).toBe(1);

    // Before floor: no deferred recovery.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECOVERY_DELAY_FLOOR_MS - 1);
    });
    expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterFirstError);

    // Cross floor: exactly one deferred refetch.
    fetchMediaIdentitiesMock.mockRejectedValueOnce(new Error('timeout-again'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterFirstError + 1));

    // Second consecutive error does NOT re-arm — advance another full floor window.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECOVERY_DELAY_FLOOR_MS + 5_000);
    });
    expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterFirstError + 1);

    unmount();
    queryClient.clear();
  });

  it('S3-T5: recovery delay respects active cooldown (max of remaining and floor)', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T12:00:00.000Z'));
    openCooldown(DEFAULT_COOLDOWN_SECONDS + 30); // 60s cooldown > floor

    const { wrapper, queryClient } = createWrapper();
    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    fetchMediaIdentitiesMock.mockRejectedValue(new Error('timeout'));

    const { result, unmount } = renderHook(() => useMediaIdentities([7], true), { wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const afterError = fetchMediaIdentitiesMock.mock.calls.length;

    // Floor alone is not enough when cooldown remaining is larger.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECOVERY_DELAY_FLOOR_MS);
    });
    expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterError);

    // After full cooldown window, recovery fires once.
    fetchMediaIdentitiesMock.mockRejectedValueOnce(new Error('still-down'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterError + 1));

    unmount();
    queryClient.clear();
  });

  it('S3-T5: unmount cancels pending recovery; success resets the latch for a later episode', async () => {
    vi.useFakeTimers();
    const { wrapper, queryClient } = createWrapper();
    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    fetchMediaIdentitiesMock.mockRejectedValue(new Error('timeout'));

    const first = renderHook(() => useMediaIdentities([9], true), { wrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(first.result.current.isError).toBe(true));
    const afterError = fetchMediaIdentitiesMock.mock.calls.length;

    first.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECOVERY_DELAY_FLOOR_MS + 1_000);
    });
    // Cancelled on unmount — no recovery fetch.
    expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterError);

    // Success path resets latch so a subsequent error can arm again.
    fetchMediaIdentitiesMock.mockResolvedValueOnce({
      identities_by_media: {},
      data_source: 'local_projection',
    });
    const second = renderHook(() => useMediaIdentities([9], true), { wrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(second.result.current.isSuccess).toBe(true));

    fetchMediaIdentitiesMock.mockRejectedValue(new Error('timeout-2'));
    await act(async () => {
      await second.result.current.refetch();
    });
    await waitFor(() => expect(second.result.current.isError).toBe(true));
    const afterSecondError = fetchMediaIdentitiesMock.mock.calls.length;

    fetchMediaIdentitiesMock.mockRejectedValueOnce(new Error('recovery-fail'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECOVERY_DELAY_FLOOR_MS);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterSecondError + 1));

    second.unmount();
    queryClient.clear();
  });

  it('BR-03: cancel between floor-fire and cooldown-callback does not consume latch', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T12:00:00.000Z'));
    // Cooldown longer than floor so runAfterCooldown defers past the outer timer.
    openCooldown(DEFAULT_COOLDOWN_SECONDS + 30);

    const { wrapper, queryClient } = createWrapper();
    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    fetchMediaIdentitiesMock.mockRejectedValue(new Error('timeout'));

    const { result, rerender, unmount } = renderHook(
      ({ enabled }: { enabled: boolean }) => useMediaIdentities([55], enabled),
      { wrapper, initialProps: { enabled: true } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const afterFirstError = fetchMediaIdentitiesMock.mock.calls.length;
    expect(afterFirstError).toBe(1);

    // Floor fires → schedules runAfterCooldown; latch must not stick if we cancel before it runs.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECOVERY_DELAY_FLOOR_MS);
    });

    // Effect cleanup via enabled flip (same mounted hook / same refs).
    rerender({ enabled: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Expire the deferred cooldown callback from the cancelled schedule — no refetch.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterFirstError);

    // Re-enable on same key: a later error episode must be able to arm recovery again.
    _resetCooldownForTests();
    fetchMediaIdentitiesMock.mockRejectedValue(new Error('timeout-again'));
    rerender({ enabled: true });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const afterReenable = fetchMediaIdentitiesMock.mock.calls.length;

    fetchMediaIdentitiesMock.mockRejectedValueOnce(new Error('recovery-fail'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECOVERY_DELAY_FLOOR_MS);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() =>
      expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterReenable + 1),
    );

    unmount();
    queryClient.clear();
  });

  it('BR-04: single-instance latch reset — error → recovery → success → error arms again', async () => {
    vi.useFakeTimers();
    const { wrapper, queryClient } = createWrapper();
    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    fetchMediaIdentitiesMock.mockRejectedValue(new Error('timeout'));

    const { result, unmount } = renderHook(() => useMediaIdentities([77], true), { wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const afterFirstError = fetchMediaIdentitiesMock.mock.calls.length;
    expect(afterFirstError).toBe(1);

    // First recovery consumes the episode (still fails).
    fetchMediaIdentitiesMock.mockRejectedValueOnce(new Error('recovery-fail'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECOVERY_DELAY_FLOOR_MS);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() =>
      expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterFirstError + 1),
    );

    // Success on the same mounted hook resets the latch.
    fetchMediaIdentitiesMock.mockResolvedValueOnce({
      identities_by_media: {},
      data_source: 'local_projection',
    });
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // Subsequent error on the same instance must arm a second recovery.
    fetchMediaIdentitiesMock.mockRejectedValue(new Error('timeout-2'));
    await act(async () => {
      await result.current.refetch();
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const afterSecondError = fetchMediaIdentitiesMock.mock.calls.length;

    fetchMediaIdentitiesMock.mockRejectedValueOnce(new Error('recovery-fail-2'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECOVERY_DELAY_FLOOR_MS);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await waitFor(() =>
      expect(fetchMediaIdentitiesMock.mock.calls.length).toBe(afterSecondError + 1),
    );

    unmount();
    queryClient.clear();
  });
});
