import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
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

describe('useTopUnlabeledTotal (rg-015)', () => {
  it('returns the envelope total, never clusters.length', async () => {
    mockedFetch.mockResolvedValue(envelope({ total: 99 }));

    const { result } = renderHook(() => useTopUnlabeledTotal(), { wrapper });

    await waitFor(() => {
      expect(result.current).toBe(99);
    });
    expect(result.current).not.toBe(2);
  });

  it('returns null while loading, on error, or when total is missing', async () => {
    mockedFetch.mockImplementation(() => new Promise(() => undefined));

    const { result: loading } = renderHook(() => useTopUnlabeledTotal(), { wrapper });
    expect(loading.current).toBeNull();

    mockedFetch.mockRejectedValue(new Error('boom'));
    const { result: errored } = renderHook(() => useTopUnlabeledTotal(), { wrapper });
    await waitFor(() => {
      expect(errored.current).toBeNull();
    });
  });

  it('treats unavailable/bootstrapping total:0 as unknown, not a known empty backlog', async () => {
    mockedFetch.mockResolvedValue(
      envelope({
        clusters: [],
        total: 0,
        data_source: DATA_SOURCE.UNAVAILABLE,
        projection_status: PROJECTION_STATUS.BOOTSTRAPPING,
      }),
    );

    const { result } = renderHook(() => useTopUnlabeledTotal(), { wrapper });

    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalled();
    });
    expect(result.current).toBeNull();
  });

  it('treats endpoint_error as unknown', async () => {
    mockedFetch.mockResolvedValue(
      envelope({
        clusters: [],
        total: 0,
        data_source: DATA_SOURCE.ENDPOINT_ERROR,
      }),
    );

    const { result } = renderHook(() => useTopUnlabeledTotal(), { wrapper });

    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalled();
    });
    expect(result.current).toBeNull();
  });

  it('shares the workbench top-unlabeled query key and limit 20', async () => {
    mockedFetch.mockResolvedValue(envelope());

    const { result } = renderHook(() => useTopUnlabeledTotal(), { wrapper });
    await waitFor(() => {
      expect(result.current).toBe(99);
    });

    expect(mockedFetch).toHaveBeenCalledWith('tenant-1', 20, expect.anything());
    expect(queryKeys.clusters.topUnlabeled('tenant-1')).toEqual([
      ...queryKeys.clusters.all,
      'top-unlabeled',
      'tenant-1',
    ]);
  });
});
