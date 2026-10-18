import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
type Route = 'closest' | 'roster' | 'batch' | 'clusters' | 'health' | 'commit' | 'rename';
interface RequestRecord { route: Route; method: string; url: URL; body?: unknown }
let allowCommit: boolean;
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
    rename: () => Promise.reject(new Error('No rename expected')),
    commit: () => Promise.reject(new Error('No write expected')),
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
    else if (url.pathname === `/wp-json/acx/v1/roster/clusters/${CLUSTER_ID}/commit`) route = 'commit';
    else if (url.pathname === `/wp-json/acx/v1/recognition/clusters/${CLUSTER_ID}`) route = 'rename';
    else if (url.pathname === '/wp-json/acx/v1/roster/entries') route = 'roster';
    else if (url.pathname === '/wp-json/acx/v1/recognition/identities/suggestions') route = 'batch';
    else if (url.pathname === '/wp-json/acx/v1/recognition/clusters') route = 'clusters';
    else if (url.pathname === '/wp-json/acx/v1/recognition/sync/health') route = 'health';
    else {
      unexpected.push(`${method} ${url.pathname}`);
      return Promise.reject(new Error(`Unexpected fixture route: ${method} ${url.pathname}`));
    }
    requests.push({ route, method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (method !== 'GET' && !(allowCommit && ((route === 'commit' && method === 'POST') || (route === 'rename' && method === 'PATCH')))) {
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
  else expect(requests.filter(({ method }) => method !== 'GET').every(({ route, method }) => ((route === 'commit' && method === 'POST') || (route === 'rename' && method === 'PATCH')))).toBe(true);
  client.clear();
  onlineManager.setOnline(true);
  vi.unstubAllGlobals();
  resetConfigCache();
  expect(unexpected, 'all requests use explicit fixture routes').toEqual([]);
});

const mountEditor = (expand = true, label: string | null = null) => {
  const view = render(<IdentityClusterItem cluster={{
    key: CLUSTER_ID, clusterId: CLUSTER_ID, label,
    isAutoLabel: false, clusteringPending: false, members: [member],
  }} canLabel canMutate />, { wrapper: createQueryWrapper(client) });
  if (expand) fireEvent.click(screen.getByRole('button', { name: label ?? 'Unnamed person' }));
  return view;
};
const input = () => screen.getByRole('combobox', { name: 'Person name' });
describe('QN1-02 actual naming draft recovery', () => {
  it('roster background failure after typed draft preserves text and restores keyboard focus after Retry', async () => {
    hold('batch');
    mountEditor();
    await waitFor(() => expect(input()).toBeEnabled());
    const user = userEvent.setup();
    await user.type(input(), 'Zoe');
    expect([(input() as HTMLInputElement).selectionStart, (input() as HTMLInputElement).selectionEnd]).toEqual([3, 3]);
    responses.roster = () => Promise.resolve(json({code:'unavailable'},503));
    await act(async () => { await client.invalidateQueries({queryKey:queryKeys.roster.entries()}); });
    expect(screen.getByRole('alert')).toHaveTextContent('Unable to load people.');
    const retry = hold('roster');
    await user.click(screen.getByRole('button', {name:'Retry'}));
    await waitFor(() => expect(count('roster')).toBe(3));
    act(() => retry.resolve(roster));
    await waitFor(() => expect(client.getQueryState(queryKeys.roster.entries())?.status).toBe('success'));
    await waitFor(() => expect(input()).toBeEnabled());
    expect(input()).toHaveValue('Zoe');
    expect(input(), 'QN successful Retry must restore focus to retained draft').toHaveFocus();
    const recovered = input() as HTMLInputElement;
    console.info('QN recovery selection', recovered.selectionStart, recovered.selectionEnd, recovered.value);
    await user.keyboard('y');
    expect(input()).toHaveValue('Zoey');
  }, 15_000);

  it('fresh actual Item opens with prefilled text selected, including a later fresh open', async () => {
    client.setQueryData(queryKeys.roster.entries(), roster);
    mountEditor(false, 'Zoe');
    await waitFor(() => expect(client.getQueryState(queryKeys.roster.entries())?.status).toBe('success'));
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Zoe' }));
    const fresh = input() as HTMLInputElement;
    expect(fresh).toHaveFocus();
    expect([fresh.selectionStart, fresh.selectionEnd]).toEqual([0, 3]);
    await user.keyboard('Pat');
    expect(fresh).toHaveValue('Pat');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.click(screen.getByRole('button', { name: 'Zoe' }));
    const reopened = input() as HTMLInputElement;
    expect(reopened).not.toBe(fresh);
    expect(reopened).toHaveFocus();
    expect([reopened.selectionStart, reopened.selectionEnd]).toEqual([0, 3]);
    await user.keyboard('y');
    expect(reopened).toHaveValue('y');
  }, 15_000);

  it('keeps the input, focus and nonempty selection through failed Retry, allowing draft edits but no commit', async () => {
    hold('batch');
    mountEditor();
    await waitFor(() => expect(input()).toBeEnabled());
    const user = userEvent.setup();
    await user.type(input(), 'Zoe');
    const draft = input() as HTMLInputElement;
    draft.setSelectionRange(1, 3);
    responses.roster = () => Promise.resolve(json({ code: 'unavailable' }, 503));
    await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.roster.entries() }); });
    expect(input()).toBe(draft);
    expect(draft).toBeEnabled();
    expect(draft).toHaveFocus();
    expect([draft.selectionStart, draft.selectionEnd]).toEqual([1, 3]);
    expect(draft).toHaveAccessibleDescription(expect.stringContaining('Unable to load people.'));
    expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled();
    await user.keyboard('{ArrowDown}{Enter}');
    expect(count('commit') + count('rename')).toBe(0);
    // A genuine unsuccessful Retry must also keep the same editor and selection.
    draft.setSelectionRange(1, 3);
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(count('roster')).toBe(3));
    await waitFor(() => expect(client.getQueryState(queryKeys.roster.entries())?.fetchStatus).toBe('idle'));
    expect(input()).toBe(draft);
    expect(draft).toHaveFocus();
    expect([draft.selectionStart, draft.selectionEnd]).toEqual([1, 3]);
    await user.keyboard('a');
    expect(draft).toHaveValue('Za');
    const retry = hold('roster');
    draft.setSelectionRange(0, 1);
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(count('roster')).toBe(4));
    expect(draft).toBeEnabled();
    expect([draft.selectionStart, draft.selectionEnd]).toEqual([0, 1]);
    await user.keyboard('M{Enter}');
    expect(draft).toHaveValue('Ma');
    expect(count('commit') + count('rename')).toBe(0);
    act(() => retry.resolve(roster));
    await waitFor(() => expect(client.getQueryState(queryKeys.roster.entries())?.status).toBe('success'));
    expect(input()).toBe(draft);
    expect(draft).toHaveFocus();
    expect([draft.selectionStart, draft.selectionEnd]).toEqual([1, 1]);
    await user.keyboard('y');
    expect(draft).toHaveValue('Mya');
    expect(screen.getByRole('button', { name: 'Save name' })).toBeEnabled();
  }, 15_000);
  it('new explicit name writes the actual PATCH before identity batch settles and blocks repeats', async () => {
    allowCommit = true;
    const batch = hold('batch');
    const write = hold('rename');
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    mountEditor();
    await waitFor(() => expect(input()).toBeEnabled());
    const user = userEvent.setup();
    await user.type(input(), 'Zoe');
    await user.click(screen.getByRole('button', {name:'Save name'}));
    await waitFor(() => expect(count('rename')).toBe(1));
    expect(requests.find(({route}) => route === 'rename')?.body).toEqual({label:'Zoe'});
    expect(count('commit')).toBe(0);
    expect(input()).toBeDisabled();
    await user.type(input(), 'changed{Enter}');
    await user.click(screen.getByRole('button', {name:/Saving/}));
    act(() => batch.resolve(emptyBatch));
    await waitFor(() => expect(closestState()?.status).toBe('success'));
    expect(input()).toHaveValue('Zoe');
    expect(input()).toBeDisabled();
    expect(count('rename')).toBe(1);
    act(() => write.resolve({}));
    expect(await screen.findByRole('button', {name:'Saved!'})).toBeDisabled();
    expect(invalidate).toHaveBeenCalled();
  }, 15_000);

  it('pending write survives late advisory failure and roster error without a second commit', async () => {
    allowCommit = true;
    const batch = hold('batch');
    const write = hold('commit');
    const invalidate = vi.spyOn(client,'invalidateQueries');
    mountEditor();
    await waitFor(() => expect(input()).toBeEnabled());
    const user = userEvent.setup();
    await user.type(input(),'Pat Nguyen');
    await user.click(screen.getByRole('button',{name:'Save name'}));
    await waitFor(() => expect(count('commit')).toBe(1));
    act(() => batch.resolve({code:'unavailable'},503));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Could not load name suggestions.'));
    expect(input()).toBeDisabled();
    responses.roster = () => Promise.resolve(json({code:'unavailable'},503));
    await act(async () => { await client.invalidateQueries({queryKey:queryKeys.roster.entries()}); });
    expect(input()).toBeDisabled();
    const rosterAlert = screen.getAllByRole('alert').find((alert) => alert.textContent?.includes('Unable to load people.'));
    expect(rosterAlert).toBeDefined();
    const retryRoster = within(rosterAlert!).getByRole('button', { name: 'Retry' });
    expect(retryRoster).toBeDisabled();
    await user.click(retryRoster);
    expect(count('commit')).toBe(1);
    responses.roster = () => Promise.resolve(json(roster));
    act(() => write.resolve({cluster_id:CLUSTER_ID,person_id:9,person_uuid:'person-9',person_name:'Pat Nguyen',updated_at:'2026-10-18T00:00:00Z'}));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({queryKey:queryKeys.roster.entries()}));
    expect(await screen.findByRole('button',{name:'Saved!'})).toBeDisabled();
    expect(count('commit')).toBe(1);
  }, 15_000);
  it('paused and globally disabled mandatory reads do not fail open in the real editor', async () => {
    onlineManager.setOnline(false);
    mountEditor();
    await waitFor(() => expect(client.getQueryState(queryKeys.roster.entries())?.fetchStatus).toBe('paused'));
    expect(client.getQueryState(queryKeys.roster.entries())?.status).toBe('pending');
    expect(input()).toBeDisabled();
    expect(screen.getByRole('button',{name:'Save name'})).toBeDisabled();
    expect(count('roster')).toBe(0);
  }, 15_000);

  it('runtime disabled unavailable roster stays closed even though query isLoading is false', async () => {
    client.setDefaultOptions({queries:{enabled:false,retry:false}});
    mountEditor();
    await waitFor(() => expect(client.getQueryState(queryKeys.roster.entries())?.status).toBe('pending'));
    expect(client.getQueryState(queryKeys.roster.entries())?.fetchStatus).toBe('idle');
    expect(input()).toBeDisabled();
    expect(screen.getByRole('button',{name:'Save name'})).toBeDisabled();
    expect(count('roster')).toBe(0);
  }, 15_000);

  it('successful empty roster with no anchor identity permits the actual naming editor', async () => {
    responses.roster = () => Promise.resolve(json([]));
    render(<IdentityClusterItem cluster={{key:CLUSTER_ID,clusterId:CLUSTER_ID,label:null,isAutoLabel:false,clusteringPending:false,members:[]}} canLabel canMutate />, {wrapper:createQueryWrapper(client)});
    const user = userEvent.setup();
    await user.click(screen.getByRole('button',{name:'Unnamed person'}));
    await waitFor(() => expect(input()).toBeEnabled());
    await user.type(input(),'Zoe');
    expect(screen.getByRole('button',{name:'Save name'})).toBeEnabled();
    expect(count('batch')).toBe(0);
    expect(count('closest')).toBe(0);
  }, 15_000);
});
