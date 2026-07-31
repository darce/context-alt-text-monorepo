import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  invalidateMediaStats,
  MEDIA_STATS_PROBE,
  mediaStatsMissingQueryKey,
  mediaStatsTotalQueryKey,
  useMediaStats,
} from '../useMediaStats';
import { queryKeys } from '../../api/queryKeys';
import * as workbenchMediaApi from '../../api/workbenchMediaApi';
import type { WorkbenchMediaResponse } from '../../api/workbenchMediaApi';

vi.mock('../../api/workbenchMediaApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/workbenchMediaApi')>(
    '../../api/workbenchMediaApi',
  );
  return {
    ...actual,
    fetchWorkbenchMedia: vi.fn(),
  };
});

const fetchWorkbenchMock = vi.mocked(workbenchMediaApi.fetchWorkbenchMedia);

const envelope = (total: number): WorkbenchMediaResponse => ({
  items: [],
  total,
  totalPages: Math.max(1, total),
});

const buildClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const createWrapper = (client: QueryClient) => {
  const Wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

describe('useMediaStats', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('exports probe keys that match the queries the hook observes', async () => {
    expect(mediaStatsMissingQueryKey).toEqual(
      queryKeys.media.workbenchPage({ ...MEDIA_STATS_PROBE, status: 'missing' }),
    );
    expect(mediaStatsTotalQueryKey).toEqual(
      queryKeys.media.workbenchPage({ ...MEDIA_STATS_PROBE, status: 'all' }),
    );
    // Distinct from a real workbench list page — invalidating the probe cannot
    // match a perPage:20 list entry (BR-77 safety).
    expect(mediaStatsMissingQueryKey).not.toEqual(
      queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' }),
    );

    fetchWorkbenchMock.mockImplementation((params) => {
      if (params.status === 'missing') {
        return Promise.resolve(envelope(3));
      }
      return Promise.resolve(envelope(10));
    });

    const client = buildClient();
    const { result } = renderHook(() => useMediaStats(), { wrapper: createWrapper(client) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.stats.total).toBe(10);
    expect(result.current.stats.missing).toBe(3);
    expect(result.current.stats.complete).toBe(7);
    expect(result.current.stats.coverage).toBe(70);
    expect(client.getQueryData(mediaStatsMissingQueryKey)).toEqual(envelope(3));
    expect(client.getQueryData(mediaStatsTotalQueryKey)).toEqual(envelope(10));
  });

  it('invalidateMediaStats refetches only the missing probe under the exported key', async () => {
    fetchWorkbenchMock.mockImplementation((params) => {
      if (params.status === 'missing' && params.perPage === 1) {
        return Promise.resolve(envelope(5));
      }
      if (params.status === 'all' && params.perPage === 1) {
        return Promise.resolve(envelope(12));
      }
      return Promise.resolve(envelope(0));
    });

    const client = buildClient();
    // Seed a list page that must never be touched by stats invalidation.
    const listKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
    client.setQueryData<WorkbenchMediaResponse>(listKey, {
      items: [
        {
          id: 1,
          title: 'Kept',
          status: 'missing',
          thumbnailUrl: null,
          altText: null,
          isDecorative: false,
          editUrl: null,
          tags: [],
        },
      ],
      total: 1,
      totalPages: 1,
    });

    const { result } = renderHook(() => useMediaStats(), { wrapper: createWrapper(client) });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.stats.missing).toBe(5);

    const missingBefore = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'missing' && call[0].perPage === 1,
    ).length;
    const totalBefore = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'all' && call[0].perPage === 1,
    ).length;

    fetchWorkbenchMock.mockImplementation((params) => {
      if (params.status === 'missing' && params.perPage === 1) {
        return Promise.resolve(envelope(4));
      }
      if (params.status === 'all' && params.perPage === 1) {
        return Promise.resolve(envelope(12));
      }
      return Promise.resolve(envelope(0));
    });

    invalidateMediaStats(client);

    await waitFor(() => expect(result.current.stats.missing).toBe(4));
    const missingAfter = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'missing' && call[0].perPage === 1,
    ).length;
    const totalAfter = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'all' && call[0].perPage === 1,
    ).length;
    expect(missingAfter).toBeGreaterThan(missingBefore);
    expect(totalAfter).toBe(totalBefore);
    // List page data untouched — wrong partial-match invalidation would clear it.
    expect(client.getQueryData<WorkbenchMediaResponse>(listKey)?.items).toHaveLength(1);
    expect(client.getQueryData<WorkbenchMediaResponse>(listKey)?.total).toBe(1);
  });
});
