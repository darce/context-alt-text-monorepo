import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useInlineSuggestionBatch } from '../useInlineSuggestionBatch';
import * as recognitionApi from '../../../../api/recognition';

vi.mock('../../../../api/recognition', () => ({
  fetchIdentitiesSuggestions: vi.fn(),
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
  });

  it('issues exactly one batched call for the supplied id set with top_k=1', async () => {
    const fetchMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    fetchMock.mockResolvedValue({ matches: {} });

    const { wrapper } = createWrapper();
    renderHook(() => useInlineSuggestionBatch(['a', 'b', 'c']), { wrapper });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(['a', 'b', 'c'], 1);
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

  it('keys by identity id and returns the first server-ranked match', async () => {
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
    expect(result.current.getMatch('b')?.label).toBe('Bob');
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
});
