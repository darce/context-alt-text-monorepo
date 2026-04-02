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
});
