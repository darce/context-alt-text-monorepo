import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import type { DetectedIdentity, SyncHealthResponse } from '../../../../api/recognition';
import type { RosterCandidatesResponse } from '../../../../api/recognition/rosterCandidatesApi';
import type { RosterEntry } from '../../../../api/rosterApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { IdentityClusterItem } from '../IdentityClusterItem';
import { useClusterSuggestions } from '../useClusterSuggestions';

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
type Route = 'closest' | 'roster' | 'batch' | 'clusters' | 'health';
interface RequestRecord { route: Route; method: string; url: URL }
let client: ReturnType<typeof buildTestQueryClient>;
let requests: RequestRecord[];
let unexpected: string[];
let responses: Record<Route, () => Promise<Response>>;
const count = (route: Route) => requests.filter((request) => request.route === route).length;
const closestState = () => client.getQueryState(queryKeys.clusters.rosterCandidates(CLUSTER_ID, 5));
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
    closest: () => Promise.resolve(json(candidateBody)),
    roster: () => Promise.resolve(json(roster)),
    batch: () => Promise.resolve(json(emptyBatch)),
    clusters: () => Promise.resolve(json(emptyClusters)),
    health: () => Promise.resolve(json(syncHealth)),
  };
  // No hook/query mocks: defer the public HTTP boundary used by the current adapters.
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    let route: Route;
    if (url.pathname === `/wp-json/acx/v1/recognition/clusters/${CLUSTER_ID}/roster-candidates`) route = 'closest';
    else if (url.pathname === '/wp-json/acx/v1/roster/entries') route = 'roster';
    else if (url.pathname === '/wp-json/acx/v1/recognition/identities/suggestions') route = 'batch';
    else if (url.pathname === '/wp-json/acx/v1/recognition/clusters') route = 'clusters';
    else if (url.pathname === '/wp-json/acx/v1/recognition/sync/health') route = 'health';
    else {
      unexpected.push(`${method} ${url.pathname}`);
      return Promise.reject(new Error(`Unexpected fixture route: ${method} ${url.pathname}`));
    }
    requests.push({ route, method, url });
    if (method !== 'GET') {
      unexpected.push(`${method} ${url.pathname}`);
      return Promise.reject(new Error('Display and retry must be read-only'));
    }
    return responses[route]();
  }));
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  assertReadOnly();
  client.clear();
  vi.unstubAllGlobals();
  resetConfigCache();
  expect(unexpected, 'all requests use explicit fixture routes').toEqual([]);
});

const mountHook = () => renderHook(
  ({ labelInput, enabled }) => useClusterSuggestions({
    identityId: IDENTITY_ID, editableClusterId: CLUSTER_ID, enabled, labelInput, debounceMs: 0,
  }),
  { initialProps: { labelInput: '', enabled: true }, wrapper: createQueryWrapper(client) },
);
const mountEditor = (expand = true) => {
  const view = render(<IdentityClusterItem cluster={{
    key: CLUSTER_ID, clusterId: CLUSTER_ID, label: null,
    isAutoLabel: false, clusteringPending: false, members: [member],
  }} canLabel canMutate />, { wrapper: createQueryWrapper(client) });
  if (expand) fireEvent.click(screen.getByRole('button', { name: 'Unnamed person' }));
  return view;
};
const input = () => screen.getByRole('combobox', { name: 'Person name' });
const essentialReady = async () => {
  await waitFor(() => expect(client.getQueryState(queryKeys.roster.entries())?.status).toBe('success'));
  await waitFor(() => expect(count('batch')).toBe(1));
  await waitFor(() => expect(count('clusters')).toBe(1));
  await waitFor(() => expect(count('closest')).toBe(1));
  await waitFor(() => {
    const essentialQueries = client.getQueryCache().findAll({
      type: 'active', predicate: (query) => !query.queryKey.includes('roster-candidates'),
    });
    expect(essentialQueries.length).toBeGreaterThanOrEqual(3);
    expect(essentialQueries.every((query) => query.state.status === 'success' && query.state.fetchStatus === 'idle')).toBe(true);
  });
};
const openChoices = () => {
  fireEvent.focus(input());
  fireEvent.keyDown(input(), { key: 'ArrowDown' });
};

