import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  fetchTopUnlabeledClusters,
} from '../../../../api/recognition';
import { resetConfigCache } from '../../../../api/config';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import type {
  PendingMergeSuggestion,
  PendingNameSuggestion,
  PendingSuggestion,
  TopUnlabeledCluster,
} from '../../../../api/recognition/types';
import { fromPendingRow } from '../suggestionProjection';
import { buildSuggestionReviewItems } from '../suggestionReviewItems';
import {
  buildWorkbenchFindings,
  NEXT_ACTION_KIND,
  NONE_REASON,
  useWorkbenchFindings,
  type WorkbenchFindingsQueues,
  type WorkbenchFindingsSourceState,
} from '../useWorkbenchFindings';

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
  };
});

const makeSuggestion = (overrides: Partial<PendingSuggestion> = {}): PendingSuggestion => ({
  id: 'sugg-1',
  identity_id: 'identity-1',
  suggested_cluster_id: 'cluster-1',
  representative_similarity: 0.8,
  // Human-labeled by default so buildSuggestionReviewItems keeps the row (isHumanLabeledTarget).
  cluster_label: 'Default Label',
  ...overrides,
});

const makeReviewItems = (...rows: PendingSuggestion[]) =>
  buildSuggestionReviewItems(rows.map(fromPendingRow));

const makeMerge = (overrides: Partial<PendingMergeSuggestion> = {}): PendingMergeSuggestion => ({
  id: 'merge-1',
  cluster_a_id: 'cluster-a',
  cluster_b_id: 'cluster-b',
  similarity: 0.9,
  status: 'pending',
  ...overrides,
});

const makeName = (overrides: Partial<PendingNameSuggestion> = {}): PendingNameSuggestion => ({
  id: 'name-1',
  cluster_id: 'cluster-n',
  suggested_name: 'Ada Lovelace',
  confidence_score: 0.7,
  source: 'roster',
  created_at: '2026-06-05T00:00:00Z',
  expires_at: null,
  ...overrides,
});

const makeCluster = (overrides: Partial<TopUnlabeledCluster> = {}): TopUnlabeledCluster => ({
  id: 'top-1',
  tenant_id: 'test-tenant-id',
  label: null,
  is_labeled: false,
  is_auto_label: false,
  identity_count: 3,
  user_confirmed: false,
  representatives: [],
  ...overrides,
});

const makeQueues = (overrides: Partial<WorkbenchFindingsQueues> = {}): WorkbenchFindingsQueues => ({
  reviewItems: [],
  assignmentTotal: 0,
  mergeSuggestions: [],
  mergeTotal: 0,
  nameSuggestions: [],
  nameTotal: 0,
  topUnlabeledClusters: [],
  // Mirrors the hook fallback: server total defaults to the fetched page length.
  topUnlabeledTotal: overrides.topUnlabeledClusters?.length ?? 0,
  ...overrides,
});

const makeState = (overrides: Partial<WorkbenchFindingsSourceState> = {}): WorkbenchFindingsSourceState => ({
  assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
  nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
  topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
  isLoading: false,
  isError: false,
  queueSettled: true,
  ...overrides,
});

