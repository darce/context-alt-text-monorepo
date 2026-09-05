import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
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

  it('threads a live AbortSignal to splitCluster and aborts it on unmount', async () => {
    let splitSignal: AbortSignal | undefined;
    vi.mocked(recognitionApi.splitCluster).mockImplementation((_clusterId, _request, signal) => {
      splitSignal = signal;
      return new Promise<never>(() => undefined);
    });
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result, unmount } = renderHook(
      () =>
        useClusterActionMutations({
          clusterId: 'c1',
          invalidateQueries: vi.fn(),
        }),
      { wrapper },
    );

    result.current.split('c1', 2);
    await waitFor(() => expect(recognitionApi.splitCluster).toHaveBeenCalledTimes(1));
    expect(splitSignal).toBeDefined();
    expect(splitSignal?.aborted).toBe(false);

    unmount();

    expect(splitSignal?.aborted).toBe(true);
  });

  // TEST-15 (heuristics-canon-research/lexicons/engineering.md:396): observe the
  // transport seam so removing the replacement abort makes this test go red.
  // RES-13 (heuristics-canon-research/lexicons/engineering.md:124): exercise the
  // failure/containment path of this external write, not only its happy path.
  it('aborts an in-flight split before starting its replacement', async () => {
    const splitSignals: AbortSignal[] = [];
    vi.mocked(recognitionApi.splitCluster).mockImplementation((_clusterId, _request, signal) => {
      if (signal) {
        splitSignals.push(signal);
      }
      return new Promise<never>(() => undefined);
    });
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useClusterActionMutations({
          clusterId: 'c1',
          invalidateQueries: vi.fn(),
        }),
      { wrapper },
    );

    result.current.split('c1', 2);
    await waitFor(() => expect(splitSignals).toHaveLength(1));
    expect(splitSignals[0].aborted).toBe(false);

    result.current.split('c1', 3);
    await waitFor(() => expect(splitSignals).toHaveLength(2));

    expect(splitSignals[0].aborted).toBe(true);
    expect(splitSignals[1].aborted).toBe(false);
  });
});
