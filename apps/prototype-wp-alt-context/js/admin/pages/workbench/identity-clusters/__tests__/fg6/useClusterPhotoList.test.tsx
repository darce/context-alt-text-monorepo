import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { listRecognitionClusterPage } from '../../../../../api/recognition/clusterApiQueries';
import { useClusterPhotoList } from '../../hooks/useClusterPhotoList';

vi.mock('../../../../../api/recognition/clusterApiQueries', () => ({ listRecognitionClusterPage: vi.fn() }));
const fetchPage = vi.mocked(listRecognitionClusterPage);
const page = {
  clusters: [
    {
      id: 'local',
      label: 'Ada',
      identity_count: 10,
      photo_count: 2,
      member_ids: [],
      sample_identities: [],
      representative_identity: { media_id: null, bbox: { x: 0, y: 0, width: 0, height: 0 } },
      person_uuid: 'wp-person',
    },
  ],
  limit: 2,
  total: null,
  truncated: true,
};
const clients: QueryClient[] = [];
const wrapper = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(client);
  return {
    client,
    Wrapper: ({ children }: React.PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
};
afterEach(() => {
  clients.forEach((c) => c.clear());
  clients.length = 0;
  vi.resetAllMocks();
});

describe('photo listing filter before producer pagination', () => {
  it('defaults to All, keys minimum and resets offset in the same transition', async () => {
    fetchPage.mockResolvedValue(page);
    const { Wrapper, client } = wrapper();
    const { result } = renderHook(() => useClusterPhotoList({ limit: 2 }), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.query.isSuccess).toBe(true));
    expect(fetchPage.mock.calls[0][0]).toEqual({ limit: 2, offset: 0 });
    expect(result.current.hasNextPage).toBe(true);
    act(() => result.current.nextPage());
    await waitFor(() => expect(fetchPage).toHaveBeenCalledWith({ limit: 2, offset: 2 }, expect.any(AbortSignal)));
    act(() => result.current.setMinimumPhotos(3));
    await waitFor(() =>
      expect(fetchPage).toHaveBeenCalledWith({ limit: 2, offset: 0, min_photos: 3 }, expect.any(AbortSignal)),
    );
    expect(fetchPage.mock.calls.some(([p]) => p?.offset === 2 && p.min_photos === 3)).toBe(false);
    expect(
      client
        .getQueryCache()
        .findAll()
        .some((q) => JSON.stringify(q.queryKey).includes('min_photos')),
    ).toBe(true);
    expect(result.current.query.data?.clusters[0].person_uuid).toBe('wp-person');
    // A producer response is displayed whole; never filter a fetched page by count.
    expect(result.current.query.data?.clusters).toHaveLength(1);
    act(() => result.current.setMinimumPhotos(undefined));
    await waitFor(() => expect(result.current.minimumPhotos).toBeUndefined());
    expect(result.current.offset).toBe(0);
  });
  it('uses truncated, including an unknown total and empty nonzero page', async () => {
    fetchPage.mockResolvedValueOnce(page).mockResolvedValue({ clusters: [], limit: 2, total: null, truncated: false });
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useClusterPhotoList({ limit: 2 }), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    act(() => result.current.nextPage());
    await waitFor(() => expect(result.current.query.data?.clusters).toEqual([]));
    expect(result.current.hasNextPage).toBe(false);
    expect(result.current.offset).toBe(2);
  });
  it('resets pagination when search changes, including a return to an earlier search', async () => {
    fetchPage.mockResolvedValue(page);
    const { Wrapper } = wrapper();
    const { result, rerender } = renderHook(({ search }) => useClusterPhotoList({ limit: 2, search }), {
      wrapper: Wrapper,
      initialProps: { search: 'Ada' },
    });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    act(() => result.current.nextPage());
    await waitFor(() => expect(result.current.offset).toBe(2));
    rerender({ search: 'Grace' });
    await waitFor(() =>
      expect(fetchPage).toHaveBeenCalledWith({ limit: 2, offset: 0, search: 'Grace' }, expect.any(AbortSignal)),
    );
    rerender({ search: 'Ada' });
    expect(result.current.offset).toBe(0);
  });
  it('exposes failure without calling it an empty filtered result', async () => {
    fetchPage.mockRejectedValue(new Error('producer unavailable'));
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useClusterPhotoList(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.query.isError).toBe(true));
    expect(result.current.query.data).toBeUndefined();
    expect(result.current.hasNextPage).toBe(false);
  });
});
