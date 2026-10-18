import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { onlineManager } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import type { DetectedIdentity, SyncHealthResponse } from '../../../../api/recognition';
import type { RosterCandidatesResponse } from '../../../../api/recognition/rosterCandidatesApi';
import type { RosterEntry } from '../../../../api/rosterApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { IdentityClusterItem } from '../IdentityClusterItem';

const CLUSTER_ID = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const IDENTITY_ID = 'identity-unnamed';
const person = (id: number, name: string): RosterEntry => ({
  id, name, person_uuid: `person-${id}`, tags: [], cluster_count: 1,
  clusters: [], queue_memberships: [], updated_at: '2026-10-15T00:00:00Z',
  source_version: 1, projection_status: 'current',
  projection_refreshed_at: '2026-10-15T00:00:00Z',
});
const roster = [person(7, 'Ellyn Heald'), person(9, 'Pat Nguyen')];
const candidateBody: RosterCandidatesResponse = {
  model_id: 'fixture-model', embedding_model: 'fixture-model',
  computed_at: '2026-10-15T00:00:00Z', probe_face_count: 1,
  reference_face_count: 2, quality_flag: 'ok',
  thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
  candidates: [{ cluster_id: 'cluster-ellyn', name: 'Ellyn Heald',
    similarity: 0.12, band: 'none', roster_entry_id: 7 }],
};
const member: DetectedIdentity = {
  identity_id: IDENTITY_ID, representative_id: 'rep-1', media_id: 1,
  cluster_id: CLUSTER_ID, cluster_label: null, is_auto_label: false,
  is_pinned: false, bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1, similarity: 1, detected_at: '',
};
const emptyClusters = { clusters: [], limit: 50, offset: 0, total: 0, truncated: false };
const emptyBatch = { matches: { [IDENTITY_ID]: [] } };
const syncHealth: SyncHealthResponse = {
  breaker: { state: 'closed', base_url: 'https://example.test', opened_at: null },
  outbox: { state: 'ok', pending: 0, failed: 0, dead_lettered: 0, oldest_age_seconds: 0 },
  conflicts: { open: 0 }, replays: { failed: 0, source: 'fixture' },
  last_pull: { at: '2026-10-15T00:00:00Z', ok: true }, warnings: [],
};
const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});
const deferredResponse = () => {
  let finish: (response: Response) => void = () => { throw new Error('Deferred response not initialized'); };
  const promise = new Promise<Response>((resolve) => { finish = resolve; });
  return { promise, resolve: (body: unknown, status = 200) => finish(json(body, status)) };
};
type Route = 'closest' | 'roster' | 'batch' | 'clusters' | 'health' | 'commit';
interface RequestRecord { route: Route; method: string; url: URL; body?: unknown }
let allowCommit: boolean;
let client: ReturnType<typeof buildTestQueryClient>;
let requests: RequestRecord[];
let unexpected: string[];
let responses: Record<Route, () => Promise<Response>>;
const count = (route: Route) => requests.filter((request) => request.route === route).length;
const hold = (route: Route) => {
  const deferred = deferredResponse();
  responses[route] = () => deferred.promise;
  return deferred;
};
const assertReadOnly = () => {
  expect(requests.every(({ method }) => method === 'GET')).toBe(true);
  expect(client.getMutationCache().getAll()).toHaveLength(0);
};

beforeEach(() => {
  allowCommit = false;
  requests = [];
  unexpected = [];
  client = buildTestQueryClient();
  registerConfig({
    nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      rosterEntries: '/wp-json/acx/v1/roster/entries',
      rosterClusters: '/wp-json/acx/v1/roster/clusters',
      rosterPersons: '/wp-json/acx/v1/roster/persons',
      recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
      recognitionIdentitySuggestions: '/wp-json/acx/v1/recognition/identities',
      recognitionSyncHealth: '/wp-json/acx/v1/recognition/sync/health',
    },
  });
  responses = {
    commit: () => Promise.reject(new Error('No write expected')),
    closest: () => Promise.resolve(json(candidateBody)),
    roster: () => Promise.resolve(json(roster)),
    batch: () => Promise.resolve(json(emptyBatch)),
    clusters: () => Promise.resolve(json(emptyClusters)),
    health: () => Promise.resolve(json(syncHealth)),
  };
  // Exercise the current query hooks and API adapters; only the HTTP boundary is deferred.
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    let route: Route;
    if (url.pathname === `/wp-json/acx/v1/recognition/clusters/${CLUSTER_ID}/roster-candidates`) route = 'closest';
    else if (url.pathname === `/wp-json/acx/v1/roster/clusters/${CLUSTER_ID}/commit`) route = 'commit';
    else if (url.pathname === '/wp-json/acx/v1/roster/entries') route = 'roster';
    else if (url.pathname === '/wp-json/acx/v1/recognition/identities/suggestions') route = 'batch';
    else if (url.pathname === '/wp-json/acx/v1/recognition/clusters') route = 'clusters';
    else if (url.pathname === '/wp-json/acx/v1/recognition/sync/health') route = 'health';
    else {
      unexpected.push(`${method} ${url.pathname}`);
      return Promise.reject(new Error(`Unexpected fixture route: ${method} ${url.pathname}`));
    }
    requests.push({ route, method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (method !== 'GET' && !(allowCommit && route === 'commit' && method === 'POST')) {
      unexpected.push(`${method} ${url.pathname}`);
      return Promise.reject(new Error('Display and retry must be read-only'));
    }
    return responses[route]();
  }));
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  if (!allowCommit) assertReadOnly();
  else expect(requests.filter(({ method }) => method !== 'GET').every(({ route, method }) => route === 'commit' && method === 'POST')).toBe(true);
  client.clear();
  onlineManager.setOnline(true);
  vi.unstubAllGlobals();
  resetConfigCache();
  expect(unexpected, 'all requests use explicit fixture routes').toEqual([]);
});

