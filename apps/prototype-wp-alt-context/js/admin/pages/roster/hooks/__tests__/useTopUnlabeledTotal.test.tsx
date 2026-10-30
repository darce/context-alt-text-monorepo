import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { DATA_SOURCE, PROJECTION_STATUS } from '../../../../api/recognition/types/dataSource';
import { queryKeys } from '../../../../api/queryKeys';
import { fetchTopUnlabeledClusters } from '../../../../api/recognition';
import { useTopUnlabeledTotal } from '../useTopUnlabeledTotal';

vi.mock('../../../../api/config', () => ({
  getConfig: () => ({ tenant_id: 'tenant-1' }),
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>(
    '../../../../api/recognition',
  );
  return {
    ...actual,
    fetchTopUnlabeledClusters: vi.fn(),
  };
});

const mockedFetch = vi.mocked(fetchTopUnlabeledClusters);

const envelope = (
  overrides: Partial<Awaited<ReturnType<typeof fetchTopUnlabeledClusters>>> = {},
): Awaited<ReturnType<typeof fetchTopUnlabeledClusters>> => ({
  clusters: [
    {
      id: 'a',
      tenant_id: 'tenant-1',
      label: null,
      is_labeled: false,
      is_auto_label: true,
      identity_count: 2,
      user_confirmed: false,
      representatives: [],
    },
    {
      id: 'b',
      tenant_id: 'tenant-1',
      label: null,
      is_labeled: false,
      is_auto_label: true,
      identity_count: 3,
      user_confirmed: false,
      representatives: [],
    },
  ],
  limit: 20,
  total: 99,
  truncated: true,
  data_source: DATA_SOURCE.LOCAL_PROJECTION,
  projection_status: PROJECTION_STATUS.AVAILABLE,
  ...overrides,
});

const wrapper = ({ children }: { children: ReactNode }) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

/** Probe shares the production query cache so tests can wait on settled, not pending-null. */
const useTopUnlabeledTotalProbe = () => {
  const total = useTopUnlabeledTotal();
  const query = useQuery({
    queryKey: queryKeys.clusters.topUnlabeled('tenant-1'),
    queryFn: () => fetchTopUnlabeledClusters('tenant-1', 20),
    enabled: false,
  });
  return { total, isFetched: query.isFetched, isSuccess: query.isSuccess };
};

describe('useTopUnlabeledTotal (rg-015)', () => {
  it('returns the envelope total, never clusters.length', async () => {
    mockedFetch.mockResolvedValue(envelope({ total: 99 }));

    const { result } = renderHook(() => useTopUnlabeledTotalProbe(), { wrapper });

    await waitFor(() => {
      expect(result.current.isFetched).toBe(true);
    });
    expect(result.current.total).toBe(99);
    expect(result.current.total).not.toBe(2);
  });

  it('returns null while loading', () => {
    mockedFetch.mockImplementation(() => new Promise(() => undefined));

    const { result } = renderHook(() => useTopUnlabeledTotalProbe(), { wrapper });
    expect(result.current.isFetched).toBe(false);
    expect(result.current.total).toBeNull();
  });

  it('returns null on fetch error after the query settles', async () => {
    mockedFetch.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => useTopUnlabeledTotalProbe(), { wrapper });
    await waitFor(() => {
      expect(result.current.isFetched).toBe(true);
    });
    expect(result.current.total).toBeNull();
  });

  it('returns null when total is missing from a counted-source envelope', async () => {
    mockedFetch.mockResolvedValue(envelope({ total: undefined as unknown as number }));
    const { result } = renderHook(() => useTopUnlabeledTotalProbe(), { wrapper });
    await waitFor(() => {
      expect(result.current.isFetched).toBe(true);
    });
    expect(result.current.total).toBeNull();
  });

  it('treats unavailable/bootstrapping total:0 as unknown after settle', async () => {
    mockedFetch.mockResolvedValue(
      envelope({
        clusters: [],
        total: 0,
        data_source: DATA_SOURCE.UNAVAILABLE,
        projection_status: PROJECTION_STATUS.BOOTSTRAPPING,
      }),
    );

    const { result } = renderHook(() => useTopUnlabeledTotalProbe(), { wrapper });

    await waitFor(() => {
      expect(result.current.isFetched).toBe(true);
    });
    expect(result.current.total).toBeNull();
  });

  it('treats endpoint_error as unknown after settle', async () => {
    mockedFetch.mockResolvedValue(
      envelope({
        clusters: [],
        total: 0,
        data_source: DATA_SOURCE.ENDPOINT_ERROR,
      }),
    );

    const { result } = renderHook(() => useTopUnlabeledTotalProbe(), { wrapper });

    await waitFor(() => {
      expect(result.current.isFetched).toBe(true);
    });
    expect(result.current.total).toBeNull();
  });

  it('returns 0 for a counted-source empty backlog (LOCAL_PROJECTION total:0)', async () => {
    mockedFetch.mockResolvedValue(
      envelope({
        clusters: [],
        total: 0,
        data_source: DATA_SOURCE.LOCAL_PROJECTION,
        projection_status: PROJECTION_STATUS.AVAILABLE,
      }),
    );

    const { result } = renderHook(() => useTopUnlabeledTotalProbe(), { wrapper });
    await waitFor(() => {
      expect(result.current.isFetched).toBe(true);
    });
    expect(result.current.total).toBe(0);
  });

  it('shares the workbench top-unlabeled query key and limit 20', async () => {
    mockedFetch.mockResolvedValue(envelope());

    const { result } = renderHook(() => useTopUnlabeledTotalProbe(), { wrapper });
    await waitFor(() => {
      expect(result.current.total).toBe(99);
    });

    expect(mockedFetch).toHaveBeenCalledWith('tenant-1', 20, expect.anything());
    expect(queryKeys.clusters.topUnlabeled('tenant-1')).toEqual(['clusters', 'top-unlabeled', 'tenant-1']);
  });

  it.each([
    { total: 0, dataSource: DATA_SOURCE.LOCAL_PROJECTION },
    { total: 7, dataSource: DATA_SOURCE.BACKEND_PROXY },
  ])('treats cached $total as unknown after a settled refetch error and recovers', async ({ total, dataSource }) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const key = queryKeys.clusters.topUnlabeled('tenant-1');
    const cached = envelope({
      total,
      data_source: dataSource,
      ...(total === 0 ? { clusters: [], truncated: false } : {}),
    });
    let rejectRefetch!: (error: Error) => void;
    mockedFetch.mockReset();
    mockedFetch
      .mockResolvedValueOnce(cached)
      .mockImplementationOnce(
        () =>
          new Promise((_, reject) => {
            rejectRefetch = reject;
          }),
      )
      .mockResolvedValue(envelope({ total: 12, data_source: dataSource }));
    const localWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const view = renderHook(() => useTopUnlabeledTotal(), { wrapper: localWrapper });

    try {
      await waitFor(() => expect(view.result.current).toBe(total));
      expect(client.getQueryState(key)?.status).toBe('success');

      let refetch!: Promise<void>;
      act(() => {
        refetch = client.refetchQueries({ queryKey: key, exact: true });
      });
      await waitFor(() => expect(client.getQueryState(key)?.fetchStatus).toBe('fetching'));
      // A normal pending refetch still exposes the last successful count.
      expect(view.result.current).toBe(total);

      await act(async () => {
        rejectRefetch(new Error('controlled HTTP 503 refetch'));
        await refetch;
      });
      await waitFor(() => expect(client.getQueryState(key)?.status).toBe('error'));
      // TanStack retains the successful envelope; the hook must classify it as unknown.
      expect(client.getQueryData(key)).toEqual(cached);
      await waitFor(() => expect(view.result.current).toBeNull());

      await act(async () => {
        await client.refetchQueries({ queryKey: key, exact: true });
      });
      await waitFor(() => {
        expect(client.getQueryState(key)?.status).toBe('success');
        expect(view.result.current).toBe(12);
      });
    } finally {
      view.unmount();
      client.clear();
    }
  });
});
