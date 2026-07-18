import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

import { fetchClusterMembers } from '../../../../api/recognition';
import type { ClusterIdentity, ClusterMembersResponse } from '../../../../api/recognition';
import { useShowAllClusterMembers } from '../useShowAllClusterMembers';

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

describe('useShowAllClusterMembers', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('pages through a truncated envelope to full membership without unbounded fetch', async () => {
    const fetchMock = vi.mocked(fetchClusterMembers);
    const page1 = [makeMember('m1'), makeMember('m2')];
    const page2 = [makeMember('m3'), makeMember('m4')];
    const page3 = [makeMember('m5')];

    fetchMock.mockImplementation((_clusterId, params = {}) => {
      const offset = params.offset ?? 0;
      if (offset === 0) {
        return Promise.resolve(makeEnvelope(page1, { limit: 2, total: 5, truncated: true }));
      }
      if (offset === 2) {
        return Promise.resolve(makeEnvelope(page2, { limit: 2, total: 5, truncated: true }));
      }
      if (offset === 4) {
        return Promise.resolve(makeEnvelope(page3, { limit: 1, total: 5, truncated: false }));
      }
      return Promise.reject(new Error(`unexpected offset ${offset}`));
    });

    const { result } = renderHook(() => useShowAllClusterMembers('cluster-show-all'), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.truncated).toBe(true);
    expect(result.current.total).toBe(5);
    expect(result.current.members).toHaveLength(2);
    expect(result.current.isFullyLoaded).toBe(false);
    // First page only — no limit/offset params.
    expect(fetchMock).toHaveBeenCalledWith('cluster-show-all');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.showAll();
    });

    expect(result.current.isFullyLoaded).toBe(true);
    expect(result.current.members.map((m) => m.identity_id)).toEqual([
      'm1',
      'm2',
      'm3',
      'm4',
      'm5',
    ]);
    // Envelope truncated flag from first page remains for Slice-5 bulk gate.
    expect(result.current.truncated).toBe(true);

    const pagedCalls = fetchMock.mock.calls.filter((call) => call[1] !== undefined);
    expect(pagedCalls).toEqual([
      ['cluster-show-all', { limit: 2, offset: 2 }],
      ['cluster-show-all', { limit: 1, offset: 4 }],
    ]);
    // Never requests beyond total: final page uses remaining count (1), not full page limit.
    expect(pagedCalls.every((call) => {
      const params = call[1] ?? {};
      const offset = params.offset ?? 0;
      const limit = params.limit ?? 0;
      return offset + limit <= 5;
    })).toBe(true);
  });

  it('discards in-flight show-all results when the cluster changes mid-paging', async () => {
    const fetchMock = vi.mocked(fetchClusterMembers);
    let releasePage: (value: ClusterMembersResponse) => void = () => undefined;

    fetchMock.mockImplementation((clusterId, params = {}) => {
      const offset = params.offset ?? 0;
      if (clusterId === 'cluster-a') {
        if (offset === 0) {
          return Promise.resolve(
            makeEnvelope([makeMember('a1'), makeMember('a2')], { limit: 2, total: 4, truncated: true }),
          );
        }
        // Hold the second page open until the test switches clusters.
        return new Promise<ClusterMembersResponse>((resolve) => {
          releasePage = resolve;
        });
      }
      return Promise.resolve(makeEnvelope([makeMember('b1')], { limit: 2, total: 1, truncated: false }));
    });

    const { result, rerender } = renderHook(({ clusterId }) => useShowAllClusterMembers(clusterId), {
      wrapper: createWrapper(),
      initialProps: { clusterId: 'cluster-a' },
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    let showAllPromise: Promise<void> = Promise.resolve();
    act(() => {
      showAllPromise = result.current.showAll();
    });

    rerender({ clusterId: 'cluster-b' });

    await waitFor(() => {
      expect(result.current.members.map((m) => m.identity_id)).toEqual(['b1']);
    });

    await act(async () => {
      releasePage(makeEnvelope([makeMember('a3'), makeMember('a4')], { limit: 2, total: 4, truncated: false }));
      await showAllPromise;
    });

    // Stale cluster-a pages never leak into cluster-b state.
    expect(result.current.members.map((m) => m.identity_id)).toEqual(['b1']);
    expect(result.current.expandError).toBeNull();
  });

  it('drops the expanded snapshot back to the honest first page after a refetch', async () => {
    const fetchMock = vi.mocked(fetchClusterMembers);
    let removed = false;

    fetchMock.mockImplementation((_clusterId, params = {}) => {
      const offset = params.offset ?? 0;
      if (removed) {
        return Promise.resolve(makeEnvelope([makeMember('m1')], { limit: 2, total: 1, truncated: false }));
      }
      if (offset === 0) {
        return Promise.resolve(
          makeEnvelope([makeMember('m1'), makeMember('m2')], { limit: 2, total: 3, truncated: true }),
        );
      }
      return Promise.resolve(makeEnvelope([makeMember('m3')], { limit: 1, total: 3, truncated: false }));
    });

    const wrapper = createWrapper();
    const { result } = renderHook(() => useShowAllClusterMembers('cluster-refetch'), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.showAll();
    });
    expect(result.current.members.map((m) => m.identity_id)).toEqual(['m1', 'm2', 'm3']);

    // Mutation invalidates + refetch returns the member-removed envelope.
    removed = true;
    await act(async () => {
      await wrapper.queryClient.refetchQueries();
    });

    await waitFor(() => {
      expect(result.current.members.map((m) => m.identity_id)).toEqual(['m1']);
    });
    expect(result.current.isFullyLoaded).toBe(true);
  });

  it('surfaces an error and keeps the honest first page when a mid-run page comes back empty', async () => {
    const fetchMock = vi.mocked(fetchClusterMembers);

    fetchMock.mockImplementation((_clusterId, params = {}) => {
      const offset = params.offset ?? 0;
      if (offset === 0) {
        return Promise.resolve(
          makeEnvelope([makeMember('m1'), makeMember('m2')], { limit: 2, total: 5, truncated: true }),
        );
      }
      return Promise.resolve(makeEnvelope([], { limit: 2, total: 5, truncated: true }));
    });

    const { result } = renderHook(() => useShowAllClusterMembers('cluster-empty-page'), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.showAll();
    });

    expect(result.current.expandError).toBe('Unable to load remaining members.');
    expect(result.current.members.map((m) => m.identity_id)).toEqual(['m1', 'm2']);
    // Not stamped complete: the affordance stays available for a retry.
    expect(result.current.isFullyLoaded).toBe(false);
    expect(result.current.isExpanding).toBe(false);
  });

  it('surfaces an error and keeps the honest first page when a mid-run page rejects', async () => {
    const fetchMock = vi.mocked(fetchClusterMembers);

    fetchMock.mockImplementation((_clusterId, params = {}) => {
      const offset = params.offset ?? 0;
      if (offset === 0) {
        return Promise.resolve(
          makeEnvelope([makeMember('m1'), makeMember('m2')], { limit: 2, total: 5, truncated: true }),
        );
      }
      return Promise.reject(new Error('network down'));
    });

    const { result } = renderHook(() => useShowAllClusterMembers('cluster-reject'), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.showAll();
    });

    expect(result.current.expandError).toBe('network down');
    expect(result.current.members.map((m) => m.identity_id)).toEqual(['m1', 'm2']);
    expect(result.current.isFullyLoaded).toBe(false);
    expect(result.current.isExpanding).toBe(false);
  });

  it('does not fetch again when already fully loaded', async () => {
    const fetchMock = vi.mocked(fetchClusterMembers);
    fetchMock.mockResolvedValue(
      makeEnvelope([makeMember('only')], { limit: 500, total: 1, truncated: false }),
    );

    const { result } = renderHook(() => useShowAllClusterMembers('cluster-full'), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isFullyLoaded).toBe(true);

    await act(async () => {
      await result.current.showAll();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