describe('F3 optional closest-read budget through the real hook and legacy editor', () => {
  it('F3 RED hook: hanging optional closest read does not consume essential loading budget', async () => {
    hold('closest');
    const { result, rerender } = mountHook();
    await essentialReady();
    expect(closestState()).toMatchObject({ status: 'pending', fetchStatus: 'fetching' });
    expect(result.current.options).toContainEqual(expect.objectContaining({ label: 'Pat Nguyen', source: 'person' }));
    expect(result.current.isLoading, 'only the optional closest GET is still pending').toBe(false);
    rerender({ labelInput: 'Pat', enabled: true });
    await waitFor(() => expect(requests.some(({ route, url }) => route === 'clusters' && url.searchParams.get('search') === 'Pat')).toBe(true));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.options.map((option) => option.label)).toContain('Pat Nguyen');
    expect(count('closest')).toBe(1);
    assertReadOnly();
  });

  it('F3 RED editor: hanging optional read permits manual naming and ordinary roster lookup', async () => {
    hold('closest');
    mountEditor();
    await essentialReady();
    expect(closestState()?.fetchStatus).toBe('fetching');
    expect(input(), 'optional suggestions must not disable manual entry').toBeEnabled();
    const user = userEvent.setup();
    await user.type(input(), 'Zoe');
    expect(input()).toHaveValue('Zoe');
    expect(screen.getByRole('button', { name: 'Save name' })).toBeEnabled();
    await user.clear(input());
    await user.type(input(), 'Pat');
    openChoices();
    expect(await screen.findByRole('option', { name: /Pat Nguyen/ })).toBeVisible();
    expect(screen.queryByRole('option', { name: /Ellyn Heald/ })).not.toBeInTheDocument();
    expect(count('closest')).toBe(1);
    assertReadOnly();
  });

  it('F3 RED retry: visible error Retry may hang without disabling manual entry or ordinary roster lookup', async () => {
    responses.closest = () => Promise.resolve(json({ code: 'service_unavailable' }, 503));
    mountEditor();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not load name suggestions.');
    expect(input()).toBeEnabled();
    await userEvent.setup().type(input(), 'Zoe');
    hold('closest');
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(count('closest')).toBe(2));
    expect(closestState()?.fetchStatus).toBe('fetching');
    expect(input(), 'a pending optional Retry must preserve manual entry').toBeEnabled();
    expect(input()).toHaveValue('Zoe');
    const user = userEvent.setup();
    await user.clear(input());
    await user.type(input(), 'Pat');
    openChoices();
    expect(await screen.findByRole('option', { name: /Pat Nguyen/ })).toBeVisible();
    expect(count('batch')).toBe(1);
    expect(count('roster')).toBe(1);
    assertReadOnly();
  });

  it('F3 healthy: essential roster initial loading protects the actual editor until the roster resolves', async () => {
    const pending = hold('roster');
    mountEditor();
    await waitFor(() => expect(count('roster')).toBe(1));
    await waitFor(() => expect(closestState()?.status).toBe('success'));
    expect(input()).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled();
    act(() => { pending.resolve(roster); });
    await waitFor(() => expect(input()).toBeEnabled());
    await userEvent.setup().type(input(), 'Zoe');
    expect(input()).toHaveValue('Zoe');
    assertReadOnly();
  });

  it.each(['batch', 'clusters'] as const)('F3 healthy: initial essential %s read retains its loading budget', async (route) => {
    const pending = hold(route);
    const { result } = mountHook();
    await waitFor(() => expect(count(route)).toBe(1));
    expect(result.current.isLoading).toBe(true);
    if (route === 'batch') expect(count('closest')).toBe(0);
    act(() => { pending.resolve(route === 'batch' ? emptyBatch : emptyClusters); });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    assertReadOnly();
  });

  it('F3 healthy: a new essential typed lookup retains its loading budget', async () => {
    const { result, rerender } = mountHook();
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await waitFor(() => expect(closestState()?.status).toBe('success'));
    const pending = hold('clusters');
    rerender({ labelInput: 'Pat', enabled: true });
    await waitFor(() => expect(requests.some(({ route, url }) => route === 'clusters' && url.searchParams.get('search') === 'Pat')).toBe(true));
    expect(result.current.isLoading).toBe(true);
    act(() => { pending.resolve(emptyClusters); });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.options.map((option) => option.label)).toContain('Pat Nguyen');
    assertReadOnly();
  });

  it('F3 healthy: failed optional read is visible, and successful Retry retains manual text without writes', async () => {
    responses.closest = () => Promise.resolve(json({ code: 'service_unavailable' }, 503));
    mountEditor();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not load name suggestions.');
    expect(input()).toBeEnabled();
    await userEvent.setup().type(input(), 'Zoe');
    responses.closest = () => Promise.resolve(json(candidateBody));
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(closestState()?.status).toBe('success'));
    expect(count('closest')).toBe(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(input()).toHaveValue('Zoe');
    openChoices();
    expect(screen.getByRole('option', { name: /Ellyn Heald/ })).toHaveTextContent('Weak match');
    expect(screen.queryByText(/training|learned|cannot.link/i)).not.toBeInTheDocument();
    assertReadOnly();
  });

  it('F3 healthy: cached closest choices survive an error and hanging Retry while manual entry remains available', async () => {
    mountEditor();
    await waitFor(() => expect(closestState()?.status).toBe('success'));
    responses.closest = () => Promise.resolve(json({ code: 'service_unavailable' }, 503));
    await act(async () => {
      await client.invalidateQueries({ queryKey: queryKeys.clusters.rosterCandidates(CLUSTER_ID, 5) });
    });
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Could not load name suggestions.');
    hold('closest');
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(count('closest')).toBe(3));
    expect(closestState()?.fetchStatus).toBe('fetching');
    expect(input()).toBeEnabled();
    await userEvent.setup().type(input(), 'Zoe');
    openChoices();
    expect(screen.getByRole('option', { name: /Ellyn Heald/ })).toHaveTextContent('Weak match');
    expect(input()).toHaveValue('Zoe');
    expect(screen.getByRole('button', { name: 'Save name' })).toBeEnabled();
    assertReadOnly();
  });

  it('F3 healthy: real query enabling spends no closest budget until essential identity data resolves', async () => {
    const pending = hold('batch');
    const { result } = mountHook();
    await waitFor(() => expect(count('roster')).toBe(1));
    expect(count('closest')).toBe(0);
    expect(result.current.isLoading).toBe(true);
    act(() => { pending.resolve(emptyBatch); });
    await waitFor(() => expect(closestState()?.status).toBe('success'));
    expect(count('closest')).toBe(1);
    const request = requests.find(({ route }) => route === 'closest');
    expect(request?.url.searchParams.get('top_k')).toBe('5');
    assertReadOnly();
  });

  it('F3 healthy: collapsed actual editor spends no identity or closest read budget', async () => {
    const view = mountEditor(false);
    await waitFor(() => expect(client.getQueryState(queryKeys.roster.entries())?.status).toBe('success'));
    await act(async () => { await client.invalidateQueries(); });
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(count('batch')).toBe(0);
    expect(count('clusters')).toBe(0);
    expect(count('closest')).toBe(0);
    view.unmount();
    await act(async () => { await client.invalidateQueries(); });
    expect(count('closest')).toBe(0);
    assertReadOnly();
  });

  it('F3 healthy: a real persisted pending proposal retains its closest-query guard', async () => {
    responses.batch = () => Promise.resolve(json({ matches: { [IDENTITY_ID]: [{
      cluster_id: 'cluster-bea', label: 'Bea Burke', similarity: 0.41,
      identity_count: 9, suggestion_id: 'persisted-proposal-fixture',
    }] } }));
    const { result } = mountHook();
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.options).toContainEqual(expect.objectContaining({
      label: 'Bea Burke', suggestion_id: 'persisted-proposal-fixture',
    }));
    expect(count('closest')).toBe(0);
    assertReadOnly();
  });
});
