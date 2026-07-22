import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fetchWorkbenchMedia,
  fetchWorkbenchMediaDetail,
  type WorkbenchMediaDetailResponse,
  type WorkbenchMediaResponse,
} from '../../api/workbenchMediaApi';
import { useWorkbenchMedia } from '../useWorkbenchMedia';
import * as recognitionApi from '../../api/recognition';

vi.mock('../../api/workbenchMediaApi', () => ({
  fetchWorkbenchMedia: vi.fn(),
  fetchWorkbenchMediaDetail: vi.fn(),
}));

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

describe('useWorkbenchMedia', () => {
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

  it('merges fetched identities into each media item', async () => {
    const { wrapper, queryClient } = createWrapper();
    const mediaResponse: WorkbenchMediaResponse = {
      items: [
        {
          id: 11,
          title: 'Item A',
          altText: null,
          status: 'missing',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
          updatedAt: '2025-01-01T00:00:00Z',
          dimensions: { width: 1200, height: 800 },
          tags: [],
        },
        {
          id: 12,
          title: 'Item B',
          altText: 'Alt',
          status: 'missing',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
          updatedAt: '2025-01-02T00:00:00Z',
          dimensions: { width: 640, height: 480 },
          tags: [],
        },
      ],
      total: 2,
      totalPages: 1,
    };

    const fetchWorkbenchMediaMock = vi.mocked(fetchWorkbenchMedia);
    const fetchMediaDeferred = createDeferred<WorkbenchMediaResponse>();
    fetchWorkbenchMediaMock.mockReturnValue(fetchMediaDeferred.promise);

    const fetchWorkbenchMediaDetailMock = vi.mocked(fetchWorkbenchMediaDetail);
    const fetchDetailDeferred = createDeferred<WorkbenchMediaDetailResponse>();
    fetchWorkbenchMediaDetailMock.mockReturnValue(fetchDetailDeferred.promise);

    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    const identitiesDeferred = createDeferred<recognitionApi.MediaIdentitiesResponse>();
    fetchMediaIdentitiesMock.mockReturnValue(identitiesDeferred.promise);

    const { result } = renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: true }), { wrapper });

    await waitFor(() => {
      expect(fetchWorkbenchMediaMock).toHaveBeenCalledWith({ page: 1, perPage: 10, search: undefined, status: 'all' });
    });

    await act(async () => {
      fetchMediaDeferred.resolve(mediaResponse);
      await fetchMediaDeferred.promise;
    });

    await waitFor(() => expect(fetchMediaIdentitiesMock).toHaveBeenCalledWith([11, 12]));
    await waitFor(() => expect(fetchWorkbenchMediaDetailMock).toHaveBeenCalledWith([11, 12]));

    await act(async () => {
      fetchDetailDeferred.resolve({
        detailsByMedia: {
          '11': {
            id: 11,
            mimeType: 'image/jpeg',
            updatedAt: '2025-01-01T00:00:00Z',
            dimensions: { width: 1200, height: 800 },
            xmpPersistence: null,
          },
          '12': {
            id: 12,
            mimeType: 'image/png',
            updatedAt: '2025-01-02T00:00:00Z',
            dimensions: { width: 640, height: 480 },
            xmpPersistence: null,
          },
        },
        limit: 100,
        total: 2,
        truncated: false,
      });
      await fetchDetailDeferred.promise;
    });

    await act(async () => {
      identitiesDeferred.resolve({
        identities_by_media: {
          '11': [
            {
              identity_id: 'face-1',
              media_id: 11,
              cluster_id: 'cluster-1',
              cluster_label: 'Riley',
              is_auto_label: false,
              bbox: { x: 0, y: 0, width: 10, height: 10 },
              confidence: 0.9,
              similarity: 0.85,
            },
          ],
          '12': [],
        },
      });
      await identitiesDeferred.promise;
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const merged = result.current.itemsWithIdentities;
    expect(merged).toHaveLength(2);
    expect(merged?.[0].mimeType).toBe('image/jpeg');
    expect(merged?.[1].dimensions).toEqual({ width: 640, height: 480 });
    expect(merged?.[0].identities).toHaveLength(1);
    expect(merged?.[1].identities).toEqual([]);

    queryClient.clear();
  });

  it('skips fetching when disabled', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchWorkbenchMediaMock = vi.mocked(fetchWorkbenchMedia);
    const fetchWorkbenchMediaDetailMock = vi.mocked(fetchWorkbenchMediaDetail);

    renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: false }), { wrapper });

    await waitFor(() => {
      expect(fetchWorkbenchMediaMock).not.toHaveBeenCalled();
      expect(fetchWorkbenchMediaDetailMock).not.toHaveBeenCalled();
      expect(recognitionApi.fetchMediaIdentities).not.toHaveBeenCalled();
    });

    queryClient.clear();
  });

  it('exposes isPlaceholderData and isFetching on identitiesSurface (Slice 3 contract)', async () => {
    const { wrapper, queryClient } = createWrapper();
    const mediaResponse: WorkbenchMediaResponse = {
      items: [
        {
          id: 21,
          title: 'Item',
          altText: null,
          status: 'missing',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
          updatedAt: '2025-01-01T00:00:00Z',
          dimensions: { width: 100, height: 100 },
          tags: [],
        },
      ],
      total: 1,
      totalPages: 1,
    };

    vi.mocked(fetchWorkbenchMedia).mockResolvedValue(mediaResponse);
    vi.mocked(fetchWorkbenchMediaDetail).mockResolvedValue({
      detailsByMedia: {},
      limit: 100,
      total: 1,
      truncated: false,
    });
    vi.mocked(recognitionApi.fetchMediaIdentities).mockResolvedValue({
      identities_by_media: {
        '21': [
          {
            identity_id: 'face-z',
            media_id: 21,
            cluster_id: 'c-z',
            cluster_label: 'Zed',
            is_auto_label: false,
            bbox: { x: 0, y: 0, width: 1, height: 1 },
            confidence: 0.5,
            similarity: 0.5,
          },
        ],
      },
      data_source: 'local_projection',
    } as recognitionApi.MediaIdentitiesResponse);

    const { result } = renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: true }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.identitiesQuery.isLoading).toBe(false));

    expect(result.current.identitiesQuery).toEqual(
      expect.objectContaining({
        isPlaceholderData: expect.any(Boolean),
        isFetching: expect.any(Boolean),
        isError: false,
        data: expect.objectContaining({ identities_by_media: expect.any(Object) }),
      }),
    );

    queryClient.clear();
  });

  it('S3-T3: failed refetch on the same key retains previously merged labels', async () => {
    const { wrapper, queryClient } = createWrapper();
    const mediaResponse: WorkbenchMediaResponse = {
      items: [
        {
          id: 31,
          title: 'Cached',
          altText: null,
          status: 'missing',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
          updatedAt: '2025-01-01T00:00:00Z',
          dimensions: { width: 100, height: 100 },
          tags: [],
        },
      ],
      total: 1,
      totalPages: 1,
    };

    vi.mocked(fetchWorkbenchMedia).mockResolvedValue(mediaResponse);
    vi.mocked(fetchWorkbenchMediaDetail).mockResolvedValue({
      detailsByMedia: {},
      limit: 100,
      total: 1,
      truncated: false,
    });
    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    fetchMediaIdentitiesMock.mockResolvedValueOnce({
      identities_by_media: {
        '31': [
          {
            identity_id: 'face-r',
            media_id: 31,
            cluster_id: 'c-r',
            cluster_label: 'Riley',
            is_auto_label: false,
            bbox: { x: 0, y: 0, width: 1, height: 1 },
            confidence: 0.9,
            similarity: 0.9,
          },
        ],
      },
      data_source: 'local_projection',
    } as recognitionApi.MediaIdentitiesResponse);

    const { result } = renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: true }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.itemsWithIdentities?.[0]?.identities?.[0]?.cluster_label).toBe('Riley'));

    fetchMediaIdentitiesMock.mockRejectedValueOnce(new Error('refetch timeout'));
    await act(async () => {
      await result.current.identitiesQuery.refetch();
    });

    await waitFor(() => expect(result.current.identitiesQuery.isError).toBe(true));
    // Same-key cache retained — labels stay on the merged row.
    expect(result.current.itemsWithIdentities?.[0]?.identities?.[0]?.cluster_label).toBe('Riley');
    expect(result.current.identitiesQuery.data?.identities_by_media?.['31']?.[0]?.cluster_label).toBe('Riley');

    queryClient.clear();
  });

  it('S3-T4: placeholder rows never coexist with error; error drops placeholder (cell 3→1)', async () => {
    const { wrapper, queryClient } = createWrapper();
    const page1: WorkbenchMediaResponse = {
      items: [
        {
          id: 41,
          title: 'Page1',
          altText: null,
          status: 'missing',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
          updatedAt: '2025-01-01T00:00:00Z',
          dimensions: { width: 100, height: 100 },
          tags: [],
        },
      ],
      total: 2,
      totalPages: 2,
    };
    const page2: WorkbenchMediaResponse = {
      items: [
        {
          id: 42,
          title: 'Page2',
          altText: null,
          status: 'missing',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
          updatedAt: '2025-01-02T00:00:00Z',
          dimensions: { width: 100, height: 100 },
          tags: [],
        },
      ],
      total: 2,
      totalPages: 2,
    };

    const fetchWorkbenchMediaMock = vi.mocked(fetchWorkbenchMedia);
    fetchWorkbenchMediaMock.mockImplementation(async ({ page }) => (page === 1 ? page1 : page2));
    vi.mocked(fetchWorkbenchMediaDetail).mockResolvedValue({
      detailsByMedia: {},
      limit: 100,
      total: 1,
      truncated: false,
    });

    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    const page2Deferred = createDeferred<recognitionApi.MediaIdentitiesResponse>();
    fetchMediaIdentitiesMock.mockImplementation(async (ids) => {
      if (ids[0] === 41) {
        return {
          identities_by_media: {
            '41': [
              {
                identity_id: 'face-a',
                media_id: 41,
                cluster_id: 'c-a',
                cluster_label: 'Alex',
                is_auto_label: false,
                bbox: { x: 0, y: 0, width: 1, height: 1 },
                confidence: 0.8,
                similarity: 0.8,
              },
            ],
          },
          data_source: 'local_projection',
        } as recognitionApi.MediaIdentitiesResponse;
      }
      return page2Deferred.promise;
    });

    const { result, rerender } = renderHook(
      ({ page }: { page: number }) => useWorkbenchMedia({ page, perPage: 10, enabled: true }),
      { wrapper, initialProps: { page: 1 } },
    );

    await waitFor(() => expect(result.current.itemsWithIdentities?.[0]?.identities?.[0]?.cluster_label).toBe('Alex'));

    rerender({ page: 2 });

    // While page-2 identities are pending, placeholder may hold page-1 data — never with isError.
    await waitFor(() => expect(result.current.data?.items[0]?.id).toBe(42));
    await waitFor(() => {
      const surface = result.current.identitiesQuery;
      if (surface.isFetching && surface.isPlaceholderData) {
        expect(surface.isError).toBe(false);
      }
    });

    await act(async () => {
      page2Deferred.reject(new Error('page2 identities failed'));
      await page2Deferred.promise.catch(() => undefined);
    });

    await waitFor(() => expect(result.current.identitiesQuery.isError).toBe(true));
    // Error path drops placeholder (RQ): no placeholder+error coexistence; cell 1 takes over.
    expect(result.current.identitiesQuery.isPlaceholderData).toBe(false);
    expect(result.current.identitiesQuery.data).toBeUndefined();

    queryClient.clear();
  });
});
