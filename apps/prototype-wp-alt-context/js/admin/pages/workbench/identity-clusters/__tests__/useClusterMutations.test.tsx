import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import * as recognitionApi from '../../../../api/recognition';
import { useClusterMutations } from '../useClusterMutations';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    pinRepresentative: vi.fn(),
    updateClusterLabel: vi.fn(),
    mergeCluster: vi.fn(),
    revertMergeCluster: vi.fn(),
    acceptSuggestion: vi.fn(),
    createClusterForIdentity: vi.fn(),
    fetchScanStatus: vi.fn(),
    reassignClusterIdentity: vi.fn(),
    rejectSuggestion: vi.fn(),
    splitCluster: vi.fn(),
  };
});

vi.mock('../../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

describe('useClusterMutations invalidate refetch (R3-05)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(recognitionApi.pinRepresentative).mockResolvedValue(undefined);
  });

  it('R3-05: a non-review cluster mutation refetches a mounted identities list', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const identitiesKey = queryKeys.media.identities();
    const fetchIdentities = vi.fn().mockResolvedValue({ identities_by_media: {} });
    const fetchLabels = vi.fn().mockResolvedValue([]);
    const fetchClusters = vi.fn().mockResolvedValue({ clusters: [] });
    const fetchProjection = vi.fn().mockResolvedValue({ items: [] });
    const fetchMergePending = vi.fn().mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(
      () => {
        const list = useQuery({ queryKey: identitiesKey, queryFn: fetchIdentities, staleTime: 0 });
        const labels = useQuery({
          queryKey: queryKeys.clusters.labels(),
          queryFn: fetchLabels,
          staleTime: 0,
        });
        const clusters = useQuery({
          queryKey: queryKeys.clusters.all,
          queryFn: fetchClusters,
          staleTime: 0,
        });
        const projection = useQuery({
          queryKey: queryKeys.suggestions.projection.all,
          queryFn: fetchProjection,
          staleTime: 0,
        });
        const mergePending = useQuery({
          queryKey: queryKeys.suggestions.mergePending(),
          queryFn: fetchMergePending,
          staleTime: 0,
        });
        const mutations = useClusterMutations({
          clusterId: 'cluster-1',
          currentLabel: null,
          derivedLabel: null,
        });
        return { list, labels, clusters, projection, mergePending, mutations };
      },
      { wrapper },
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    fetchIdentities.mockClear();
    fetchLabels.mockClear();
    fetchClusters.mockClear();
    fetchProjection.mockClear();
    fetchMergePending.mockClear();

    await act(async () => {
      result.current.mutations.pinRepresentative('rep-1', true);
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(fetchIdentities).toHaveBeenCalled();
      expect(fetchLabels).toHaveBeenCalled();
      expect(fetchClusters).toHaveBeenCalled();
      expect(fetchProjection).toHaveBeenCalled();
      expect(fetchMergePending).toHaveBeenCalled();
    });
  });
});
