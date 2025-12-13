import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useWorkbenchMedia } from '../useWorkbenchMedia';
import * as recognitionApi from '../../api/recognition';

vi.mock('../../api/recognition', () => ({
  fetchMediaIdentities: vi.fn(),
}));

describe('useWorkbenchMedia', () => {
  const originalFetch = globalThis.fetch;

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
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      endpoints: {
        workbenchMedia: '/wp-json/acx/v1/media',
        recognitionAnalyze: '/wp-json/acx/v1/recognition/analyze',
        recognitionJobs: '/wp-json/acx/v1/recognition/jobs',
        recognitionCluster: '/wp-json/acx/v1/recognition/cluster',
        recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
      },
    };
  });

  afterEach(() => {
    if (originalFetch) {
      globalThis.fetch = originalFetch;
    } else {
      // @ts-expect-error allow cleanup when fetch was undefined
      delete globalThis.fetch;
    }
  });

  it('merges fetched identities into each media item', async () => {
    const { wrapper, queryClient } = createWrapper();
    const mediaResponse = {
      items: [
        {
          id: 11,
          title: 'Item A',
          altText: null,
          status: 'missing',
          thumbnailUrl: null,
          mimeType: 'image/jpeg',
          editUrl: '#',
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
          tags: [],
        },
      ],
      total: 2,
      totalPages: 1,
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mediaResponse),
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
    fetchMediaIdentitiesMock.mockResolvedValue({
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

    const { result } = renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: true }), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(fetchMediaIdentitiesMock).toHaveBeenCalledWith([11, 12]);

    const merged = result.current.itemsWithIdentities;
    expect(merged).toHaveLength(2);
    expect(merged?.[0].identities).toHaveLength(1);
    expect(merged?.[1].identities).toEqual([]);

    queryClient.clear();
  });

  it('skips fetching when disabled', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as typeof fetch;

    renderHook(() => useWorkbenchMedia({ page: 1, perPage: 10, enabled: false }), { wrapper });

    await waitFor(() => {
      expect(fetchMock).not.toHaveBeenCalled();
      expect(recognitionApi.fetchMediaIdentities).not.toHaveBeenCalled();
    });

    queryClient.clear();
  });
});
