import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import type { RosterClusterCommitResponse, RosterEntry } from '../../../../api/rosterApi';
import { DEFAULT_FETCH_TIMEOUT_MS } from '../../../../utils/http';
import { ClusterLabelingPanel } from '../ClusterLabelingPanel';
import { CLUSTER_MUTATION_ERROR_COPY } from '../clusterMutationUtils';

const CLUSTERS = '/wp-json/acx/v1/recognition/clusters';
const ROSTER = '/wp-json/acx/v1/roster';
const CLUSTER_ID = 'hanging-closest-fixture';
const person: RosterEntry = {
  id: 42, name: 'Slate Willow', person_uuid: 'fixture-person-42', tags: [],
  cluster_count: 0, clusters: [], queue_memberships: [],
  updated_at: '2026-10-15T00:00:00Z', source_version: 1,
  projection_status: 'current', projection_refreshed_at: null,
};
const closestBody = {
  model_id: 'fixture-model', embedding_model: 'fixture-model',
  computed_at: '2026-10-15T00:00:00Z', probe_face_count: 1,
  reference_face_count: 1, quality_flag: 'ok',
  thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
  candidates: [],
};
const commitBody: RosterClusterCommitResponse = {
  cluster_id: CLUSTER_ID, person_id: person.id, person_uuid: person.person_uuid,
  person_name: person.name, updated_at: person.updated_at,
};
const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
}));
interface RequestRecord {
  url: URL;
  method: string;
  body: string | null | undefined;
  signal: AbortSignal | null | undefined;
}

