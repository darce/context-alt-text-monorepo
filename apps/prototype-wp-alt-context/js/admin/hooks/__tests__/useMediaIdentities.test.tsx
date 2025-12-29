import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useMediaIdentities } from '../useMediaIdentities';
import * as recognitionApi from '../../api/recognition';

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
  });

  it('fetches identities when enabled and media IDs exist', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    const identitiesDeferred = createDeferred<{ identities_by_media: Record<string, unknown> }>();
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
});
