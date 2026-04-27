import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useClusterSuggestions } from '../useClusterSuggestions';
import * as recognitionApi from '../../../../api/recognition';

vi.mock('../../../../api/recognition', () => ({
  fetchIdentitySuggestions: vi.fn(),
  listRecognitionClusters: vi.fn(),
}));

describe('useClusterSuggestions', () => {
  const createWrapper = () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { wrapper, queryClient };
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('merges identity suggestions with label matches and sorts by similarity', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitySuggestionsMock = vi.mocked(recognitionApi.fetchIdentitySuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    fetchIdentitySuggestionsMock.mockResolvedValue({
      matches: [
        { cluster_id: 'c1', label: 'Alice', similarity: 0.9, identity_count: 3 },
        { cluster_id: 'c2', label: 'Albert', similarity: 0.8, identity_count: 10 },
        { cluster_id: 'c3', label: 'Bob', similarity: 0.7, identity_count: 2 },
      ],
    });

    const baseCluster = {
      member_ids: [],
      representative_identity: {
        media_id: null,
        bbox: { x: 0, y: 0, width: 0, height: 0 },
      },
      sample_identities: [],
    };

    listRecognitionClustersMock.mockResolvedValue({
      clusters: [
        { ...baseCluster, id: 'c2', label: 'Albert', identity_count: 10 },
        { ...baseCluster, id: 'c4', label: 'Alana', identity_count: 5 },
      ],
      limit: 20,
      total: 2,
      truncated: false,
    });

    const { result } = renderHook(
      () => useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput: 'Al', debounceMs: 0 }),
      { wrapper },
    );

    await waitFor(() => expect(fetchIdentitySuggestionsMock).toHaveBeenCalledWith('identity-1', 5));
    await waitFor(() => expect(listRecognitionClustersMock).toHaveBeenCalled());
    const [params] = listRecognitionClustersMock.mock.calls[0] ?? [];
    expect(params).toEqual({ limit: 20, offset: 0, labeled_only: true, search: 'Al' });

    await waitFor(() => expect(result.current.options).toHaveLength(3));
    expect(result.current.options.map((option) => option.label)).toEqual(['Alice', 'Albert', 'Alana']);
    expect(result.current.options[0].group).toBe('Suggested');
    expect(result.current.options[2].group).toBe('All Labels');

    queryClient.clear();
  });
});
