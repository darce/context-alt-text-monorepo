/**
 * operator115 terminal-404 read budget (c82 FIR115, RED-first).
 *
 * A merge-suggestion accept for a persisted identity suggestion ID is looked up in
 * the cluster merge table and returns 404. The mutation error path then calls
 * invalidateQueries on every label/read key, so each mounted identity batch
 * refetches. That fanout is the executed cause this module pins; the upstream 429
 * is not reproduced here.
 *
 * Drives the real useClusterMutations -> useClusterLabelMutations stack, a real
 * QueryClient, real identity batch observers and the real fetchIdentitiesSuggestions
 * request path. Only HTTP is scripted.
 *
 * RED: the unrelated-batch read budget tests fail on the current tree.
 * Controls (cached choices, single error, no whole-cluster fallback, healthy success,
 * ambiguous transport) pass and must keep passing after the production fix.
 */
import { useQueries } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor, type RenderHookResult } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import { fetchIdentitiesSuggestions } from '../../../../api/recognition';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { identityBatchIdsKey } from '../suggestionProjection';
import { useClusterMutations } from '../useClusterMutations';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text.replace(/%((\d+)\$)?[sd]/g, (_match, _position, explicit) =>
      String(values[explicit ? Number(explicit) - 1 : index++] ?? ''));
  },
}));
vi.mock('../../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

const EDITABLE_CLUSTER_ID = '26d1cacb-351d-4e52-a007-f130764ba758';
const TARGET_CLUSTER_ID = '0a6dbdcb-5191-4f63-9d9f-63f375149ee8';
const OTHER_CLUSTER_ID = '5a1e0c00-0000-4000-8000-0000000000e1';
const PENDING_SUGGESTION_ID = '19697519-6950-4743-8305-8105584652f9';
const AFFECTED_IDENTITY_ID = 'adcde572-ce74-446a-86e7-970865e533d8';
const UNRELATED_IDENTITY_IDS = [
  '42dee0f3-0abe-4705-8ef2-c19dbf90fa9a',
  'fd5082a4-8411-4de3-9f97-fefa66f02597',
  'a387e141-e9b4-446a-ad89-eb948db93d99',
  '451236e0-2037-49eb-9085-4a428f202b44',
  'f7d636df-69b4-4c84-8863-5c3c8a60d580',
  'c8bba863-b1c4-4f8e-877f-71e527c66c95',
];
const ALL_IDENTITY_IDS = [AFFECTED_IDENTITY_ID, ...UNRELATED_IDENTITY_IDS];

const IDENTITY_ROUTE = '/wp-json/acx/v1/recognition/identities';
const MERGE_SUGGESTION_ROUTE = '/wp-json/acx/v1/recognition/suggestions/merge';
const CLUSTER_ROUTE = '/wp-json/acx/v1/recognition/clusters';
const BATCH_PATH = `${IDENTITY_ROUTE}/suggestions`;
const ACCEPT_PATH = `${MERGE_SUGGESTION_ROUTE}/${PENDING_SUGGESTION_ID}/accept`;

interface RecordedRequest {
  method: string;
  pathname: string;
  searchParams: URLSearchParams;
}

let requests: RecordedRequest[];
let unexpectedRoutes: string[];
let acceptResponse: () => Promise<Response>;
let client: ReturnType<typeof buildTestQueryClient>;

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const notFoundBody = { code: 'acx_merge_suggestion_not_found', message: 'Merge suggestion not found.' };

const acceptedMergeBody = () => ({
  id: PENDING_SUGGESTION_ID,
  cluster_a_id: EDITABLE_CLUSTER_ID,
  cluster_b_id: TARGET_CLUSTER_ID,
  similarity: 0.49,
  status: 'accepted',
  source_cluster_id: EDITABLE_CLUSTER_ID,
  target_cluster_id: TARGET_CLUSTER_ID,
  moved_identity_ids: [AFFECTED_IDENTITY_ID],
});

const batchFor = (identityId: string) => ({
  matches: {
    [identityId]: [
      {
        cluster_id: OTHER_CLUSTER_ID,
        label: 'Ellyn Heald',
        similarity: 0.61,
        identity_count: 1,
        suggestion_id: `sug-${identityId}`,
      },
    ],
  },
});

const handleRequest = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(raw, window.location.origin);
  const method = (init?.method ?? 'GET').toUpperCase();
  requests.push({ method, pathname: url.pathname, searchParams: url.searchParams });

  if (method === 'GET' && url.pathname === BATCH_PATH) {
    const identityId = url.searchParams.get('identity_ids') ?? '';
    return Promise.resolve(jsonResponse(batchFor(identityId)));
  }
  if (method === 'POST' && url.pathname === ACCEPT_PATH) {
    return acceptResponse();
  }
  unexpectedRoutes.push(`${method} ${url.pathname}`);
  return Promise.resolve(jsonResponse({ code: 'unexpected_fixture_route' }, 500));
};

