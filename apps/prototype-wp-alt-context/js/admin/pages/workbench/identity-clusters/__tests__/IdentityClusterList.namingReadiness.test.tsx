/**
 * Ungrouped residue editor naming readiness (UXREC-1-DEMO-01).
 *
 * The per-cluster editor separates naming readiness (the local roster read) from
 * advisory loading (identity batch / labelled-cluster reads) since CURUX1-N-01.
 * These cases port that contract to the ungrouped `Find similar / Name` editor,
 * driving the real `useClusterSuggestions` loader through the HTTP boundary.
 */

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import type { DetectedIdentity } from '../../../../api/recognition';
import type { RosterEntry } from '../../../../api/rosterApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { IdentityClusterList } from '../IdentityClusterList';

// List-level hooks are outside the naming-readiness contract; no writes are expected.
vi.mock('../useClusterMutations', () => ({
  useClusterMutations: () => ({
    isPending: false,
    isReverting: false,
    merge: vi.fn(),
    assignToCluster: vi.fn(),
    rename: vi.fn(),
    createClusterForIdentity: vi.fn(),
    reassign: vi.fn(),
    split: vi.fn(),
    revertMerge: vi.fn(),
    rejectSuggestion: vi.fn(),
    splitGate: { disabled: false, title: undefined, 'aria-disabled': false },
  }),
}));
vi.mock('../useInlineSuggestionBatch', () => ({
  useInlineSuggestionBatch: () => ({ getMatch: () => undefined, isLoading: false, isError: false }),
}));
vi.mock('../usePendingMergeTwins', () => ({
  usePendingMergeTwins: () => ({
    mergeSuggestions: [],
    truncated: false,
    scheduleAcceptMerge: vi.fn(),
    scheduleRejectMerge: vi.fn(),
    isCardPending: () => false,
  }),
}));

const IDENTITY_ID = 'identity-unnamed';
const person = (id: number, name: string): RosterEntry => ({
  id, name, person_uuid: `person-${id}`, tags: [], cluster_count: 1,
  clusters: [], queue_memberships: [], updated_at: '2026-10-15T00:00:00Z',
  source_version: 1, projection_status: 'current',
  projection_refreshed_at: '2026-10-15T00:00:00Z',
});
const roster = [person(7, 'Ellyn Heald'), person(9, 'Pat Nguyen')];
const member: DetectedIdentity = {
  identity_id: IDENTITY_ID, representative_id: 'rep-1', media_id: 1,
  cluster_id: null, cluster_label: null, is_auto_label: false,
  is_pinned: false, bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1, similarity: 1, detected_at: '',
};
const emptyClusters = { clusters: [], limit: 50, offset: 0, total: 0, truncated: false };
const emptyBatch = { matches: { [IDENTITY_ID]: [] } };
const json = (body: unknown, status = 200): Response => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});
const deferredResponse = () => {
  let finish: (response: Response) => void = () => { throw new Error('Deferred response not initialized'); };
  const promise = new Promise<Response>((resolve) => { finish = resolve; });
  return { promise, resolve: (body: unknown, status = 200) => finish(json(body, status)) };
};
type Route = 'roster' | 'batch' | 'clusters';
interface RequestRecord { route: Route; method: string; url: URL }
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
const rosterQuery = () => client.getQueryCache().find({ queryKey: queryKeys.roster.entries(), exact: true });

beforeEach(() => {
  requests = [];
  unexpected = [];
  client = buildTestQueryClient();
  registerConfig({
    nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      rosterEntries: '/wp-json/acx/v1/roster/entries',
      recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
      recognitionIdentitySuggestions: '/wp-json/acx/v1/recognition/identities',
    },
  });
  responses = {
    roster: () => Promise.resolve(json(roster)),
    batch: () => Promise.resolve(json(emptyBatch)),
    clusters: () => Promise.resolve(json(emptyClusters)),
  };
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    let route: Route;
    if (url.pathname === '/wp-json/acx/v1/roster/entries') route = 'roster';
    else if (url.pathname === '/wp-json/acx/v1/recognition/identities/suggestions') route = 'batch';
    else if (url.pathname === '/wp-json/acx/v1/recognition/clusters') route = 'clusters';
    else {
      unexpected.push(`${method} ${url.pathname}`);
      return Promise.reject(new Error(`Unexpected fixture route: ${method} ${url.pathname}`));
    }
    requests.push({ route, method, url });
    if (method !== 'GET') {
      unexpected.push(`${method} ${url.pathname}`);
      return Promise.reject(new Error('Naming readiness must be read-only'));
    }
    return responses[route]();
  }));
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  client.clear();
  vi.unstubAllGlobals();
  resetConfigCache();
  expect(requests.every(({ method }) => method === 'GET')).toBe(true);
  expect(unexpected, 'all requests use explicit fixture routes').toEqual([]);
});

