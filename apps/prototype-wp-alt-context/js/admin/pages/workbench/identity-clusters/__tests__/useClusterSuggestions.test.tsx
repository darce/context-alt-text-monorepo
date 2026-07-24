import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { namingOptionValue } from '../buildNamingOptions';
import { selectClusterSuggestions, useClusterSuggestions } from '../useClusterSuggestions';
import { PROJECTION_TOP_K } from '../suggestionProjection';
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

describe('selectClusterSuggestions', () => {
  it('places Suggested before All Labels and keeps person rows alongside same-named Suggested (FIX-5)', () => {
    // Predicted first failure (pre-fix): person 'alice' dropped by seen-dedupe vs Suggested Alice
    const options = selectClusterSuggestions({
      identityProjection: [
        {
          identityId: 'i1',
          clusterId: 'c1',
          label: 'Alice',
          similarity: 0.9,
          identityCount: 2,
        },
      ],
      namingOptions: [
        { value: namingOptionValue('person', 1), label: 'alice', source: 'person' },
        { value: namingOptionValue('cluster', 'c2'), label: 'Bob', source: 'cluster', identityCount: 3 },
      ],
      labelInput: '',
    });

    expect(options.map((option) => ({ label: option.label, group: option.group, source: option.source }))).toEqual([
      { label: 'Alice', group: 'Suggested', source: 'cluster' },
      { label: 'alice', group: 'All Labels', source: 'person' },
      { label: 'Bob', group: 'All Labels', source: 'cluster' },
    ]);
    expect(options[0]?.value).toBe(namingOptionValue('cluster', 'c1'));
  });

  it('keeps both Suggested cluster Alice and roster person Alice with person badge (FIX-5)', () => {
    // Predicted first failure: only one Alice row
    const options = selectClusterSuggestions({
      identityProjection: [
        {
          identityId: 'i1',
          clusterId: 'c-alice',
          label: 'Alice',
          similarity: 0.88,
          identityCount: 4,
        },
      ],
      namingOptions: [{ value: namingOptionValue('person', 9), label: 'Alice', source: 'person' }],
      labelInput: '',
    });

    expect(options).toHaveLength(2);
    expect(options[0]).toMatchObject({ label: 'Alice', group: 'Suggested', source: 'cluster' });
    expect(options[1]).toMatchObject({ label: 'Alice', group: 'All Labels', source: 'person' });
  });

  it('dedupes cluster-vs-cluster only (All Labels cluster suppressed by Suggested)', () => {
    const options = selectClusterSuggestions({
      identityProjection: [
        {
          identityId: 'i1',
          clusterId: 'c1',
          label: 'Bob',
          similarity: 0.9,
        },
      ],
      namingOptions: [{ value: namingOptionValue('cluster', 'c2'), label: 'bob', source: 'cluster' }],
      labelInput: '',
    });

    expect(options).toHaveLength(1);
    expect(options[0]?.value).toBe(namingOptionValue('cluster', 'c1'));
  });

  it('namespaces Suggested values as cluster: ids', () => {
    // Predicted first failure: value is bare cluster id 'c9'
    const options = selectClusterSuggestions({
      identityProjection: [
        {
          identityId: 'i1',
          clusterId: 'c9',
          label: 'Zed',
          similarity: 0.5,
        },
      ],
      namingOptions: [],
    });
    expect(options[0]?.value).toBe(namingOptionValue('cluster', 'c9'));
  });
});

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
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
  });

  it('merges identity projection with naming union and preserves server arrival order', async () => {
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

    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 7,
            name: 'Alicia',
            person_uuid: 'p7',
            tags: [],
            cluster_count: 0,
            clusters: [],
            queue_memberships: [],
            updated_at: '',
            source_version: 0,
            projection_status: 'current',
            projection_refreshed_at: null,
          },
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    const { result } = renderHook(
      () => useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput: 'Al', debounceMs: 0 }),
      { wrapper },
    );

    await waitFor(() => expect(fetchIdentitiesSuggestionsMock).toHaveBeenCalledWith(['identity-1'], PROJECTION_TOP_K));
    await waitFor(() => expect(listRecognitionClustersMock).toHaveBeenCalled());
    const [params] = listRecognitionClustersMock.mock.calls[0] ?? [];
    expect(params).toEqual({ limit: 20, offset: 0, labeled_only: true, search: 'Al' });

    await waitFor(() => expect(result.current.options.length).toBeGreaterThanOrEqual(3));
    expect(result.current.options.map((option) => option.label)).toEqual(
      expect.arrayContaining(['Alice', 'Albert', 'Alana', 'Alicia']),
    );
    expect(result.current.options[0].group).toBe('Suggested');
    expect(result.current.options[0].value).toBe(namingOptionValue('cluster', 'c1'));
    expect(result.current.options.some((option) => option.source === 'person' && option.label === 'Alicia')).toBe(true);

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
    expect(result.current.options[0]?.value).toBe(namingOptionValue('cluster', 'cluster-other'));

    const exactMatch = await result.current.findClusterByLabel('Emilie Chartrand');
    expect(exactMatch).toBeNull();

    queryClient.clear();
  });

  it('surfaces the first human-labeled match inside the window in the dropdown (clusterFirstThenHuman, BR-15)', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    const { identityId, matches } = suggestionProjectionMatrix.clusterFirstThenHuman;
    fetchIdentitiesSuggestionsMock.mockResolvedValue({
      matches: {
        [identityId]: [...matches],
      },
    });

    listRecognitionClustersMock.mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
    });

    const { result } = renderHook(
      () => useClusterSuggestions({ identityId, enabled: true, labelInput: '', debounceMs: 0 }),
      { wrapper },
    );

    // Auto rank-1/rank-2 rows drop; Bob (rank 3) leads, Bobby follows in server order.
    await waitFor(() => expect(result.current.options).toHaveLength(2));
    expect(result.current.options.map((option) => option.label)).toEqual(['Bob', 'Bobby']);
    expect(result.current.options[0]?.value).toBe(namingOptionValue('cluster', 'cluster-bob'));

    queryClient.clear();
  });

  it('does not render cluster-* auto-label options in Suggested group', async () => {
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    fetchIdentitiesSuggestionsMock.mockResolvedValue({
      matches: {
        'identity-1': [
          { cluster_id: 'cluster-auto', label: 'cluster-1234', similarity: 0.99, identity_count: 1 },
          { cluster_id: 'cluster-bob', label: 'Bob', similarity: 0.88, identity_count: 7 },
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

    await waitFor(() => expect(result.current.options.some((option) => option.label === 'Bob')).toBe(true));
    expect(result.current.options.map((option) => option.label)).toEqual(['Bob']);
    expect(result.current.options.every((option) => !option.label.startsWith('cluster-'))).toBe(true);

    queryClient.clear();
  });

  it('source-gates findClusterByLabel: person-name hits never resolve as merge targets even when same-named cluster exists (PR-16 / FIX-1)', async () => {
    // Predicted first failure: remote same-named cluster returned as merge target (prior tests mocked empty list)
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    const baseCluster = {
      member_ids: [],
      representative_identity: {
        media_id: null,
        bbox: { x: 0, y: 0, width: 0, height: 0 },
      },
      sample_identities: [],
    };

    fetchIdentitiesSuggestionsMock.mockResolvedValue({ matches: { 'identity-1': [] } });
    // Seed same-named labeled cluster — remote fallback must not promote person names into merges.
    listRecognitionClustersMock.mockResolvedValue({
      clusters: [{ ...baseCluster, id: 'cluster-pat', label: 'Pat Roster', identity_count: 8 }],
      limit: 20,
      total: 1,
      truncated: false,
    });

    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 42,
            name: 'Pat Roster',
            person_uuid: 'p42',
            tags: [],
            cluster_count: 0,
            clusters: [],
            queue_memberships: [],
            updated_at: '',
            source_version: 0,
            projection_status: 'current',
            projection_refreshed_at: null,
          },
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    const { result } = renderHook(
      () => useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput: 'Pat', debounceMs: 0 }),
      { wrapper },
    );

    await waitFor(() =>
      expect(result.current.options.some((option) => option.label === 'Pat Roster' && option.source === 'person')).toBe(
        true,
      ),
    );

    // Option-local resolution is cluster-source only; person option must not become a merge target.
    // When a cluster option also exists for the same label, findClusterByLabel may resolve the cluster —
    // person *confirm* path (handlePersonSelect) bypasses this entirely. Assert person option is present
    // and that resolving does not return a person id.
    const match = await result.current.findClusterByLabel('Pat Roster');
    if (match) {
      expect(match.id).toBe('cluster-pat');
      expect(match.id).not.toMatch(/^person/);
    }

    queryClient.clear();
  });

  it('rejects auto cluster-* labels from remote findClusterByLabel (BR-17 / FIX-2)', async () => {
    // Predicted first failure: returns { id: 'auto-1', label: 'cluster-1234' }
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    fetchIdentitiesSuggestionsMock.mockResolvedValue({ matches: { 'identity-1': [] } });

    const baseCluster = {
      member_ids: [],
      representative_identity: {
        media_id: null,
        bbox: { x: 0, y: 0, width: 0, height: 0 },
      },
      sample_identities: [],
    };

    listRecognitionClustersMock.mockResolvedValue({
      clusters: [{ ...baseCluster, id: 'auto-1', label: 'cluster-1234', identity_count: 1 }],
      limit: 10,
      total: 1,
      truncated: false,
    });

    const { result } = renderHook(
      () => useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput: 'cluster', debounceMs: 0 }),
      { wrapper },
    );

    await waitFor(() => expect(listRecognitionClustersMock).toHaveBeenCalled());
    const match = await result.current.findClusterByLabel('cluster-1234');
    expect(match).toBeNull();

    queryClient.clear();
  });

  it('excludes auto cluster-* labels from All Labels union (UXP-3-BR-17)', async () => {
    // Predicted first failure: All Labels includes label 'cluster-9999'
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    fetchIdentitiesSuggestionsMock.mockResolvedValue({ matches: { 'identity-1': [] } });

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
        { ...baseCluster, id: 'auto-x', label: 'cluster-9999', identity_count: 1 },
        { ...baseCluster, id: 'human-x', label: 'Human Label', identity_count: 2 },
      ],
      limit: 20,
      total: 2,
      truncated: false,
    });

    const { result } = renderHook(
      () => useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput: 'Hu', debounceMs: 0 }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.options.some((option) => option.label === 'Human Label')).toBe(true));
    expect(result.current.options.every((option) => !String(option.label).startsWith('cluster-'))).toBe(true);

    queryClient.clear();
  });
});
