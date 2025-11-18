import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useMediaIdentities } from '../useMediaIdentities';
import * as recognitionApi from '../../api/recognitionApi';

vi.mock('../../api/recognitionApi', () => ({
  fetchMediaIdentities: vi.fn(),
}));

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
  });

  it('fetches identities when enabled and media IDs exist', async () => {
    const { wrapper, queryClient } = createWrapper();
    (recognitionApi.fetchMediaIdentities as vi.Mock).mockResolvedValue({ identities_by_media: {} });

    const { result } = renderHook(() => useMediaIdentities([1, 2], true), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(recognitionApi.fetchMediaIdentities).toHaveBeenCalledWith([1, 2]);

    queryClient.clear();
  });

  it('does not issue a fetch when disabled or when IDs are empty', async () => {
    const { wrapper, queryClient } = createWrapper();

    renderHook(() => useMediaIdentities([], true), { wrapper });
    renderHook(() => useMediaIdentities([3], false), { wrapper });

    await waitFor(() => expect(recognitionApi.fetchMediaIdentities).not.toHaveBeenCalled());

    queryClient.clear();
  });
});
