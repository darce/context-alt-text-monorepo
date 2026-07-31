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
import { DATA_SOURCE } from '../../api/recognition/types';
import { deriveIdentitiesPresentationSource } from '../../pages/workbench/deriveIdentitiesPresentationSource';
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
          isDecorative: false,
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
          isDecorative: false,
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
          isDecorative: false,
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
    await waitFor(() => {
      expect(result.current.identitiesQuery.isFetching).toBe(false);
      expect(result.current.identitiesQuery.isPlaceholderData).toBe(false);
    });

    // Post-settle contract: concrete settled flags (not expect.any(Boolean)).
    expect(result.current.identitiesQuery.isFetching).toBe(false);
    expect(result.current.identitiesQuery.isPlaceholderData).toBe(false);
    expect(result.current.identitiesQuery.isError).toBe(false);
    expect(result.current.identitiesQuery.data).toEqual(
      expect.objectContaining({ identities_by_media: expect.any(Object) }),
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
          isDecorative: false,
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
          isDecorative: false,
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
          isDecorative: false,
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

    // While page-2 identities are pending, must observe placeholder hold + fetch in flight.
    await waitFor(() => expect(result.current.data?.items[0]?.id).toBe(42));
    await waitFor(() => {
      const surface = result.current.identitiesQuery;
      expect(surface.isPlaceholderData && surface.isFetching).toBe(true);
    });
    // In that observed state: never coexists with isError; presentation keeps prior envelope.
    expect(result.current.identitiesQuery.isError).toBe(false);
    expect(result.current.identitiesQuery.isPlaceholderData).toBe(true);
    expect(result.current.identitiesQuery.isFetching).toBe(true);
    expect(
      deriveIdentitiesPresentationSource(
        result.current.identitiesQuery.isError,
        result.current.identitiesQuery.data,
      ),
    ).toBe(DATA_SOURCE.LOCAL_PROJECTION);

    await act(async () => {
      page2Deferred.reject(new Error('page2 identities failed'));
      await page2Deferred.promise.catch(() => undefined);
    });

    await waitFor(() => expect(result.current.identitiesQuery.isError).toBe(true));
    // Error path drops placeholder (RQ): no placeholder+error coexistence; cell 1 takes over.
    expect(result.current.identitiesQuery.isPlaceholderData).toBe(false);
    expect(result.current.identitiesQuery.data).toBeUndefined();
    expect(
      deriveIdentitiesPresentationSource(
        result.current.identitiesQuery.isError,
        result.current.identitiesQuery.data,
      ),
    ).toBe(DATA_SOURCE.UNAVAILABLE);

    queryClient.clear();
  });

  const pageMediaItem = (id: number, title: string): WorkbenchMediaResponse['items'][number] => ({
    id,
    title,
    altText: null,
    isDecorative: false,
    status: 'missing',
    thumbnailUrl: null,
    mimeType: 'image/jpeg',
    editUrl: '#',
    updatedAt: '2025-01-01T00:00:00Z',
    dimensions: { width: 100, height: 100 },
    tags: [],
  });

  const emptyDetail = (): WorkbenchMediaDetailResponse => ({
    detailsByMedia: {},
    limit: 100,
    total: 0,
    truncated: false,
  });

  const emptyIdentities = (): recognitionApi.MediaIdentitiesResponse =>
    ({
      identities_by_media: {},
      data_source: 'local_projection',
    }) as recognitionApi.MediaIdentitiesResponse;

  it('S4-T1: no speculative next-page prefetch while stage-2 isFetching; exactly one after settle', async () => {
    const { wrapper, queryClient } = createWrapper();
    const page1: WorkbenchMediaResponse = {
      items: [pageMediaItem(101, 'P1')],
      total: 3,
      totalPages: 3,
    };
    const page2: WorkbenchMediaResponse = {
      items: [pageMediaItem(102, 'P2')],
      total: 3,
      totalPages: 3,
    };

    const fetchWorkbenchMediaMock = vi.mocked(fetchWorkbenchMedia);
    fetchWorkbenchMediaMock.mockImplementation(async ({ page }) => (page === 1 ? page1 : page2));

    const detailDeferred = createDeferred<WorkbenchMediaDetailResponse>();
    const identitiesDeferred = createDeferred<recognitionApi.MediaIdentitiesResponse>();
    vi.mocked(fetchWorkbenchMediaDetail).mockReturnValue(detailDeferred.promise);
    vi.mocked(recognitionApi.fetchMediaIdentities).mockReturnValue(identitiesDeferred.promise);

    const { result } = renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: true }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.detailQuery.isFetching).toBe(true));
    await waitFor(() => expect(result.current.identitiesQuery.isFetching).toBe(true));

    // While stage-2 in flight: only page-1 media fetch — zero page-2 prefetch.
    expect(
      fetchWorkbenchMediaMock.mock.calls.filter((call) => call[0].page === 2),
    ).toHaveLength(0);

    await act(async () => {
      detailDeferred.resolve(emptyDetail());
      await detailDeferred.promise;
    });
    // One stage-2 leg settled, other still in flight — still no prefetch.
    expect(
      fetchWorkbenchMediaMock.mock.calls.filter((call) => call[0].page === 2),
    ).toHaveLength(0);

    await act(async () => {
      identitiesDeferred.resolve(emptyIdentities());
      await identitiesDeferred.promise;
    });

    await waitFor(() => expect(result.current.detailQuery.isFetching).toBe(false));
    await waitFor(() => expect(result.current.identitiesQuery.isFetching).toBe(false));

    await waitFor(() => {
      expect(
        fetchWorkbenchMediaMock.mock.calls.filter((call) => call[0].page === 2),
      ).toHaveLength(1);
    });

    queryClient.clear();
  });

  it('S4-T2: page-change with placeholder held + stage-2 in flight → no N+2 prefetch until isFetching clears', async () => {
    const { wrapper, queryClient } = createWrapper();
    const page1: WorkbenchMediaResponse = {
      items: [pageMediaItem(201, 'P1')],
      total: 3,
      totalPages: 3,
    };
    const page2: WorkbenchMediaResponse = {
      items: [pageMediaItem(202, 'P2')],
      total: 3,
      totalPages: 3,
    };
    const page3: WorkbenchMediaResponse = {
      items: [pageMediaItem(203, 'P3')],
      total: 3,
      totalPages: 3,
    };

    const fetchWorkbenchMediaMock = vi.mocked(fetchWorkbenchMedia);
    fetchWorkbenchMediaMock.mockImplementation(async ({ page }) => {
      if (page === 1) return page1;
      if (page === 2) return page2;
      return page3;
    });

    // Page-1 stage-2 settles immediately so initial prefetch of page 2 can fire.
    const detailByIds = new Map<string, ReturnType<typeof createDeferred<WorkbenchMediaDetailResponse>>>();
    const identitiesByIds = new Map<
      string,
      ReturnType<typeof createDeferred<recognitionApi.MediaIdentitiesResponse>>
    >();

    vi.mocked(fetchWorkbenchMediaDetail).mockImplementation(async (ids) => {
      const key = ids.join(',');
      if (key === '201') {
        return emptyDetail();
      }
      const deferred = detailByIds.get(key) ?? createDeferred<WorkbenchMediaDetailResponse>();
      detailByIds.set(key, deferred);
      return deferred.promise;
    });
    vi.mocked(recognitionApi.fetchMediaIdentities).mockImplementation(async (ids) => {
      const key = ids.join(',');
      if (key === '201') {
        return emptyIdentities();
      }
      const deferred =
        identitiesByIds.get(key) ?? createDeferred<recognitionApi.MediaIdentitiesResponse>();
      identitiesByIds.set(key, deferred);
      return deferred.promise;
    });

    const { result, rerender } = renderHook(
      ({ page }: { page: number }) => useWorkbenchMedia({ page, perPage: 10, enabled: true }),
      { wrapper, initialProps: { page: 1 } },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.detailQuery.isFetching).toBe(false));
    await waitFor(() => expect(result.current.identitiesQuery.isFetching).toBe(false));
    // Page-1 settle may prefetch page 2.
    await waitFor(() => {
      expect(
        fetchWorkbenchMediaMock.mock.calls.filter((call) => call[0].page === 2).length,
      ).toBeGreaterThanOrEqual(1);
    });

    const page3CallsBefore = fetchWorkbenchMediaMock.mock.calls.filter(
      (call) => call[0].page === 3,
    ).length;

    rerender({ page: 2 });

    // Page 2 media may come from cache (prefetch) → status success under placeholder for stage-2
    // while page-2 detail/identities are still in flight. Status-level gate would prefetch page 3 now.
    await waitFor(() => expect(result.current.data?.items[0]?.id).toBe(202));
    await waitFor(() => {
      // Stage-2 for page-2 ids still fetching (deferred).
      expect(result.current.detailQuery.isFetching || result.current.identitiesQuery.isFetching).toBe(
        true,
      );
    });

    expect(
      fetchWorkbenchMediaMock.mock.calls.filter((call) => call[0].page === 3),
    ).toHaveLength(page3CallsBefore);

    // Resolve page-2 stage-2.
    await act(async () => {
      const detailDef = detailByIds.get('202');
      const idDef = identitiesByIds.get('202');
      detailDef?.resolve(emptyDetail());
      idDef?.resolve(emptyIdentities());
      await Promise.all([detailDef?.promise, idDef?.promise]);
    });

    await waitFor(() => expect(result.current.detailQuery.isFetching).toBe(false));
    await waitFor(() => expect(result.current.identitiesQuery.isFetching).toBe(false));

    // Discriminating pin: exactly one page-3 prefetch after fetch-level settle (BR-07).
    await waitFor(() => {
      expect(
        fetchWorkbenchMediaMock.mock.calls.filter((call) => call[0].page === 3),
      ).toHaveLength(1);
    });

    queryClient.clear();
  });

  it('S4-T3: after settle, effect re-runs (identities isFetching flip) do not issue additional page N+1 fetches', async () => {
    const { wrapper, queryClient } = createWrapper();
    const page1: WorkbenchMediaResponse = {
      items: [pageMediaItem(301, 'P1')],
      total: 2,
      totalPages: 2,
    };
    const page2: WorkbenchMediaResponse = {
      items: [pageMediaItem(302, 'P2')],
      total: 2,
      totalPages: 2,
    };

    const fetchWorkbenchMediaMock = vi.mocked(fetchWorkbenchMedia);
    fetchWorkbenchMediaMock.mockImplementation(async ({ page }) => (page === 1 ? page1 : page2));
    vi.mocked(fetchWorkbenchMediaDetail).mockResolvedValue(emptyDetail());

    let identitiesCalls = 0;
    const identitiesDeferreds: Array<ReturnType<typeof createDeferred<recognitionApi.MediaIdentitiesResponse>>> =
      [];
    vi.mocked(recognitionApi.fetchMediaIdentities).mockImplementation(async () => {
      identitiesCalls += 1;
      if (identitiesCalls === 1) {
        return emptyIdentities();
      }
      const deferred = createDeferred<recognitionApi.MediaIdentitiesResponse>();
      identitiesDeferreds.push(deferred);
      return deferred.promise;
    });

    const { result } = renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: true }), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.detailQuery.isFetching).toBe(false));
    await waitFor(() => expect(result.current.identitiesQuery.isFetching).toBe(false));

    await waitFor(() => {
      expect(
        fetchWorkbenchMediaMock.mock.calls.filter((call) => call[0].page === 2),
      ).toHaveLength(1);
    });

    // Force identities refetch (simulates 3s clustering poll settle cycle).
    await act(async () => {
      const refetchPromise = result.current.identitiesQuery.refetch();
      // Resolve the in-flight poll refetch so isFetching flips true→false and the effect re-runs.
      await waitFor(() => expect(identitiesDeferreds.length).toBeGreaterThanOrEqual(1));
      identitiesDeferreds[0]?.resolve(emptyIdentities());
      await refetchPromise;
    });

    await waitFor(() => expect(result.current.identitiesQuery.isFetching).toBe(false));

    // Once-per-page-key: still exactly one next-page fetch.
    expect(
      fetchWorkbenchMediaMock.mock.calls.filter((call) => call[0].page === 2),
    ).toHaveLength(1);

    queryClient.clear();
  });

  it('S4: disabled hook issues no media or next-page prefetch', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchWorkbenchMediaMock = vi.mocked(fetchWorkbenchMedia);

    renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: false }), { wrapper });

    await waitFor(() => {
      expect(fetchWorkbenchMediaMock).not.toHaveBeenCalled();
    });

    queryClient.clear();
  });

  it('S4: empty mediaIds (no stage-2) still prefetches next page after media settle', async () => {
    const { wrapper, queryClient } = createWrapper();
    const page1: WorkbenchMediaResponse = {
      items: [],
      total: 0,
      totalPages: 2,
    };
    const page2: WorkbenchMediaResponse = {
      items: [pageMediaItem(401, 'P2')],
      total: 1,
      totalPages: 2,
    };

    const fetchWorkbenchMediaMock = vi.mocked(fetchWorkbenchMedia);
    fetchWorkbenchMediaMock.mockImplementation(async ({ page }) => (page === 1 ? page1 : page2));
    vi.mocked(fetchWorkbenchMediaDetail).mockResolvedValue(emptyDetail());
    vi.mocked(recognitionApi.fetchMediaIdentities).mockResolvedValue(emptyIdentities());

    renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: true }), { wrapper });

    await waitFor(() => {
      expect(
        fetchWorkbenchMediaMock.mock.calls.filter((call) => call[0].page === 2),
      ).toHaveLength(1);
    });
    expect(vi.mocked(fetchWorkbenchMediaDetail)).not.toHaveBeenCalled();
    expect(recognitionApi.fetchMediaIdentities).not.toHaveBeenCalled();

    queryClient.clear();
  });
});
