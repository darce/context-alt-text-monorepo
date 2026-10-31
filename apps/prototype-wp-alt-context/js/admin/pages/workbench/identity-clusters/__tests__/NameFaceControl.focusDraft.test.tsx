import React from 'react';
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
import { NameFaceControl } from '../NameFaceControl';

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
    if (init?.body != null && typeof init.body !== 'string') {
      throw new Error('Fixture request body must be a JSON string');
    }
    requests.push({ route, method, url, body: init?.body ? JSON.parse(init.body) : undefined });
    if (method !== 'GET' && !(allowCommit && ((route === 'commit' && method === 'POST') || (route === 'rename' && method === 'PATCH')))) {
      unexpected.push(`${method} ${url.pathname}`);
      return Promise.reject(new Error('Display and retry must be read-only'));
    }
    return responses[route]();
  }));
});

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
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
describe('Name this person focus and draft journey through actual producers', () => {
  it('focuses immediately while mandatory people lookup is pending, allows typing and keeps commit gated', async () => {
    const read = hold('roster');
    mountEditor();
    const draft = input() as HTMLInputElement;
    expect(draft).toBeEnabled();
    expect(draft).toHaveFocus();
    expect(screen.getByRole('status')).toHaveTextContent('Loading people…');
    const user = userEvent.setup();
    await user.keyboard('Zoe{Enter}');
    expect(draft).toHaveValue('Zoe');
    expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled();
    expect(count('rename') + count('commit')).toBe(0);
    draft.setSelectionRange(1, 3);
    act(() => read.resolve(roster));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save name' })).toBeEnabled());
    expect(input()).toBe(draft);
    expect(draft).toHaveFocus();
    expect([draft.selectionStart, draft.selectionEnd]).toEqual([1, 3]);
  });

  it.each(['offline', 'disabled'])('allows drafting with %s mandatory reads, without permitting a write', async (mode) => {
    if (mode === 'offline') onlineManager.setOnline(false);
    else client.setDefaultOptions({ queries: { enabled: false, retry: false } });
    mountEditor();
    expect(input()).toBeEnabled();
    expect(input()).toHaveFocus();
    await userEvent.setup().keyboard('Zoe{Enter}');
    expect(input()).toHaveValue('Zoe');
    expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled();
    expect(count('roster') + count('commit') + count('rename')).toBe(0);
  });

  it.each([
    ['Name this person', 'Cancel'],
    ['Unnamed person', 'Escape'],
  ])('returns focus to the exact %s opener after %s', async (opener, exit) => {
    client.setQueryData(queryKeys.roster.entries(), roster);
    mountEditor(false);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: opener }));
    await user.keyboard('Zoe');
    if (exit === 'Cancel') await user.click(screen.getByRole('button', { name: 'Cancel' }));
    else await user.keyboard('{Escape}{Escape}');
    await waitFor(() => expect(screen.getByRole('button', { name: opener })).toHaveFocus());
    // Actual Library producer starts each explicit reopen with its accepted label.
    await user.keyboard('{Enter}');
    expect(input()).toHaveValue('');
    expect(input()).toHaveFocus();
  });

  it('reveals the whole editor in only the nearest scrollable pane', async () => {
    client.setQueryData(queryKeys.roster.entries(), roster);
    const rect = (top: number, bottom: number) => ({ top, bottom, left: 0, right: 400, width: 400, height: bottom - top, x: 0, y: top, toJSON: () => ({}) });
    const geometry = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.dataset.testid === 'media-pane') return rect(100, 400);
      if (this.classList.contains('acx-identity-cluster__edit')) return rect(380, 500);
      return rect(0, 800);
    });
    const { container } = render(<div data-testid="outer-pane" style={{ overflowY: 'auto' }}>
      <div data-testid="media-pane" style={{ overflowY: 'auto' }}><IdentityClusterItem cluster={{
        key: CLUSTER_ID, clusterId: CLUSTER_ID, label: null,
        isAutoLabel: false, clusteringPending: false, members: [member],
      }} canLabel canMutate /></div>
    </div>, { wrapper: createQueryWrapper(client) });
    const pane = screen.getByTestId('media-pane');
    const outer = screen.getByTestId('outer-pane');
    for (const node of [pane, outer]) {
      Object.defineProperties(node, { scrollHeight: { value: 900 }, clientHeight: { value: 300 } });
    }
    await userEvent.setup().click(screen.getByRole('button', { name: 'Name this person' }));
    expect(input()).toHaveFocus();
    expect(pane.scrollTop).toBe(100);
    expect(outer.scrollTop).toBe(0);
    expect(container).toContainElement(input());
    geometry.mockRestore();
  });

  it('keeps an explicitly retained controlled draft across cancel and keyed identity/tenant changes', async () => {
    const Harness = ({ scope }: { scope: string }) => {
      const [draft, setDraft] = React.useState('');
      const [open, setOpen] = React.useState(false);
      return <div><button onClick={() => setOpen(true)}>Name {scope}</button>
        {open && <NameFaceControl options={[]} value={draft} onValueChange={setDraft}
          onCommit={() => { throw new Error('No commit expected'); }} onCancel={() => setOpen(false)}
          visibleLabel="Person name" inputId="retained-draft" commitLabel="Save name" />}
      </div>;
    };
    const user = userEvent.setup();
    const view = render(<Harness key="tenant-a/face-a" scope="A" />);
    await user.click(screen.getByRole('button', { name: 'Name A' }));
    await user.keyboard('Zoe{Escape}');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Name A' })).toHaveFocus());
    await user.keyboard('{Enter}');
    expect(input()).toHaveValue('Zoe');
    const draft = input() as HTMLInputElement;
    draft.setSelectionRange(1, 2);
    view.rerender(<Harness key="tenant-a/face-a" scope="A" />);
    expect(input()).toBe(draft);
    expect([draft.selectionStart, draft.selectionEnd]).toEqual([1, 2]);
    view.rerender(<Harness key="tenant-b/face-b" scope="B" />);
    await user.click(screen.getByRole('button', { name: 'Name B' }));
    expect(input()).toHaveValue('');
  });

  it('retains the actual draft through a failed write and retry, announcing pending and acknowledgement', async () => {
    allowCommit = true;
    client.setQueryData(queryKeys.roster.entries(), roster);
    const first = hold('commit');
    mountEditor();
    const user = userEvent.setup();
    await user.type(input(), 'Pat Nguyen');
    const retainedInput = input() as HTMLInputElement;
    retainedInput.setSelectionRange(4, 6);
    await user.click(screen.getByRole('button', { name: 'Save name' }));
    await waitFor(() => expect(count('commit')).toBe(1));
    expect(requests.find(({ route }) => route === 'commit')?.body).toEqual({ roster_entry_id: 9, new_entry_name: null });
    expect(input()).toHaveValue('Pat Nguyen');
    expect(input()).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Saving…');
    await act(async () => { first.resolve({ code: 'unavailable', message: 'Name could not be saved. Try again.' }, 503); await first.promise; });
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/./), { timeout: 3000 });
    expect(input()).toHaveValue('Pat Nguyen');
    expect(input()).toBeEnabled();
    expect(input()).toBe(retainedInput);
    expect([retainedInput.selectionStart, retainedInput.selectionEnd]).toEqual([4, 6]);
    const retry = hold('commit');
    await user.click(screen.getByRole('button', { name: 'Save name' }));
    await waitFor(() => expect(count('commit')).toBe(2));
    await user.click(screen.getByRole('button', { name: /Saving/ }));
    expect(count('commit')).toBe(2);
    await act(async () => { retry.resolve({ cluster_id: CLUSTER_ID, person_id: 9, person_uuid: 'person-9', person_name: 'Pat Nguyen', updated_at: '2026-10-18T00:00:00Z' }); await retry.promise; });
    expect(await screen.findByRole('button', { name: 'Saved!' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Saved!');
    expect(input()).toHaveValue('Pat Nguyen');
    expect(screen.queryByText(/synced|remote sync complete/i)).not.toBeInTheDocument();
  });
});
