import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as buildNamingOptionsModule from '../buildNamingOptions';
import {
  NAMING_GROUP_ALL_LABELS,
  NAMING_GROUP_SUGGESTED,
  namingOptionValue,
} from '../buildNamingOptions';
import {
  resolveClusterMatchFromOptions,
  selectClusterSuggestions,
  useClusterSuggestions,
} from '../useClusterSuggestions';
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
      { label: 'Alice', group: NAMING_GROUP_SUGGESTED, source: 'cluster' },
      { label: 'alice', group: NAMING_GROUP_ALL_LABELS, source: 'person' },
      { label: 'Bob', group: NAMING_GROUP_ALL_LABELS, source: 'cluster' },
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
    expect(options[0]).toMatchObject({ label: 'Alice', group: NAMING_GROUP_SUGGESTED, source: 'cluster' });
    expect(options[1]).toMatchObject({ label: 'Alice', group: NAMING_GROUP_ALL_LABELS, source: 'person' });
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

  it('threads ProjectedSuggestion.suggestionId onto option.suggestion_id (BR-16)', () => {
    // Predicted first failure: suggestion_id undefined when only camelCase suggestionId present
    const options = selectClusterSuggestions({
      identityProjection: [
        {
          identityId: 'i1',
          clusterId: 'c1',
          label: 'Alice',
          similarity: 0.9,
          identityCount: 2,
          suggestionId: 'sug-from-projection',
        },
      ],
      namingOptions: [],
    });
    expect(options).toHaveLength(1);
    expect(options[0]?.suggestion_id).toBe('sug-from-projection');
  });

  it('resolveClusterMatchFromOptions maps option.suggestion_id → match.suggestionId (L1V-01 free-type)', () => {
    // Predicted first failure: match = { id, label, identityCount } with no suggestionId —
    // free-typed suggested label would merge without acceptSuggestion.
    const options = selectClusterSuggestions({
      identityProjection: [
        {
          identityId: 'i1',
          clusterId: 'c-alice',
          label: 'Alice',
          similarity: 0.91,
          identityCount: 4,
          suggestionId: 'sug-free-type-1',
        },
      ],
      namingOptions: [],
    });
    expect(options[0]?.suggestion_id).toBe('sug-free-type-1');

    const match = resolveClusterMatchFromOptions(options, 'Alice');
    expect(match).toEqual({
      id: 'c-alice',
      label: 'Alice',
      identityCount: 4,
      suggestionId: 'sug-free-type-1',
    });
    // Case-insensitive free-type of the same suggested label also keeps the id.
    expect(resolveClusterMatchFromOptions(options, 'alice')?.suggestionId).toBe('sug-free-type-1');
  });

  it('resolveClusterMatchFromOptions omits suggestionId when option has none', () => {
    const match = resolveClusterMatchFromOptions(
      [
        {
          value: namingOptionValue('cluster', 'c-bob'),
          label: 'Bob',
          source: 'cluster',
          identityCount: 2,
        },
      ],
      'Bob',
    );
    expect(match).toEqual({ id: 'c-bob', label: 'Bob', identityCount: 2, suggestionId: undefined });
  });

  it('BR-17: empty-label filter + section-2 search filter/dedupe with non-zero clusters', () => {
    // Predicted first failure: empty/whitespace identity labels appear; All Labels includes
    // search miss (Bob) or duplicate Alice cluster not suppressed by Suggested.
    const options = selectClusterSuggestions({
      identityProjection: [
        {
          identityId: 'i0',
          clusterId: 'c-empty',
          label: '',
          similarity: 0.99,
          identityCount: 1,
        },
        {
          identityId: 'i1',
          clusterId: 'c1',
          label: 'Alice',
          similarity: 0.9,
          identityCount: 2,
        },
        {
          identityId: 'i2',
          clusterId: 'c-ws',
          label: '   ',
          similarity: 0.88,
          identityCount: 1,
        },
        {
          identityId: 'i3',
          clusterId: 'c2',
          label: 'Alicia',
          similarity: 0.7,
          identityCount: 3,
        },
      ],
      namingOptions: [
        {
          value: namingOptionValue('cluster', 'c3'),
          label: 'Alice',
          source: 'cluster',
          identityCount: 4,
        },
        {
          value: namingOptionValue('cluster', 'c4'),
          label: 'Albert',
          source: 'cluster',
          identityCount: 5,
        },
        {
          value: namingOptionValue('cluster', 'c5'),
          label: 'Bob',
          source: 'cluster',
          identityCount: 6,
        },
        { value: namingOptionValue('person', 1), label: 'Alana', source: 'person' },
      ],
      labelInput: 'Al',
    });

    expect(options.map((option) => ({ label: option.label, group: option.group, source: option.source }))).toEqual([
      { label: 'Alice', group: NAMING_GROUP_SUGGESTED, source: 'cluster' },
      { label: 'Alicia', group: NAMING_GROUP_SUGGESTED, source: 'cluster' },
      { label: 'Albert', group: NAMING_GROUP_ALL_LABELS, source: 'cluster' },
      { label: 'Alana', group: NAMING_GROUP_ALL_LABELS, source: 'person' },
    ]);
    expect(options.some((option) => option.label === 'Bob')).toBe(false);
    expect(options.some((option) => option.value === namingOptionValue('cluster', 'c-empty'))).toBe(false);
    expect(options.some((option) => option.value === namingOptionValue('cluster', 'c3'))).toBe(false);
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
    expect(result.current.options[0].group).toBe(NAMING_GROUP_SUGGESTED);
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
    expect(result.current.options.every((option) => option.group === NAMING_GROUP_SUGGESTED)).toBe(true);

    queryClient.clear();
  });

  it('free-typed suggested label findClusterByLabel returns suggestionId (L1V-01 → acceptSuggestion)', async () => {
    // Free-type Save calls findClusterByLabel; without suggestionId on the match the
    // merge hop never calls acceptSuggestion and the pending row stays open.
    // Predicted first failure: match.suggestionId undefined despite option.suggestion_id.
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

    fetchIdentitiesSuggestionsMock.mockResolvedValue({
      matches: {
        'identity-1': [
          {
            cluster_id: 'cluster-alice',
            label: 'Alice',
            similarity: 0.95,
            identity_count: 3,
            suggestion_id: 'sug-free-type-api',
          },
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

    await waitFor(() => expect(result.current.options).toHaveLength(1));
    expect(result.current.options[0]?.suggestion_id).toBe('sug-free-type-api');

    const match = await result.current.findClusterByLabel('Alice');
    expect(match).toEqual({
      id: 'cluster-alice',
      label: 'Alice',
      identityCount: 3,
      suggestionId: 'sug-free-type-api',
    });

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

  it('namedMatches filter keeps null-labeled ClusterSummary out of naming options (BR-53)', async () => {
    // Real hook (unmocked loader): API returns one null-labeled row + one named row.
    // Options contain the named row only; spy asserts namedMatches filtered before buildNamingOptions
    // (buildNamingOptions itself null-skips, so options alone cannot red-proof the loader filter).
    const { wrapper, queryClient } = createWrapper();
    const fetchIdentitiesSuggestionsMock = vi.mocked(recognitionApi.fetchIdentitiesSuggestions);
    const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);
    const buildSpy = vi.spyOn(buildNamingOptionsModule, 'buildNamingOptions');

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
        { ...baseCluster, id: 'null-label-row', label: null, identity_count: 1 },
        { ...baseCluster, id: 'named-row', label: 'Named Match', identity_count: 2 },
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
          labelInput: 'Na',
          debounceMs: 0,
        }),
      { wrapper },
    );

    await waitFor(() =>
      expect(result.current.options.some((option) => option.label === 'Named Match')).toBe(true),
    );
    expect(result.current.options.every((option) => typeof option.label === 'string' && option.label !== '')).toBe(
      true,
    );
    expect(result.current.options.some((option) => option.value === namingOptionValue('cluster', 'null-label-row'))).toBe(
      false,
    );

    const labelMatchArgs = buildSpy.mock.calls
      .map((call) => call[0]?.labelMatches ?? [])
      .find((rows) => rows.some((row) => row.id === 'named-row'));
    expect(labelMatchArgs).toBeDefined();
    expect(labelMatchArgs?.every((row) => typeof row.label === 'string' && row.label !== '')).toBe(true);
    expect(labelMatchArgs?.some((row) => row.id === 'null-label-row')).toBe(false);
    expect(labelMatchArgs?.map((row) => row.id)).toEqual(['named-row']);

    buildSpy.mockRestore();
    queryClient.clear();
  });

  describe('TEST-15 at-rest labelled clusters (E21-16)', () => {
    const baseCluster = {
      member_ids: [],
      representative_identity: {
        media_id: null,
        bbox: { x: 0, y: 0, width: 0, height: 0 },
      },
      sample_identities: [],
    };

    const mockEmptySuggestions = () => {
      vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({
        matches: { 'identity-1': [] },
      });
    };

    it('renders a labelled cluster at rest with no matching roster person', async () => {
      // Predicted first failure (pre-fix): Tory Guzman absent — labelled search
      // is disabled until 2+ chars, so at-rest union is suggestions + roster only.
      const { wrapper, queryClient } = createWrapper();
      mockEmptySuggestions();
      const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);
      listRecognitionClustersMock.mockResolvedValue({
        clusters: [{ ...baseCluster, id: 'cluster-tory', label: 'Tory Guzman', identity_count: 4 }],
        limit: 50,
        total: 1,
        truncated: false,
      });

      const { result } = renderHook(
        () => useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput: '', debounceMs: 0 }),
        { wrapper },
      );

      await waitFor(() =>
        expect(result.current.options.some((option) => option.label === 'Tory Guzman')).toBe(true),
      );
      expect(result.current.options.some((option) => option.source === 'person' && option.label === 'Tory Guzman')).toBe(
        false,
      );
      expect(
        result.current.options.some(
          (option) => option.value === namingOptionValue('cluster', 'cluster-tory') && option.group === NAMING_GROUP_ALL_LABELS,
        ),
      ).toBe(true);
      expect(listRecognitionClustersMock).toHaveBeenCalledWith({
        limit: 50,
        offset: 0,
        labeled_only: true,
      });

      queryClient.clear();
    });

    it('does not render auto cluster-* labels from the at-rest labelled list', async () => {
      // Predicted first failure (pre-fix): human-labelled sibling missing at rest;
      // after an unfiltered at-rest fetch, cluster-1234 would also leak.
      const { wrapper, queryClient } = createWrapper();
      mockEmptySuggestions();
      const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);
      listRecognitionClustersMock.mockResolvedValue({
        clusters: [
          { ...baseCluster, id: 'auto-1', label: 'cluster-1234', identity_count: 1 },
          { ...baseCluster, id: 'human-1', label: 'Dana Ruiz', identity_count: 2 },
        ],
        limit: 50,
        total: 2,
        truncated: false,
      });

      const { result } = renderHook(
        () => useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput: '', debounceMs: 0 }),
        { wrapper },
      );

      await waitFor(() =>
        expect(result.current.options.some((option) => option.label === 'Dana Ruiz')).toBe(true),
      );
      expect(result.current.options.every((option) => !String(option.label).startsWith('cluster-'))).toBe(true);
      expect(result.current.options.some((option) => option.value === namingOptionValue('cluster', 'auto-1'))).toBe(
        false,
      );

      queryClient.clear();
    });

    it('still triggers the >=2-char search query and merges those hits', async () => {
      // Predicted first failure (pre-fix): at-rest Tory never appears. Search path
      // must keep firing with the typed term so totals beyond the at-rest page merge.
      const { wrapper, queryClient } = createWrapper();
      mockEmptySuggestions();
      const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);
      listRecognitionClustersMock.mockImplementation(async (params) => {
        if (params?.search && params.search.length >= 2) {
          return {
            clusters: [{ ...baseCluster, id: 'cluster-maya', label: 'Maya Chen', identity_count: 3 }],
            limit: 20,
            total: 1,
            truncated: false,
          };
        }
        return {
          clusters: [{ ...baseCluster, id: 'cluster-tory', label: 'Tory Guzman', identity_count: 4 }],
          limit: 50,
          total: 1,
          truncated: false,
        };
      });

      const { result, rerender } = renderHook(
        ({ labelInput }: { labelInput: string }) =>
          useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput, debounceMs: 0 }),
        { wrapper, initialProps: { labelInput: '' } },
      );

      await waitFor(() =>
        expect(result.current.options.some((option) => option.label === 'Tory Guzman')).toBe(true),
      );

      rerender({ labelInput: 'Ma' });

      await waitFor(() =>
        expect(listRecognitionClustersMock).toHaveBeenCalledWith({
          limit: 20,
          offset: 0,
          labeled_only: true,
          search: 'Ma',
        }),
      );
      await waitFor(() =>
        expect(result.current.options.some((option) => option.label === 'Maya Chen')).toBe(true),
      );

      queryClient.clear();
    });

    it('threads envelope total/truncated instead of deriving them from page length (REV1-01)', async () => {
      const { wrapper, queryClient } = createWrapper();
      mockEmptySuggestions();
      const page = Array.from({ length: 50 }, (_, index) => ({
        ...baseCluster,
        id: `cluster-${index}`,
        label: `Label ${index}`,
        identity_count: 1,
      }));
      vi.mocked(recognitionApi.listRecognitionClusters).mockResolvedValue({
        clusters: page,
        limit: 50,
        total: 80,
        truncated: true,
      });

      const { result } = renderHook(
        () => useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput: '', debounceMs: 0 }),
        { wrapper },
      );

      await waitFor(() => expect(result.current.atRestTruncated).toBe(true));
      expect(result.current.atRestTotal).toBe(80);
      expect(result.current.atRestShown).toBe(50);
      expect(result.current.atRestTotal).not.toBe(result.current.atRestShown);

      queryClient.clear();
    });

    it('excludes editableClusterId from the at-rest labelled list', async () => {
      // Predicted first failure (pre-fix): neither at-rest row appears. After the
      // at-rest fetch, the editable cluster must stay out of the assign dropdown.
      const { wrapper, queryClient } = createWrapper();
      mockEmptySuggestions();
      const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);
      listRecognitionClustersMock.mockResolvedValue({
        clusters: [
          { ...baseCluster, id: 'cluster-self', label: 'Tory Guzman', identity_count: 4 },
          { ...baseCluster, id: 'cluster-other', label: 'Pat Nguyen', identity_count: 6 },
        ],
        limit: 50,
        total: 2,
        truncated: false,
      });

      const { result } = renderHook(
        () =>
          useClusterSuggestions({
            identityId: 'identity-1',
            enabled: true,
            labelInput: '',
            debounceMs: 0,
            editableClusterId: 'cluster-self',
          }),
        { wrapper },
      );

      await waitFor(() =>
        expect(result.current.options.some((option) => option.label === 'Pat Nguyen')).toBe(true),
      );
      expect(result.current.options.some((option) => option.value === namingOptionValue('cluster', 'cluster-self'))).toBe(
        false,
      );
      expect(result.current.options.some((option) => option.label === 'Tory Guzman')).toBe(false);

      queryClient.clear();
    });

    it('keeps the at-rest labelled page visible while the first search is in flight (REV1-02)', async () => {
      // Predicted first failure (pre-fix): after debounce flips isAtRestMode, the
      // search observer has never fetched, so labelMatches ?? [] blanks the list.
      // Assert after the flip and before the deferred search resolves — asserting
      // before debounce is tautological (at-rest mode is still active).
      const { wrapper, queryClient } = createWrapper();
      mockEmptySuggestions();
      const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);

      type ClusterListResponse = Awaited<ReturnType<typeof recognitionApi.listRecognitionClusters>>;
      let resolveSearch!: (value: ClusterListResponse) => void;
      const pendingSearch = new Promise<ClusterListResponse>((resolve) => {
        resolveSearch = resolve;
      });

      listRecognitionClustersMock.mockImplementation((params) => {
        if (params?.search && String(params.search).length >= 2) {
          return pendingSearch;
        }
        return Promise.resolve({
          clusters: [{ ...baseCluster, id: 'cluster-tory', label: 'Tory Guzman', identity_count: 4 }],
          limit: 50,
          total: 1,
          truncated: false,
        });
      });

      const { result, rerender } = renderHook(
        ({ labelInput }: { labelInput: string }) =>
          useClusterSuggestions({ identityId: 'identity-1', enabled: true, labelInput, debounceMs: 300 }),
        { wrapper, initialProps: { labelInput: '' } },
      );

      await waitFor(() =>
        expect(result.current.options.some((option) => option.label === 'Tory Guzman')).toBe(true),
      );
      expect(result.current.isAtRestMode).toBe(true);

      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      rerender({ labelInput: 'To' });
      expect(result.current.isAtRestMode).toBe(true);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(result.current.isAtRestMode).toBe(false);
      expect(result.current.options.some((option) => option.label === 'Tory Guzman')).toBe(true);
      expect(
        result.current.options.some((option) => option.value === namingOptionValue('cluster', 'cluster-tory')),
      ).toBe(true);

      vi.useRealTimers();
      resolveSearch({
        clusters: [{ ...baseCluster, id: 'cluster-tova', label: 'Tova Lin', identity_count: 3 }],
        limit: 20,
        total: 1,
        truncated: false,
      });

      await waitFor(() =>
        expect(result.current.options.some((option) => option.label === 'Tova Lin')).toBe(true),
      );
      expect(result.current.options.some((option) => option.label === 'Tory Guzman')).toBe(false);

      queryClient.clear();
    });
  });
});
