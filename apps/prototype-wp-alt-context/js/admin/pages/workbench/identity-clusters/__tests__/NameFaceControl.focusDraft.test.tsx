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

// jsdom has no layout or native scrolling. Model the measured nested Library
// scrollports, with rects derived from content offsets and actual scrollTop.
// A layout delivery can move the row without resizing the name editor itself.
const installNamingLayout = (viewport: '1024' | '1440') => {
  const compact = viewport === '1024';
  const libraryBottom = compact ? 730 : 856;
  const rowsTop = compact ? 585.953125 : 760;
  let rowsHeight = compact ? 128 : 160;
  let growth = 0;
  const rect = (top: number, height: number): DOMRect => new DOMRect(744.6875, top, 150.21875, height);
  const observers: LayoutResizeObserver[] = [];
  class LayoutResizeObserver implements ResizeObserver {
    targets = new Set<Element>();
    constructor(private callback: ResizeObserverCallback) { observers.push(this); }
    observe(target: Element) { this.targets.add(target); }
    unobserve(target: Element) { this.targets.delete(target); }
    disconnect() { this.targets.clear(); }
    deliver(target: Element) {
      this.callback([{ target, contentRect: target.isConnected ? target.getBoundingClientRect() : new DOMRect(),
        borderBoxSize: [], contentBoxSize: [], devicePixelContentBoxSize: [] }], this);
    }
  }
  vi.stubGlobal('ResizeObserver', LayoutResizeObserver);
  const library = () => screen.getByTestId('library-pane');
  const rows = () => screen.getByTestId('media-pane');
  const origin = () => rowsTop - library().scrollTop;
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    if (this.dataset.testid === 'library-pane') return rect(100, libraryBottom - 100);
    if (this.dataset.testid === 'media-pane') return rect(origin(), rowsHeight);
    const editorTop = origin() + 460 + growth - rows().scrollTop;
    if (this.classList.contains('acx-identity-cluster__edit')) return rect(editorTop, 152.609375);
    if (this.getAttribute('role') === 'combobox') return rect(editorTop + 26.203125, 40);
    if (this.tagName === 'BUTTON' && this.textContent === 'Name this person') {
      return rect(origin() + 486.203125 - rows().scrollTop, 26.203125);
    }
    return rect(0, 0);
  });
  // Emulate native nearest scrolling through every scroll container, separately
  // from the visibility oracle below. Include the existing 8px scroll padding
  // and 8px control margin. Do not give the product a fixed passing input rect.
  const scroll = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(function (this: Element) {
    for (let parent = this.parentElement; parent; parent = parent.parentElement) {
      if (!/(auto|scroll|hidden)/.test(getComputedStyle(parent).overflowY)) continue;
      const bounds = this.getBoundingClientRect();
      const pane = parent.getBoundingClientRect();
      const top = pane.top + 16;
      const bottom = pane.top + parent.clientHeight - 16;
      if (bounds.top < top && bounds.bottom > bottom) continue;
      if (bounds.top < top) parent.scrollTop += bounds.top - top;
      else if (bounds.bottom > bottom) parent.scrollTop += bounds.bottom - bottom;
    }
  });
  // Deliberately preserve native focus, supplying the actual element via .call.
  // eslint-disable-next-line @typescript-eslint/unbound-method
  const browserFocus = HTMLElement.prototype.focus;
  const focus = vi.spyOn(HTMLElement.prototype, 'focus').mockImplementation(function (this: HTMLElement, options?: FocusOptions) {
    browserFocus.call(this, options);
    if (!options?.preventScroll) this.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  });
  const clips = (target: HTMLElement) => {
    const bounds = target.getBoundingClientRect();
    const failures = [];
    if (bounds.top < 0 || bounds.bottom > (compact ? 900 : 1080)) failures.push('viewport');
    for (let parent = target.parentElement; parent; parent = parent.parentElement) {
      if (!/(auto|scroll|hidden|clip)/.test(getComputedStyle(parent).overflowY)) continue;
      const pane = parent.getBoundingClientRect();
      if (bounds.top < pane.top || bounds.bottom > pane.top + parent.clientHeight
        || bounds.left < pane.left || bounds.right > pane.right) failures.push(parent.dataset.testid);
    }
    return failures;
  };
  const deliver = (target: Element) => act(() => {
    observers.filter((observer) => observer.targets.has(target)).forEach((observer) => observer.deliver(target));
  });
  return {
    clips, observers, deliver,
    focusCount: (target: HTMLElement) => focus.mock.contexts.filter((node) => node === target).length,
    scrollCount: () => scroll.mock.calls.length,
    attach: () => {
      Object.defineProperties(rows(), {
        scrollHeight: { get: () => 5049 + growth }, clientHeight: { get: () => rowsHeight },
      });
      Object.defineProperties(library(), {
        scrollHeight: { get: () => Math.max(libraryBottom - 100 + 43, rowsTop + rowsHeight - 100 + 16) },
        clientHeight: { get: () => libraryBottom - 100 },
      });
      for (const node of [rows(), library()]) {
        let scroll = 0;
        Object.defineProperty(node, 'scrollTop', {
          get: () => scroll,
          set: (next: number) => { scroll = Math.max(0, Math.min(next, node.scrollHeight - node.clientHeight)); },
        });
      }
    },
    settleRow: () => { growth = compact ? 338.0625 : 114.87625; },
    shrinkRows: () => { rowsHeight = 80; },
  };
};

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

  it.each(['1024', '1440'] as const)('keeps the focused draft inside every clipping ancestor after %s Library layout settles and resizes', async (viewport) => {
    const read = hold('roster');
    const layout = installNamingLayout(viewport);
    render(<section data-testid="library-pane" style={{ overflowY: 'auto' }}>
      <div data-testid="media-pane" style={{ overflowY: 'auto' }}><table><tbody><tr><td data-testid="evidence-cell">
        <IdentityClusterItem cluster={{
        key: CLUSTER_ID, clusterId: CLUSTER_ID, label: null,
        isAutoLabel: false, clusteringPending: false, members: [member],
      }} canLabel canMutate /></td></tr></tbody></table></div>
    </section>, { wrapper: createQueryWrapper(client) });
    layout.attach();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Name this person' }));
    const draft = input() as HTMLInputElement;
    expect(draft).toHaveFocus();
    await userEvent.setup().keyboard('Zoe');
    draft.setSelectionRange(1, 2);
    const focusCount = () => layout.focusCount(draft);
    expect(focusCount()).toBe(1);
    const select = vi.spyOn(draft, 'select');
    layout.settleRow();
    // Real failure sequence: a later table/ancestor layout moves a still-focused
    // input. A viewport-only check also misses the 1440 ancestor clipping case.
    expect(layout.clips(draft)).toContain('media-pane');
    layout.deliver(screen.getByTestId('evidence-cell'));
    expect(layout.clips(draft), 'input fully intersects viewport AND every clipping ancestor').toEqual([]);
    act(() => read.resolve(roster));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save name' })).toBeEnabled());
    layout.deliver(draft.closest('.acx-identity-cluster__edit')!);
    layout.shrinkRows();
    layout.deliver(screen.getByTestId('media-pane'));
    expect(layout.clips(draft)).toEqual([]);
    expect(input()).toBe(draft);
    expect(draft).toHaveFocus();
    expect(draft).toHaveValue('Zoe');
    expect([draft.selectionStart, draft.selectionEnd]).toEqual([1, 2]);
    expect(focusCount()).toBe(1);
    expect(select).not.toHaveBeenCalled();

    if (draft.getAttribute('aria-expanded') === 'true') {
      await userEvent.setup().keyboard('{Escape}');
      expect(draft).toHaveFocus();
      expect(draft).toHaveAttribute('aria-expanded', 'false');
    }
    await userEvent.setup().keyboard('{Escape}');
    const opener = screen.getByRole('button', { name: 'Name this person' });
    await waitFor(() => expect(opener).toHaveFocus());
    expect(layout.clips(opener)).toEqual([]);
    await userEvent.setup().keyboard('{Enter}');
    expect(input()).toHaveFocus();
    expect(input()).toHaveValue('');
    expect(layout.clips(input())).toEqual([]);

    // A size notification must neither scroll back to a field the user left,
    // nor revive focus after navigation/unmount, including a queued delivery.
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    cancel.focus();
    const pane = screen.getByTestId('media-pane');
    const previousScroll = pane.scrollTop;
    layout.settleRow();
    layout.deliver(screen.getByTestId('evidence-cell'));
    expect(cancel).toHaveFocus();
    expect(pane.scrollTop).toBe(previousScroll);
    const editor = input().closest('.acx-identity-cluster__edit')!;
    cleanup();
    render(<button>Another route</button>);
    const nextRoute = screen.getByRole('button', { name: 'Another route' });
    nextRoute.focus();
    const scrollCalls = layout.scrollCount();
    layout.observers.forEach((observer) => observer.deliver(editor));
    expect(layout.observers.every((observer) => observer.targets.size === 0)).toBe(true);
    expect(nextRoute).toHaveFocus();
    expect(layout.scrollCount()).toBe(scrollCalls);
    expect(focusCount()).toBe(1);
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
