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
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
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
