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
});
