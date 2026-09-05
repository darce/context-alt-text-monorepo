import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../api/recognition';
import { useClusterActionMutations } from '../../pages/workbench/identity-clusters/useClusterActionMutations';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string) => text,
}));

vi.mock('../../api/recognition', () => {
  return {
    acceptSuggestion: vi.fn(),
    createClusterForIdentity: vi.fn(),
    fetchScanStatus: vi.fn(),
    pinRepresentative: vi.fn(),
    reassignClusterIdentity: vi.fn(),
    rejectSuggestion: vi.fn(),
    splitCluster: vi.fn(),
  };
});

vi.mock('../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

describe('useClusterActionMutations split cancellation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('settles an aborted split before its replacement completes without stale callbacks', async () => {
    const splitSignals: AbortSignal[] = [];
    vi.mocked(recognitionApi.splitCluster)
      .mockImplementationOnce((_clusterId, _request, signal) => {
        if (!signal) {
          throw new Error('expected split signal');
        }
        splitSignals.push(signal);
        return new Promise<never>((_resolve, reject) => {
          signal.addEventListener(
            'abort',
            () => reject(new DOMException('The split was superseded.', 'AbortError')),
            { once: true },
          );
        });
      })
      .mockImplementationOnce((_clusterId, _request, signal) => {
        if (!signal) {
          throw new Error('expected replacement split signal');
        }
        splitSignals.push(signal);
        return Promise.resolve({
          new_cluster_ids: ['replacement-cluster'],
          moved_counts: [2],
          new_cluster_id: 'replacement-cluster',
          moved_count: 2,
        });
      });
    const onError = vi.fn();
    const onAbort = vi.fn();
    const invalidateQueries = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useClusterActionMutations({
          clusterId: 'c1',
          onError,
          onAbort,
          invalidateQueries,
        }),
      { wrapper },
    );

    act(() => result.current.split('c1', 2));
    await waitFor(() => expect(splitSignals).toHaveLength(1));

    act(() => result.current.split('c1', 3));
    await waitFor(() => expect(splitSignals).toHaveLength(2));
    await waitFor(() => expect(result.current.isSplitting).toBe(false));

    expect(splitSignals[0].aborted).toBe(true);
    expect(splitSignals[1].aborted).toBe(false);
    expect(onError).not.toHaveBeenCalled();
    expect(onAbort).not.toHaveBeenCalled();
    expect(invalidateQueries).toHaveBeenCalledTimes(1);
  });

  it('settles an unmounted split abort without post-unmount callbacks', async () => {
    let splitSignal: AbortSignal | undefined;
    let markAbortSettled: (() => void) | undefined;
    const abortSettled = new Promise<void>((resolve) => {
      markAbortSettled = resolve;
    });
    vi.mocked(recognitionApi.splitCluster).mockImplementation((_clusterId, _request, signal) => {
      splitSignal = signal;
      return new Promise<never>((_resolve, reject) => {
        signal?.addEventListener(
          'abort',
          () => {
            reject(new DOMException('The split owner unmounted.', 'AbortError'));
            markAbortSettled?.();
          },
          { once: true },
        );
      });
    });
    const onError = vi.fn();
    const onAbort = vi.fn();
    const invalidateQueries = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(
      () =>
        useClusterActionMutations({
          clusterId: 'c1',
          onError,
          onAbort,
          invalidateQueries,
        }),
      { wrapper },
    );

    result.current.split('c1', 2);
    await waitFor(() => expect(recognitionApi.splitCluster).toHaveBeenCalledTimes(1));
    expect(splitSignal).toBeDefined();
    expect(splitSignal?.aborted).toBe(false);

    unmount();
    await abortSettled;
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(splitSignal?.aborted).toBe(true);
    expect(onError).not.toHaveBeenCalled();
    expect(onAbort).not.toHaveBeenCalled();
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  // TEST-15 (heuristics-canon-research/lexicons/engineering.md:396): assert
  // settled mutation state, not only that a signal flipped while a promise was
  // left pending. RES-13 (:124): the containment path includes async job polling.
  it('settles a superseded async poll while its replacement completes', async () => {
    vi.mocked(recognitionApi.splitCluster).mockImplementation((clusterId) =>
      Promise.resolve({ job_id: `job-${clusterId}`, status: 'pending', message: 'queued' }),
    );
    vi.mocked(recognitionApi.fetchScanStatus).mockImplementation((jobId) => {
      if (jobId === 'job-c1') {
        return new Promise<never>(() => undefined);
      }
      return Promise.resolve({
        id: jobId,
        type: 'split',
        status: 'completed',
        progress: null,
        started_at: '2026-09-05T00:00:00.000Z',
        finished_at: '2026-09-05T00:00:01.000Z',
      });
    });
    const onError = vi.fn();
    const onAbort = vi.fn();
    const invalidateQueries = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useClusterActionMutations({
          clusterId: 'c1',
          identityCount: 100,
          onError,
          onAbort,
          invalidateQueries,
        }),
      { wrapper },
    );

    act(() => result.current.split('c1', 2));
    await waitFor(() => expect(recognitionApi.fetchScanStatus).toHaveBeenCalledWith('job-c1'));

    act(() => result.current.split('c2', 2));
    await waitFor(() => expect(recognitionApi.fetchScanStatus).toHaveBeenCalledWith('job-c2'));
    await waitFor(() => expect(result.current.isSplitting).toBe(false));
    await waitFor(() =>
      expect(queryClient.getMutationCache().getAll().every((mutation) => mutation.state.status !== 'pending')).toBe(
        true,
      ),
    );

    expect(onError).not.toHaveBeenCalled();
    expect(onAbort).not.toHaveBeenCalled();
    expect(invalidateQueries).toHaveBeenCalledTimes(1);
  });

  it('cancels the async poll delay when a split is superseded', async () => {
    vi.mocked(recognitionApi.splitCluster).mockImplementation((clusterId) =>
      Promise.resolve({ job_id: `job-${clusterId}`, status: 'pending', message: 'queued' }),
    );
    vi.mocked(recognitionApi.fetchScanStatus).mockImplementation((jobId) =>
      Promise.resolve({
        id: jobId,
        type: 'split',
        status: jobId === 'job-c1' ? 'running' : 'completed',
        progress: null,
        started_at: '2026-09-05T00:00:00.000Z',
        finished_at: jobId === 'job-c1' ? null : '2026-09-05T00:00:01.000Z',
      }),
    );
    const onError = vi.fn();
    const onAbort = vi.fn();
    const invalidateQueries = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useClusterActionMutations({
          clusterId: 'c1',
          identityCount: 100,
          onError,
          onAbort,
          invalidateQueries,
        }),
      { wrapper },
    );

    act(() => result.current.split('c1', 2));
    await waitFor(() => expect(recognitionApi.fetchScanStatus).toHaveBeenCalledWith('job-c1'));
    await Promise.resolve();

    act(() => result.current.split('c2', 2));
    await waitFor(() => expect(result.current.isSplitting).toBe(false));
    await waitFor(() =>
      expect(queryClient.getMutationCache().getAll().every((mutation) => mutation.state.status !== 'pending')).toBe(
        true,
      ),
    );

    expect(onError).not.toHaveBeenCalled();
    expect(onAbort).not.toHaveBeenCalled();
    expect(invalidateQueries).toHaveBeenCalledTimes(1);
  });
});
