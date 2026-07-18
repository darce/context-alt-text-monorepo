import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useClusterSuggestions } from '../useClusterSuggestions';
import { PROJECTION_TOP_K } from '../suggestionProjection';
import * as recognitionApi from '../../../../api/recognition';

vi.mock('../../../../api/recognition', () => ({
  fetchIdentitiesSuggestions: vi.fn(),
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

  it('merges identity projection with label matches and preserves server arrival order', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    fetchIdentitiesSuggestionsMock.mockResolvedValue({
      matches: {
        'identity-1': [
          { cluster_id: 'c1', label: 'Alice', similarity: 0.9, identity_count: 3 },
          { cluster_id: 'c2', label: 'Albert', similarity: 0.8, identity_count: 10 },
          { cluster_id: 'c3', label: 'Bob', similarity: 0.7, identity_count: 2 },
        ],
      },
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

    await waitFor(() =>
      expect(fetchIdentitiesSuggestionsMock).toHaveBeenCalledWith(['identity-1'], PROJECTION_TOP_K),
    );
    await waitFor(() => expect(listRecognitionClustersMock).toHaveBeenCalled());
    const [params] = listRecognitionClustersMock.mock.calls[0] ?? [];
    expect(params).toEqual({ limit: 20, offset: 0, labeled_only: true, search: 'Al' });

    await waitFor(() => expect(result.current.options).toHaveLength(3));
    expect(result.current.options.map((option) => option.label)).toEqual(['Alice', 'Albert', 'Alana']);
    expect(result.current.options[0].group).toBe('Suggested');
    expect(result.current.options[0].value).toBe('c1');
    expect(result.current.options[2].group).toBe('All Labels');

    queryClient.clear();
  });

  it('preserves server arrival order for Suggested group (no client re-sort)', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    // Deliberately NOT similarity-desc: re-sort would yield Alice, Alicia, Alison.
    fetchIdentitiesSuggestionsMock.mockResolvedValue({
      matches: {
        'identity-1': [
          { cluster_id: 'cluster-alicia', label: 'Alicia', similarity: 0.81, identity_count: 5 },
          { cluster_id: 'cluster-alice', label: 'Alice', similarity: 0.92, identity_count: 12 },
          { cluster_id: 'cluster-alison', label: 'Alison', similarity: 0.7, identity_count: 2 },
        ],
      },
    });

    listRecognitionClustersMock.mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
    });

    const { result } = renderHook(
      () => useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput: '', debounceMs: 0 }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.options).toHaveLength(3));
    expect(result.current.options.map((option) => option.label)).toEqual(['Alicia', 'Alice', 'Alison']);
    expect(result.current.options.every((option) => option.group === 'Suggested')).toBe(true);

    queryClient.clear();
  });

  it('excludes the editable cluster from suggestions and exact label lookup', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    fetchIdentitiesSuggestionsMock.mockResolvedValue({
      matches: {
        'identity-1': [
          { cluster_id: 'cluster-self', label: 'Emilie Chartrand', similarity: 0.99, identity_count: 3 },
          { cluster_id: 'cluster-other', label: 'Emilie Chartrand Archive', similarity: 0.75, identity_count: 7 },
        ],
      },
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
        { ...baseCluster, id: 'cluster-self', label: 'Emilie Chartrand', identity_count: 3 },
        { ...baseCluster, id: 'cluster-other', label: 'Emilie Chartrand Archive', identity_count: 7 },
      ],
      limit: 20,
      total: 2,
      truncated: false,
    });

    const { result } = renderHook(
      () =>
        useClusterSuggestions({
          identityId: 'identity-1',
          enabled: true,
          labelInput: 'Emilie',
          debounceMs: 0,
          editableClusterId: 'cluster-self',
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.options).toHaveLength(1));
    expect(result.current.options[0]?.value).toBe('cluster-other');

    const exactMatch = await result.current.findClusterByLabel('Emilie Chartrand');
    expect(exactMatch).toBeNull();

    queryClient.clear();
  });
});