const batchReads = () => requests.filter(({ method, pathname }) => method === 'GET' && pathname === BATCH_PATH);
const readsOf = (identityId: string) =>
  batchReads().filter(({ searchParams }) => searchParams.get('identity_ids') === identityId).length;
const unrelatedReads = () => UNRELATED_IDENTITY_IDS.reduce((total, identityId) => total + readsOf(identityId), 0);
const acceptRequests = () =>
  requests.filter(({ method, pathname }) => method === 'POST' && pathname === ACCEPT_PATH);
const clusterMergeRequests = () =>
  requests.filter(({ method, pathname }) => method !== 'GET' && pathname.startsWith(CLUSTER_ROUTE));

const identityBatchKey = (identityId: string) =>
  queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey([identityId]));

const useFlow = (onError: (error: string) => void, onMergeSuccess: (result: unknown) => void) => {
  const reads = useQueries({
    queries: ALL_IDENTITY_IDS.map((identityId) => ({
      queryKey: identityBatchKey(identityId),
      queryFn: () => fetchIdentitiesSuggestions([identityId]),
      staleTime: 0,
    })),
  });
  const mutations = useClusterMutations({
    clusterId: EDITABLE_CLUSTER_ID,
    currentLabel: null,
    derivedLabel: 'Unnamed person',
    onError,
    onMergeSuccess,
  });
  return { reads, mutations };
};

type FlowState = ReturnType<typeof useFlow>;

const mountFlow = async () => {
  const onError = vi.fn();
  const onMergeSuccess = vi.fn();
  let view!: RenderHookResult<FlowState, unknown>;
  await act(async () => {
    view = renderHook(() => useFlow(onError, onMergeSuccess), { wrapper: createQueryWrapper(client) });
    await Promise.resolve();
  });
  return { view, onError, onMergeSuccess };
};

type MountedFlow = Awaited<ReturnType<typeof mountFlow>>['view'];

const loadActiveBatches = async (view: MountedFlow) => {
  await waitFor(() => expect(view.result.current.reads.every((read) => read.isSuccess)).toBe(true));
  expect(batchReads(), 'fixture health: one initial load per active identity observer').toHaveLength(
    ALL_IDENTITY_IDS.length,
  );
  requests = [];
};

const acceptPendingSuggestion = async (view: MountedFlow) => {
  await act(async () => {
    view.result.current.mutations.merge(
      TARGET_CLUSTER_ID,
      'Bea Burke',
      new AbortController().signal,
      PENDING_SUGGESTION_ID,
    );
    await Promise.resolve();
  });
};

const settle = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });

