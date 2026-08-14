import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import { useInlineSuggestionBatch } from '../useInlineSuggestionBatch';
import { useClusterSuggestions } from '../useClusterSuggestions';
import {
  PROJECTION_TOP_K,
  identityBatchIdsKey,
} from '../suggestionProjection';
import { suggestionProjectionMatrix } from './suggestionProjection.fixtures';
import * as recognitionApi from '../../../../api/recognition';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../../test-utils/mockHooks';

vi.mock('../../../../api/recognition', () => ({
  fetchIdentitiesSuggestions: vi.fn(),
  listRecognitionClusters: vi.fn(),
}));

vi.mock('../../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, queryClient };
};

const match = (label: string, cluster_id = `cluster-${label}`) => ({
  cluster_id,
  label,
  similarity: 0.9,
  identity_count: 2,
});

describe('useInlineSuggestionBatch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
    vi.mocked(recognitionApi.listRecognitionClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
    });
  });

  it('issues exactly one batched call for the supplied id set with top_k=PROJECTION_TOP_K', async () => {
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockResolvedValue({ matches: {} });

    const { wrapper } = createWrapper();
    renderHook(() => useInlineSuggestionBatch(['a', 'b', 'c']), { wrapper });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(['a', 'b', 'c'], PROJECTION_TOP_K);
    expect(PROJECTION_TOP_K).toBe(5);
  });

  it('fetches nothing for an empty id set', async () => {
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockResolvedValue({ matches: {} });

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useInlineSuggestionBatch([]), { wrapper });

    // Give any accidental query a chance to fire.
    await Promise.resolve();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.getMatch('a')).toBeUndefined();
  });

  it('keys by identity id and returns the first server-ranked match as ProjectedSuggestion', async () => {
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockResolvedValue({
      matches: {
        a: [match('Ada'), match('Ada-second')],
        b: [match('Bob')],
      },
    });

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useInlineSuggestionBatch(['a', 'b']), { wrapper });

    await waitFor(() => expect(result.current.getMatch('a')?.label).toBe('Ada'));
    expect(result.current.getMatch('a')).toMatchObject({
      identityId: 'a',
      clusterId: 'cluster-Ada',
      label: 'Ada',
      similarity: 0.9,
      identityCount: 2,
    });
    expect(result.current.getMatch('b')?.label).toBe('Bob');
    expect(result.current.getMatch('b')?.clusterId).toBe('cluster-Bob');
  });

  it('returns undefined for an identity absent from the keyed envelope (empty-match)', async () => {
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockResolvedValue({ matches: { a: [match('Ada')] } });

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useInlineSuggestionBatch(['a', 'b']), { wrapper });

    await waitFor(() => expect(result.current.getMatch('a')?.label).toBe('Ada'));
    // 'b' had no eligible suggestion → omitted from the mapping.
    expect(result.current.getMatch('b')).toBeUndefined();
    // Undefined id (no anchor) also yields nothing.
    expect(result.current.getMatch(undefined)).toBeUndefined();
  });

  it('excludes auto cluster-* labeled matches via isHumanLabeledTarget', async () => {
    // Expected first failure under commit-1 predicate: expected undefined, received ProjectedSuggestion with label 'cluster-1234'
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockResolvedValue({
      matches: {
        a: [match('cluster-1234', 'cluster-1234')],
      },
    });

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useInlineSuggestionBatch(['a']), { wrapper });

    // Wait for the data to be applied, not merely the fetch to fire — getMatch is
    // also undefined while loading, which would green a broken filter (BR-11).
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.getMatch('a')).toBeUndefined();
  });

  it('surfaces first human-labeled match inside PROJECTION_TOP_K window (clusterFirstThenHuman)', async () => {
    // Fixture rank-1/2 labels are machine-shaped (`cluster-auto-1` / `cluster-auto-2`);
    // isHumanLabeledTarget gates them so getMatch surfaces 'Bob' (sug-cf-3).
    const { identityId, matches, expectedIdentityTopSuggestionId } = suggestionProjectionMatrix.clusterFirstThenHuman;
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockResolvedValue({
      matches: {
        [identityId]: [...matches],
      },
    });

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useInlineSuggestionBatch([identityId]), { wrapper });

    await waitFor(() =>
      expect(result.current.getMatch(identityId)?.suggestionId).toBe(expectedIdentityTopSuggestionId),
    );
    expect(result.current.getMatch(identityId)?.label).toBe('Bob');
    expect(result.current.getMatch(identityId)?.suggestionId).toBe('sug-cf-3');
  });

  it('returns no prompt when the entire PROJECTION_TOP_K window is ineligible (allIneligibleWindow)', async () => {
    // Expected first failure under commit-1: getMatch is defined (auto/blank first row still truthy-or-auto), not undefined
    const { identityId, matches } = suggestionProjectionMatrix.allIneligibleWindow;
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockResolvedValue({
      matches: {
        [identityId]: [...matches],
      },
    });

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useInlineSuggestionBatch([identityId]), { wrapper });

    // Wait for the data to be applied, not merely the fetch to fire (BR-11).
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.getMatch(identityId)).toBeUndefined();
  });

  it('seeds per-identity keys so dropdown loader reuses batch without second fetch (BR-10)', async () => {
    // Predicted first failure: dual cache keys → second fetchIdentitiesSuggestions for single id
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockResolvedValue({
      matches: {
        a: [match('Ada', 'cluster-Ada')],
        b: [match('Bob', 'cluster-Bob')],
      },
    });

    const { wrapper, queryClient } = createWrapper();
    const { result: batch } = renderHook(() => useInlineSuggestionBatch(['a', 'b']), { wrapper });
    await waitFor(() => expect(batch.current.getMatch('a')?.label).toBe('Ada'));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const singleKey = queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey(['a']));
    expect(queryClient.getQueryData(singleKey)).toEqual({
      matches: { a: [match('Ada', 'cluster-Ada')] },
    });

    const { result: dropdown } = renderHook(
      () => useClusterSuggestions({ identityId: 'a', enabled: true, labelInput: '', debounceMs: 0 }),
      { wrapper },
    );
    await waitFor(() => expect(dropdown.current.isLoading).toBe(false));
    await waitFor(() =>
      expect(dropdown.current.options.some((o) => o.label === 'Ada' && o.group === 'Suggested')).toBe(true),
    );

    // Still one network call — single-id entry was seeded from the multi-id batch.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
