import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../api/queryKeys';
import type { RosterEntry } from '../../api/rosterApi';
import * as rosterApi from '../../api/rosterApi';
import { derivePersonState, PERSON_STATES } from '../../pages/roster/personState';
import { useCreatePerson, useUpdatePerson } from '../useRosterHooks';

vi.mock('../../api/rosterApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/rosterApi')>();
  return {
    ...actual,
    createPerson: vi.fn(),
    updatePerson: vi.fn(),
    deletePerson: vi.fn(),
    listRosterEntries: vi.fn(),
  };
});

const rosterEntriesKey = queryKeys.roster.entries();

const projectedNeedsReview: RosterEntry = {
  id: 1,
  person_uuid: 'person-uuid-alex',
  name: 'Alex',
  tags: ['fixture'],
  cluster_count: 2,
  clusters: [
    {
      cluster_id: 'cluster-1',
      identity_count: 1,
      representative_identity: null,
      instances: [],
    },
  ],
  queue_memberships: ['hard-examples'],
  updated_at: '2026-01-01T00:00:00Z',
  source_version: 3,
  projection_status: 'current',
  projection_refreshed_at: '2026-01-01T00:00:00Z',
};

/**
 * Raw acx_persons row returned by update_person / create_person —
 * no queue_memberships, no clusters, no projection_status.
 */
const personsRowBody = {
  id: 1,
  person_uuid: 'person-uuid-alex',
  name: 'Alex Updated',
  tags: ['fixture', 'edited'],
  cluster_count: 2,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
} as unknown as RosterEntry;

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, queryClient };
};

describe('useRosterHooks cache merge on person mutation [S4-BR-02]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('useUpdatePerson onSuccess merges into previous entry so needs-review is preserved', async () => {
    vi.mocked(rosterApi.updatePerson).mockResolvedValue(personsRowBody);

    const { wrapper, queryClient } = createWrapper();
    queryClient.setQueryData<RosterEntry[]>(rosterEntriesKey, [projectedNeedsReview]);

    // Sanity: pre-update cache derives needs-review from hard-examples membership.
    expect(derivePersonState(projectedNeedsReview)).toBe(PERSON_STATES.NEEDS_REVIEW);

    const { result } = renderHook(() => useUpdatePerson(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ id: 1, name: 'Alex Updated', tags: ['fixture', 'edited'] });
    });

    // Before invalidation settles, the cache must still carry projection fields
    // that a bare persons-row replace would wipe.
    const cached = queryClient.getQueryData<RosterEntry[]>(rosterEntriesKey);
    expect(cached).toHaveLength(1);
    const entry = cached![0];

    expect(entry.name).toBe('Alex Updated');
    expect(entry.tags).toEqual(['fixture', 'edited']);
    expect(entry.queue_memberships).toEqual(['hard-examples']);
    expect(entry.clusters).toEqual(projectedNeedsReview.clusters);
    expect(entry.projection_status).toBe('current');
    expect(derivePersonState(entry)).toBe(PERSON_STATES.NEEDS_REVIEW);
    expect(derivePersonState(entry)).not.toBe(PERSON_STATES.NAMED);

    queryClient.clear();
  });

  it('useCreatePerson onSuccess merges sparse create body without dropping sibling projection fields on replace of optimistic row', async () => {
    const sparseCreateBody = {
      id: 99,
      person_uuid: 'person-uuid-new',
      name: 'New Person',
      tags: [],
      cluster_count: 0,
      created_at: '2026-01-03T00:00:00Z',
      updated_at: '2026-01-03T00:00:00Z',
    } as unknown as RosterEntry;

    vi.mocked(rosterApi.createPerson).mockResolvedValue(sparseCreateBody);

    const { wrapper, queryClient } = createWrapper();
    // Seed an unrelated needs-review peer so create path cannot clobber the whole list.
    queryClient.setQueryData<RosterEntry[]>(rosterEntriesKey, [projectedNeedsReview]);

    const { result } = renderHook(() => useCreatePerson(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ name: 'New Person' });
    });

    await waitFor(() => {
      const cached = queryClient.getQueryData<RosterEntry[]>(rosterEntriesKey) ?? [];
      // Optimistic id replaced; peer + created entry remain.
      expect(cached.some((e) => e.id === 99)).toBe(true);
    });

    const cached = queryClient.getQueryData<RosterEntry[]>(rosterEntriesKey) ?? [];
    const created = cached.find((e) => e.id === 99)!;
    const peer = cached.find((e) => e.id === 1)!;

    // Peer needs-review must survive create's list rewrite.
    expect(peer.queue_memberships).toEqual(['hard-examples']);
    expect(derivePersonState(peer)).toBe(PERSON_STATES.NEEDS_REVIEW);

    // Created row must have safe defaults for projection fields (not undefined).
    expect(Array.isArray(created.queue_memberships)).toBe(true);
    expect(created.queue_memberships).toEqual([]);
    expect(Array.isArray(created.clusters)).toBe(true);
    expect(created.clusters).toEqual([]);
    expect(created.projection_status).toBeDefined();
    expect(derivePersonState(created)).toBe(PERSON_STATES.NAMED);

    queryClient.clear();
  });
});