describe('ClusterLabelingPanel hanging closest read and commit budget', () => {
  let client: QueryClient;
  let requests: RequestRecord[];
  let unexpectedRoutes: string[];
  let closestMode: 'hang' | 'quick' | 'error';
  let commitHangs: boolean;
  let duplicateFails: boolean;
  let releasePending: (() => void)[];
  let onLabel: ReturnType<typeof vi.fn<(label: string) => void>>;

  const closestReads = () => requests.filter(({ url }) => url.pathname.endsWith('/roster-candidates'));
  const writes = () => requests.filter(({ method }) => method !== 'GET');
  const flush = async () => {
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  };
  const advance = async (milliseconds: number) => {
    await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
  };
  const openPanel = async () => {
    render(
      <QueryClientProvider client={client}>
        <ClusterLabelingPanel clusterId={CLUSTER_ID} onClose={vi.fn()} onLabel={onLabel} />
      </QueryClientProvider>,
    );
    await flush();
    expect(closestReads()).toHaveLength(1);
    expect(closestReads()[0].url.searchParams.get('top_k')).toBe('5');
    expect(writes()).toHaveLength(0);
    expect(screen.getByRole('combobox', { name: 'Name' })).toBeEnabled();
  };
  const enterAndSave = async (name: string) => {
    fireEvent.change(screen.getByRole('combobox', { name: 'Name' }), { target: { value: name } });
    await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Save name' }));
    await flush();
  };
  const expectBothAlerts = () => {
    // Query the collection synchronously: a single findByRole('alert') is ambiguous here.
    const alerts = screen.getAllByRole('alert');
    expect(alerts).toHaveLength(2);
    expect(alerts.filter((alert) => alert.textContent?.includes(CLUSTER_MUTATION_ERROR_COPY.timeout))).toHaveLength(1);
    const optionalErrors = alerts.filter((alert) => alert.textContent?.includes('Could not load name suggestions.'));
    expect(optionalErrors).toHaveLength(1);
    expect(within(optionalErrors[0]).getByRole('button', { name: 'Retry' })).toBeEnabled();
    alerts.forEach((alert) => expect(alert).toBeVisible());
  };

  beforeEach(() => {
    vi.useFakeTimers();
    requests = [];
    unexpectedRoutes = [];
    releasePending = [];
    closestMode = 'hang';
    commitHangs = true;
    duplicateFails = false;
    onLabel = vi.fn<(label: string) => void>();
    client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    registerConfig({
      nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        recognitionClusters: CLUSTERS,
        rosterEntries: `${ROSTER}/entries`,
        rosterClusters: `${ROSTER}/clusters`,
      },
    });
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, window.location.origin);
      const method = init?.method ?? 'GET';
      requests.push({ url, method, body: typeof init?.body === 'string' ? init.body : null, signal: init?.signal });
      if (method === 'GET' && url.pathname === `${ROSTER}/entries`) {
        return json([person]);
      }
      if (method === 'GET' && url.pathname === `${CLUSTERS}/${CLUSTER_ID}/members`) {
        return json({ members: [], limit: 500, total: 0, truncated: false });
      }
      if (method === 'GET' && url.pathname === CLUSTERS) {
        if (duplicateFails && url.searchParams.get('limit') === '10') {
          return json({ code: 'fixture_lookup_failure' }, 503);
        }
        return json({ clusters: [], limit: Number(url.searchParams.get('limit')), total: 0, truncated: false });
      }
      if (method === 'GET' && url.pathname === `${CLUSTERS}/${CLUSTER_ID}/roster-candidates`) {
        if (closestMode === 'quick') {
          return json(closestBody);
        }
        if (closestMode === 'error') {
          return json({ code: 'fixture_optional_failure' }, 503);
        }
        // No response ever arrives; only the real HTTP backstop can reject this read.
        return new Promise((_resolve, reject) => {
          const abort = () => reject(new DOMException('Fixture read aborted', 'AbortError'));
          init?.signal?.addEventListener('abort', abort, { once: true });
          releasePending.push(() => {
            init?.signal?.removeEventListener('abort', abort);
            abort();
          });
        });
      }
      if (method === 'POST' && url.pathname === `${ROSTER}/clusters/${CLUSTER_ID}/commit`) {
        if (commitHangs) {
          // Deliberately signal-deaf: the interactive race must release the UI too.
          return new Promise((resolve) => { releasePending.push(() => resolve(new Response(null, { status: 204 }))); });
        }
        return json(commitBody);
      }
      if (method === 'PATCH' && url.pathname === `${CLUSTERS}/${CLUSTER_ID}`) {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      unexpectedRoutes.push(`${method} ${url.pathname}`);
      return json({ code: 'unexpected_fixture_route' }, 500);
    }));
  });

  afterEach(async () => {
    cleanup();
    await client.cancelQueries();
    client.clear();
    await act(async () => {
      releasePending.forEach((release) => release());
      await Promise.resolve();
    });
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    resetConfigCache();
    expect(unexpectedRoutes).toEqual([]);
  });

  it('aborts the commit at exactly 3000ms while closest hangs, then shows both timeout and optional-read errors', async () => {
    await openPanel();
    const closestSignal = closestReads()[0].signal;
    expect(closestSignal?.aborted).toBe(false);
    await enterAndSave(person.name);
    expect(writes()).toHaveLength(1);
    expect(writes()[0].method).toBe('POST');
    expect(writes()[0].body).toBe(JSON.stringify({ roster_entry_id: person.id, new_entry_name: null }));
    const commitSignal = writes()[0].signal;
    expect(commitSignal).toBeInstanceOf(AbortSignal);
    expect(commitSignal?.aborted).toBe(false);
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Saving...' }));
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Name' }), { key: 'Enter' });
    await flush();
    expect(writes()).toHaveLength(1);

    await advance(2999);
    expect(commitSignal?.aborted).toBe(false);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await advance(1);
    expect(commitSignal?.aborted).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent(CLUSTER_MUTATION_ERROR_COPY.timeout);
    expect(screen.getByRole('button', { name: 'Save name' })).toBeEnabled();
    expect(closestSignal?.aborted).toBe(false);
    expect(onLabel).not.toHaveBeenCalled();

    // Separate phases: the optional GET's HTTP backstop is not the 3s write budget.
    await advance(DEFAULT_FETCH_TIMEOUT_MS);
    expect(closestSignal?.aborted).toBe(true);
    expectBothAlerts();
    expect(writes()).toHaveLength(1);
    expect(closestReads()).toHaveLength(1);

    fireEvent.change(screen.getByRole('combobox', { name: 'Name' }), { target: { value: 'Manual recovery' } });
    await flush();
    expect(screen.getByRole('combobox', { name: 'Name' })).toHaveValue('Manual recovery');
    expect(screen.getByRole('button', { name: 'Save name' })).toBeEnabled();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load name suggestions.');
    closestMode = 'quick';
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await flush();
    expect(closestReads()).toHaveLength(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(writes()).toHaveLength(1);
    await enterAndSave('Manual recovery');
    expect(writes()).toHaveLength(2);
    expect(writes()[1].method).toBe('PATCH');
    expect(onLabel).toHaveBeenCalledExactlyOnceWith('Manual recovery');
  });

  it.each(['hang', 'quick', 'error'] as const)('allows a healthy manual commit with a %s optional closest read', async (mode) => {
    closestMode = mode;
    await openPanel();
    await enterAndSave('Manual Cedar');
    expect(writes()).toHaveLength(1);
    expect(writes()[0].method).toBe('PATCH');
    expect(writes()[0].body).toBe(JSON.stringify({ label: 'Manual Cedar' }));
    expect(onLabel).toHaveBeenCalledExactlyOnceWith('Manual Cedar');
    const alerts = screen.queryAllByRole('alert');
    expect(alerts).toHaveLength(mode === 'error' ? 1 : 0);
    if (mode === 'error') {
      expect(alerts[0]).toHaveTextContent('Could not load name suggestions.');
    }
  });

  it.each(['quick', 'error'] as const)('preserves a healthy roster-ID commit with a %s optional closest read', async (mode) => {
    closestMode = mode;
    commitHangs = false;
    await openPanel();
    await enterAndSave(person.name);
    expect(writes()).toHaveLength(1);
    expect(writes()[0].method).toBe('POST');
    expect(writes()[0].body).toBe(JSON.stringify({ roster_entry_id: person.id, new_entry_name: null }));
    expect(onLabel).toHaveBeenCalledExactlyOnceWith(person.name);
  });

  it('keeps the submit-time duplicate guard fail-closed while closest hangs, then recovers on explicit save', async () => {
    duplicateFails = true;
    await openPanel();
    await enterAndSave('Manual Cedar');
    expect(writes()).toHaveLength(0);
    expect(onLabel).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Could not check whether that name is already in use. Please try again.');
    duplicateFails = false;
    await enterAndSave('Manual Cedar');
    expect(writes()).toHaveLength(1);
    expect(onLabel).toHaveBeenCalledExactlyOnceWith('Manual Cedar');
  });
});
