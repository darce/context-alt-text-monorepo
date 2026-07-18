/**
 * E21-5 Slice 5 — truncation gate (PR-35 / BR-43).
 * Consumes query-cache first-page envelope only — never isFullyLoaded.
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchClusterMembers } from '../../../../api/recognition';
import type { ClusterIdentity, ClusterMembersResponse } from '../../../../api/recognition';
import { queryKeys } from '../../../../api/queryKeys';
import { useSelectedClusterTruncation } from '../useSelectedClusterTruncation';

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>(
    '../../../../api/recognition',
  );
  return {
    ...actual,
    fetchClusterMembers: vi.fn(),
  };
});

const makeMember = (id: string): ClusterIdentity => ({
  identity_id: id,
  media_id: Number(id.replace(/\D/g, '') || 1),
  similarity: 0.9,
  confidence: 0.95,
  bbox: { x: 0, y: 0, width: 10, height: 10 },
  thumb_url: `http://example.test/${id}.jpg`,
});

const makeEnvelope = (
  members: ClusterIdentity[],
  overrides: Partial<ClusterMembersResponse> = {},
): ClusterMembersResponse => ({
  members,
  limit: overrides.limit ?? (members.length || 2),
  total: overrides.total ?? members.length,
  truncated: overrides.truncated ?? false,
});

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return Object.assign(wrapper, { queryClient });
};

describe('useSelectedClusterTruncation', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('is not gated when selection has no target clusters', () => {
    const { result } = renderHook(() => useSelectedClusterTruncation([]), {
      wrapper: createWrapper(),
    });
    expect(result.current.isTruncationGated).toBe(false);
    expect(result.current.targetClusterIds).toEqual([]);
    expect(fetchClusterMembers).not.toHaveBeenCalled();
  });

  it('gates when first-page envelope reports truncated=true', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue(
      makeEnvelope([makeMember('m1'), makeMember('m2')], {
        limit: 2,
        total: 10,
        truncated: true,
      }),
    );

    const { result } = renderHook(() => useSelectedClusterTruncation(['cluster-trunc']), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isTruncationGated).toBe(true);
    expect(result.current.gatedTotal).toBe(10);
    expect(result.current.gatedHiddenCount).toBe(8);
    expect(fetchClusterMembers).toHaveBeenCalledWith('cluster-trunc');
  });

  it('is ungated when envelope is not truncated', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue(
      makeEnvelope([makeMember('m1')], { limit: 25, total: 1, truncated: false }),
    );

    const { result } = renderHook(() => useSelectedClusterTruncation(['cluster-full']), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isTruncationGated).toBe(false);
    expect(result.current.gatedHiddenCount).toBe(0);
  });

  it('reads from query-cache envelope (memberList key) without show-all expansion', async () => {
    const wrapper = createWrapper();
    const envelope = makeEnvelope([makeMember('m1')], {
      limit: 1,
      total: 5,
      truncated: true,
    });
    wrapper.queryClient.setQueryData(queryKeys.clusters.memberList('cluster-cached'), envelope);

    const { result } = renderHook(() => useSelectedClusterTruncation(['cluster-cached']), {
      wrapper,
    });

    await waitFor(() => {
      expect(result.current.isTruncationGated).toBe(true);
    });

    expect(result.current.gatedTotal).toBe(5);
    // Prefetch may still hit network depending on staleTime; gate data matches cache.
    expect(result.current.truncatedClusters[0]?.hiddenCount).toBe(4);
  });

  it('dedupes target cluster ids', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue(
      makeEnvelope([makeMember('m1')], { truncated: false, total: 1 }),
    );

    const { result } = renderHook(
      () => useSelectedClusterTruncation(['c1', 'c1', null, 'c2', undefined]),
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.targetClusterIds).toEqual(['c1', 'c2']);
  });

  it('BR-52: fetch error fails closed — isTruncationGated + isError; refetch retries', async () => {
    vi.mocked(fetchClusterMembers).mockRejectedValueOnce(new Error('network down'));

    const { result } = renderHook(() => useSelectedClusterTruncation(['cluster-err']), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isError).toBe(true);
    expect(result.current.isTruncationGated).toBe(true);

    vi.mocked(fetchClusterMembers).mockResolvedValue(
      makeEnvelope([makeMember('m1')], { truncated: false, total: 1 }),
    );

    act(() => {
      result.current.refetch();
    });

    await waitFor(() => {
      expect(result.current.isError).toBe(false);
    });
    expect(result.current.isTruncationGated).toBe(false);
  });
});