const openEditor = () => {
  render(<IdentityClusterList identities={[member]} />, { wrapper: createQueryWrapper(client) });
  fireEvent.click(screen.getByRole('button', { name: 'Find similar / Name' }));
};
const input = () => screen.getByRole('combobox', { name: 'Person name' });
const saveButton = () => screen.getByRole('button', { name: 'Save name' });
const loadingPeople = () => screen.queryByText('Loading people…');
const rosterReady = () => waitFor(() => expect(rosterQuery()?.state.status).toBe('success'));
const advisorySettled = () => waitFor(() => {
  const advisory = client.getQueryCache().findAll({ type: 'active', predicate: (query) => query !== rosterQuery() });
  expect(advisory.length).toBeGreaterThanOrEqual(2);
  expect(advisory.every((query) => query.state.status === 'success' && query.state.fetchStatus === 'idle')).toBe(true);
});

describe('DEMO-01 ungrouped editor: naming waits only on the roster (INT-08, RES-02)', () => {
  it.each(['batch', 'clusters'] as const)(
    'pending advisory %s read keeps naming typeable and Save enabled once the roster succeeds',
    async (route) => {
      hold(route);
      openEditor();
      await rosterReady();
      await waitFor(() => expect(count(route)).toBeGreaterThanOrEqual(1));
      await waitFor(() => expect(input(), 'advisory read must not gate naming').toBeEnabled());
      expect(loadingPeople()).not.toBeInTheDocument();
      const user = userEvent.setup();
      await user.type(input(), 'Zoe');
      expect(input()).toHaveValue('Zoe');
      expect(input()).toHaveFocus();
      expect(saveButton()).toBeEnabled();
      expect(loadingPeople()).not.toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    },
  );

  it('pending roster still protects the editor with Loading people… until it resolves', async () => {
    const pending = hold('roster');
    openEditor();
    await waitFor(() => expect(count('roster')).toBe(1));
    await advisorySettled();
    expect(input()).toBeDisabled();
    expect(saveButton()).toBeDisabled();
    expect(loadingPeople()).toBeInTheDocument();
    act(() => { pending.resolve(roster); });
    await waitFor(() => expect(input()).toBeEnabled());
    expect(loadingPeople()).not.toBeInTheDocument();
    await userEvent.setup().type(input(), 'Zoe');
    expect(saveButton()).toBeEnabled();
  });
});

describe('DEMO-01 ungrouped editor: roster failure is a designed state (RLSE-04)', () => {
  it('shows the roster error with Retry, blocks Save, and Retry refetches only the roster', async () => {
    responses.roster = () => Promise.resolve(json({ code: 'unavailable' }, 503));
    openEditor();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Unable to load people. Retry before naming someone new.');
    expect(screen.queryByText('Could not load name suggestions.')).not.toBeInTheDocument();
    expect(loadingPeople()).not.toBeInTheDocument();
    expect(input(), 'the draft stays editable on roster failure').toBeEnabled();
    await userEvent.setup().type(input(), 'Zoe');
    expect(input()).toHaveValue('Zoe');
    expect(saveButton(), 'naming must wait for a successful roster Retry').toBeDisabled();
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    await advisorySettled();
    const batchReads = count('batch');
    const retry = hold('roster');
    await userEvent.setup().click(within(alert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(count('roster')).toBe(2));
    expect(count('batch'), 'roster Retry does not re-run advisory reads').toBe(batchReads);
    expect(saveButton()).toBeDisabled();
    act(() => { retry.resolve([]); });
    await waitFor(() => expect(input()).toBeEnabled());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(input()).toHaveValue('Zoe');
    expect(saveButton()).toBeEnabled();
  });
});

describe('DEMO-01 ungrouped editor: advisory failure stays separate from roster readiness', () => {
  it('shows the suggestions error while naming stays usable, and its Retry leaves the roster alone', async () => {
    responses.batch = () => Promise.resolve(json({ code: 'unavailable' }, 503));
    openEditor();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not load name suggestions.');
    expect(screen.queryByText('Unable to load people. Retry before naming someone new.')).not.toBeInTheDocument();
    await rosterReady();
    await waitFor(() => expect(input()).toBeEnabled());
    expect(loadingPeople()).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(input(), 'Zoe');
    expect(saveButton()).toBeEnabled();
    hold('batch');
    fireEvent.click(within(alert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(count('batch')).toBe(2));
    expect(count('roster'), 'advisory Retry does not touch the roster read').toBe(1);
    expect(input(), 'a pending advisory Retry must preserve naming').toBeEnabled();
    expect(input()).toHaveValue('Zoe');
    expect(saveButton()).toBeEnabled();
    expect(loadingPeople()).not.toBeInTheDocument();
  });
});