describe('buildWorkbenchFindings', () => {
  it('summarizes counts from queue totals and unlabeled cluster list', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(makeSuggestion()),
        assignmentTotal: 3,
        mergeSuggestions: [makeMerge()],
        mergeTotal: 2,
        nameSuggestions: [makeName()],
        nameTotal: 1,
        topUnlabeledClusters: [makeCluster(), makeCluster({ id: 'top-2', identity_count: 5 })],
      }),
      makeState(),
    );

    expect(model.counts).toEqual({
      assignments: 3,
      merges: 2,
      names: 1,
      unlabeledClusters: 2,
      total: 8,
    });
    expect(model.hasFindings).toBe(true);
  });

  // REV-A-01: counts must use server total, not the capped page length (TOP_UNLABELED_LIMIT=20).
  it('reports the server-side unlabeled total when it exceeds the fetched page', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [makeCluster()],
        topUnlabeledTotal: 25,
      }),
      makeState(),
    );

    expect(model.counts.unlabeledClusters).toBe(25);
    expect(model.counts.total).toBe(25);
    // Next action still targets the loaded page.
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'top-1' });
  });

  it('prioritizes the highest-score assignment suggestion as next action', () => {
    const low = makeSuggestion({ id: 'sugg-low', suggested_cluster_id: 'c-low', representative_similarity: 0.5 });
    const high = makeSuggestion({
      id: 'sugg-high',
      suggested_cluster_id: 'c-high',
      representative_similarity: 0.95,
      cluster_label: 'Grace Hopper',
    });
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(low, high),
        assignmentTotal: 2,
        mergeSuggestions: [makeMerge()],
        mergeTotal: 1,
        nameSuggestions: [makeName()],
        nameTotal: 1,
        topUnlabeledClusters: [makeCluster()],
      }),
      makeState(),
    );

    expect(model.nextAction).toEqual({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: 'sugg-high',
      clusterId: 'c-high',
      label: 'Grace Hopper',
    });
  });

  it('falls back to merge review when no assignment suggestions remain', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        mergeSuggestions: [makeMerge({ id: 'merge-7' })],
        mergeTotal: 1,
        nameSuggestions: [makeName()],
        nameTotal: 1,
        topUnlabeledClusters: [makeCluster()],
      }),
      makeState(),
    );

    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.MERGE, suggestionId: 'merge-7' });
  });

  it('falls back to name suggestion when assignment and merge queues are empty', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        nameSuggestions: [makeName({ id: 'name-9', cluster_id: 'cluster-9' })],
        nameTotal: 1,
        topUnlabeledClusters: [makeCluster()],
      }),
      makeState(),
    );

    expect(model.nextAction).toEqual({
      kind: NEXT_ACTION_KIND.NAME,
      suggestionId: 'name-9',
      clusterId: 'cluster-9',
    });
  });

  it('targets the unlabeled cluster with the highest identity_count last', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [
          makeCluster({ id: 'small', identity_count: 2 }),
          makeCluster({ id: 'large', identity_count: 9 }),
        ],
      }),
      makeState(),
    );

    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'large' });
  });

  it('returns a disabled empty action when no findings exist', () => {
    const model = buildWorkbenchFindings(makeQueues(), makeState());

    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY });
    expect(model.hasFindings).toBe(false);
    expect(model.counts.total).toBe(0);
  });

  it('reports loading state while initial queue data is pending', () => {
    const model = buildWorkbenchFindings(makeQueues(), makeState({ isLoading: true }));

    expect(model.isLoading).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.LOADING });
  });

  it('reports error state when the primary queues fail', () => {
    const model = buildWorkbenchFindings(makeQueues(), makeState({ isError: true }));

    expect(model.isError).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR });
  });

  it('reports unavailable state when the suggestion source is unavailable', () => {
    const model = buildWorkbenchFindings(
      makeQueues(),
      makeState({
        assignmentDataSource: DATA_SOURCE.UNAVAILABLE,
        topUnlabeledDataSource: DATA_SOURCE.UNAVAILABLE,
      }),
    );

    expect(model.isUnavailable).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.UNAVAILABLE });
  });

  // REV-A-03: name (and merge) outages must not hide the panel — only assignment + top-unlabeled
  // are canonical availability signals (partial summary is preferred over empty unavailable UI).
  it('does not mark unavailable when only the name data source is unavailable', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [makeCluster({ id: 'still-visible' })],
        topUnlabeledTotal: 1,
      }),
      makeState({ nameDataSource: DATA_SOURCE.UNAVAILABLE }),
    );

    expect(model.isUnavailable).toBe(false);
    expect(model.hasFindings).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'still-visible' });
  });

  it('marks findings read-only under backend-proxy projection while keeping the next action visible', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [makeCluster({ id: 'proxy-cluster', identity_count: 4 })],
      }),
      makeState({ topUnlabeledDataSource: DATA_SOURCE.BACKEND_PROXY }),
    );

    expect(model.isReadOnly).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'proxy-cluster' });
  });

  it('collects representative previews in priority order and drops entries without imagery', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({ identity_thumb_url: 'http://example.test/assign-thumb.jpg' }),
        ),
        assignmentTotal: 1,
        mergeSuggestions: [makeMerge({ cluster_a_representative_thumb_url: 'http://example.test/merge-thumb.jpg' })],
        mergeTotal: 1,
        nameSuggestions: [makeName()],
        nameTotal: 1,
        topUnlabeledClusters: [
          makeCluster({
            id: 'with-face',
            identity_count: 6,
            representatives: [
              { id: 'rep-1', media_id: 11, thumb_url: 'http://example.test/cluster-thumb.jpg', is_pinned: false },
            ],
          }),
          makeCluster({ id: 'no-face', identity_count: 2 }),
        ],
      }),
      makeState(),
    );

    expect(model.previews.map((preview) => preview.key)).toEqual([
      'assignment-sugg-1',
      'merge-merge-1',
      'cluster-with-face',
    ]);
    expect(model.previews[0].thumbUrl).toBe('http://example.test/assign-thumb.jpg');
  });
});