beforeEach(() => {
  requests = [];
  unexpectedRoutes = [];
  acceptResponse = () => Promise.resolve(jsonResponse(notFoundBody, 404));
  registerConfig({
    nonce: 'fixture-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      recognitionClusters: CLUSTER_ROUTE,
      recognitionIdentitySuggestions: IDENTITY_ROUTE,
      recognitionMergeSuggestions: MERGE_SUGGESTION_ROUTE,
    },
  });
  client = buildTestQueryClient();
  vi.stubGlobal('fetch', vi.fn(handleRequest));
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  client.clear();
  vi.unstubAllGlobals();
  resetConfigCache();
  expect(unexpectedRoutes, 'every request must match an explicit HTTP fixture').toEqual([]);
});

describe('useClusterMutations terminal-404 identity read budget (operator115)', () => {
  it('RED: a terminal 404 from the identity-suggestion accept does not refetch unrelated identity batches', async () => {
    const { view, onError } = await mountFlow();
    await loadActiveBatches(view);

    await acceptPendingSuggestion(view);
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    await settle();

    expect(acceptRequests(), 'the 404 comes from the merge-suggestion accept route').toHaveLength(1);
    expect(unrelatedReads(), 'unrelated identity batch reads after one terminal 404').toBe(0);
  });

  it('RED: repeated terminal 404s keep the unrelated identity read budget at zero', async () => {
    const { view, onError } = await mountFlow();
    await loadActiveBatches(view);

    await acceptPendingSuggestion(view);
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    await settle();
    await acceptPendingSuggestion(view);
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(2));
    await settle();

    expect(acceptRequests()).toHaveLength(2);
    expect(unrelatedReads(), 'unrelated identity batch reads after two terminal 404s').toBe(0);
  });

  it('control: a terminal 404 surfaces one visible error and never falls back to a whole-cluster merge', async () => {
    const { view, onError, onMergeSuccess } = await mountFlow();
    await loadActiveBatches(view);

    await acceptPendingSuggestion(view);
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    await settle();

    expect(String(onError.mock.calls[0]?.[0]).trim()).not.toBe('');
    expect(onMergeSuccess).not.toHaveBeenCalled();
    expect(clusterMergeRequests(), 'no whole-cluster merge fallback after the 404').toHaveLength(0);
  });

  it('control: a terminal 404 keeps the cached identity choices that were already loaded', async () => {
    const { view, onError } = await mountFlow();
    await loadActiveBatches(view);

    await acceptPendingSuggestion(view);
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    await settle();

    for (const identityId of ALL_IDENTITY_IDS) {
      expect(client.getQueryData(identityBatchKey(identityId))).toEqual(batchFor(identityId));
    }
    expect(view.result.current.reads.every((read) => read.data !== undefined)).toBe(true);
  });

  it('control: a healthy accept still reconciles the affected identity and reports success', async () => {
    acceptResponse = () => Promise.resolve(jsonResponse(acceptedMergeBody(), 200));
    const { view, onError, onMergeSuccess } = await mountFlow();
    await loadActiveBatches(view);

    await acceptPendingSuggestion(view);
    await waitFor(() => expect(onMergeSuccess).toHaveBeenCalledTimes(1));
    await settle();

    expect(onError).not.toHaveBeenCalled();
    expect(onMergeSuccess.mock.calls[0]?.[0]).toMatchObject({
      source_id: EDITABLE_CLUSTER_ID,
      target_id: TARGET_CLUSTER_ID,
    });
    expect(readsOf(AFFECTED_IDENTITY_ID)).toBeGreaterThanOrEqual(1);
  });

  it('control: an ambiguous transport failure reports one visible error and reconciles the affected identity', async () => {
    acceptResponse = () => Promise.reject(new TypeError('Failed to fetch'));
    const { view, onError, onMergeSuccess } = await mountFlow();
    await loadActiveBatches(view);

    await acceptPendingSuggestion(view);
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    await settle();

    expect(String(onError.mock.calls[0]?.[0]).trim()).not.toBe('');
    expect(onMergeSuccess).not.toHaveBeenCalled();
    expect(readsOf(AFFECTED_IDENTITY_ID)).toBeGreaterThanOrEqual(1);
  });
});