const mountEditor = (expand = true) => {
  const view = render(<IdentityClusterItem cluster={{
    key: CLUSTER_ID, clusterId: CLUSTER_ID, label: null,
    isAutoLabel: false, clusteringPending: false, members: [member],
  }} canLabel canMutate />, { wrapper: createQueryWrapper(client) });
  if (expand) fireEvent.click(screen.getByRole('button', { name: 'Unnamed person' }));
  return view;
};
const input = () => screen.getByRole('combobox', { name: 'Person name' });

const rosterState = () => client.getQueryState(queryKeys.roster.entries());
const reachCachedError = async () => {
  hold('batch');
  mountEditor();
  await waitFor(() => expect(input()).toBeEnabled());
  expect(rosterState()?.status).toBe('success');
  expect(count('roster')).toBe(1);
  responses.roster = () => Promise.resolve(json({ code: 'unavailable' }, 503));
  await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.roster.entries() }); });
  await waitFor(() => expect(rosterState()).toMatchObject({ status: 'error', fetchStatus: 'idle' }));
  expect(rosterState()?.data).toEqual(roster);
  expect(screen.getByRole('alert')).toHaveTextContent('Unable to load people.');
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Save name' })).not.toBeInTheDocument();
  expect(count('roster')).toBe(2);
};
const clickPendingRetry = async (expectedTotal: number) => {
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Retry' }));
  await waitFor(() => expect(rosterState()?.fetchStatus).toBe('fetching'));
  await user.click(screen.getByRole('button', { name: 'Retry' }));
  await user.click(screen.getByRole('button', { name: 'Retry' }));
  expect(count('roster'), 'pending mandatory Retry must coalesce uncancellable HTTP reads').toBe(expectedTotal);
  expect(rosterState()).toMatchObject({ status: 'error', fetchStatus: 'fetching' });
  expect(screen.getByRole('alert')).toHaveTextContent('Unable to load people.');
  expect(screen.queryByRole('button', { name: 'Save name' })).not.toBeInTheDocument();
};

describe('CURUX1-QN1-01 mandatory roster Retry through production queries and HTTP', () => {
  it('coalesces three cached-error Retry clicks, settles success, then permits a later Retry', async () => {
    await reachCachedError();
    const retry = hold('roster');
    await clickPendingRetry(3);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    act(() => { retry.resolve([]); });
    await waitFor(() => expect(input()).toBeEnabled());
    expect(rosterState()).toMatchObject({ status: 'success', fetchStatus: 'idle', data: [] });
    expect(screen.queryByText(/Unable to load people/)).not.toBeInTheDocument();
    await userEvent.setup().type(input(), 'Zoe');
    expect(screen.getByRole('button', { name: 'Save name' })).toBeEnabled();
    expect(count('commit')).toBe(0);

    responses.roster = () => Promise.resolve(json({ code: 'unavailable' }, 503));
    await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.roster.entries() }); });
    await waitFor(() => expect(rosterState()).toMatchObject({ status: 'error', fetchStatus: 'idle' }));
    expect(count('roster')).toBe(4);
    const laterRetry = hold('roster');
    await clickPendingRetry(5);
    act(() => { laterRetry.resolve(roster); });
    await waitFor(() => expect(input()).toBeEnabled());
    expect(rosterState()).toMatchObject({ status: 'success', fetchStatus: 'idle', data: roster });
    expect(input()).toHaveValue('Zoe');
    expect(count('roster')).toBe(5);
  });

  it('coalesces pending Retry failure and releases the next Retry after failure settlement', async () => {
    await reachCachedError();
    const failedRetry = hold('roster');
    await clickPendingRetry(3);
    act(() => { failedRetry.resolve({ code: 'still-unavailable' }, 503); });
    await waitFor(() => expect(rosterState()).toMatchObject({ status: 'error', fetchStatus: 'idle' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load people.');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    const nextRetry = hold('roster');
    await clickPendingRetry(4);
    act(() => { nextRetry.resolve(roster); });
    await waitFor(() => expect(input()).toBeEnabled());
    expect(rosterState()).toMatchObject({ status: 'success', fetchStatus: 'idle', data: roster });
    expect(count('roster')).toBe(4);
  });

  it('issues no Retry HTTP request while a real roster bind write is pending', async () => {
    allowCommit = true;
    hold('batch');
    const write = hold('commit');
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    mountEditor();
    await waitFor(() => expect(input()).toBeEnabled());
    const user = userEvent.setup();
    // Select the real stable-ID roster row without scheduling a typed search.
    await user.click(input());
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');
    await waitFor(() => expect(count('commit')).toBe(1));
    expect(requests.find(({ route }) => route === 'commit')?.body).toEqual({ roster_entry_id: 9, new_entry_name: null });
    expect(input()).toBeDisabled();
    responses.roster = () => Promise.resolve(json({ code: 'unavailable' }, 503));
    await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.roster.entries() }); });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry' })).toBeDisabled());
    const before = requests.length;
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await user.keyboard('{Enter}');
    expect(requests).toHaveLength(before);
    expect(count('roster')).toBe(2);
    expect(count('commit')).toBe(1);
    responses.roster = () => Promise.resolve(json(roster));
    invalidate.mockClear();
    act(() => { write.resolve({ cluster_id: CLUSTER_ID, person_id: 9, person_uuid: 'person-9', person_name: 'Pat Nguyen', updated_at: '2026-10-18T00:00:00Z' }); });
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.roster.entries() }));
    expect(await screen.findByRole('button', { name: 'Saved!' })).toBeDisabled();
    expect(count('commit')).toBe(1);
  });
});