describe('useWorkbenchFindings', () => {
  let queryClient: QueryClient | undefined;

  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        recognitionSuggestions: 'http://example.test/recognition/suggestions',
        recognitionMergeSuggestions: 'http://example.test/recognition/suggestions/merge',
        recognitionNameSuggestions: 'http://example.test/recognition/suggestions/name',
        recognitionBulkAcceptSuggestions: 'http://example.test/recognition/suggestions/bulk-accept',
        recognitionClusters: 'http://example.test/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    };
    resetConfigCache();
  });

  afterEach(() => {
    void queryClient?.cancelQueries();
    queryClient?.clear();
    cleanup();
    vi.clearAllMocks();
  });

  it('derives the view model from live suggestion review queries', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [makeSuggestion({ id: 'live-sugg', suggested_cluster_id: 'live-cluster' })],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [makeCluster()],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useWorkbenchFindings(), { wrapper });

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.counts).toEqual({
      assignments: 1,
      merges: 0,
      names: 0,
      unlabeledClusters: 1,
      total: 2,
    });
    expect(result.current.nextAction).toEqual({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: 'live-sugg',
      clusterId: 'live-cluster',
      label: 'Default Label',
    });
    expect(result.current.isReadOnly).toBe(false);
  });

  // REV-A-01 (hook path): total-backed count must flow from useSuggestionReviewQueries
  // through useWorkbenchFindings — page length alone under-reports the backlog.
  it('uses topUnlabeledQuery total for unlabeledClusters when total exceeds the fetched page', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    // Fetched page is capped (1 item here); server total is higher.
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [makeCluster({ id: 'page-head', identity_count: 8 })],
      limit: 20,
      total: 42,
      truncated: true,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useWorkbenchFindings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    // Would fail against old code that used topUnlabeledClusters.length (page size).
    expect(result.current.counts.unlabeledClusters).toBe(42);
    expect(result.current.counts.total).toBe(42);
    expect(result.current.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'page-head' });
  });

  // REV-A-03 (isError): Locks the !hasAnyData guard — BOTH primary queries
  // (assignment + merge) fail, so without the guard isError would flip true, but
  // top-unlabeled data still renders as a partial summary.
  it('degrades gracefully on partial query failure instead of surfacing an error', async () => {
    vi.mocked(fetchPendingSuggestions).mockRejectedValue(new Error('assignment endpoint down'));
    vi.mocked(fetchPendingMergeSuggestions).mockRejectedValue(new Error('merge endpoint down'));
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [makeCluster()],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useWorkbenchFindings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isError).toBe(false);
    expect(result.current.hasFindings).toBe(true);
    expect(result.current.counts.unlabeledClusters).toBe(1);
    expect(result.current.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'top-1' });
  });

  // REV-A-02: useWorkbenchFindings must not wrap buildWorkbenchFindings in useMemo over
  // freshly-allocated query fallback arrays (that memo was a no-op). Rebuild is cheap;
  // the hook still returns a coherent view model every render.
  it('rebuilds a coherent view model each render without relying on unstable memo deps', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [makeSuggestion({ id: 'memo-sugg', suggested_cluster_id: 'memo-cluster' })],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [makeCluster({ id: 'memo-cluster-top' })],
      limit: 20,
      total: 3,
      truncated: true,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result, rerender } = renderHook(() => useWorkbenchFindings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    rerender();
    const second = result.current;

    // REV-A-02 (no-op useMemo) is enforced by review, not by this test: a no-op
    // memo is behaviorally invisible, and pinning object identity would
    // spuriously fail if a correctly-stable memo were ever added. This test
    // only pins rerender consistency of the view model.
    expect(second.counts).toEqual({
      assignments: 1,
      merges: 0,
      names: 0,
      unlabeledClusters: 3,
      total: 4,
    });
    expect(second.nextAction).toEqual({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: 'memo-sugg',
      clusterId: 'memo-cluster',
      label: 'Default Label',
    });
  });
});
