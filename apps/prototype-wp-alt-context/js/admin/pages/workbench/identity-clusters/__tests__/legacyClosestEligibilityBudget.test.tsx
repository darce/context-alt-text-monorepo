import { onlineManager } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import type { IdentityBatchSuggestionsResponse } from '../../../../api/recognition';
import type { RosterCandidatesResponse } from '../../../../api/recognition/rosterCandidatesApi';
import type { RosterEntry } from '../../../../api/rosterApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { identityBatchIdsKey } from '../suggestionProjection';
import { useClusterSuggestionsLoader } from '../useClusterSuggestionsLoader';

const SOURCE = 'identity-legacy-source';
const CLUSTER = 'legacy-editable-cluster';
const TARGET = 'persisted-target-cluster';
const SUGGESTION = 'persisted-identity-proposal';
const closestKey = queryKeys.clusters.rosterCandidates(CLUSTER, 5);
const batchKey = queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey([SOURCE]));
const emptyBatch: IdentityBatchSuggestionsResponse = { matches: { [SOURCE]: [] } };
const pendingBatch: IdentityBatchSuggestionsResponse = { matches: { [SOURCE]: [{
  cluster_id: TARGET, label: 'Bea Burke', similarity: 0.41,
  identity_count: 9, suggestion_id: SUGGESTION,
}] } };
const roster: RosterEntry[] = ['Ellyn Heald', 'Pat Nguyen'].map((name, index) => ({
  id: index + 7, name, person_uuid: `fixture-person-${index + 7}`, tags: [],
  cluster_count: 1, clusters: [], queue_memberships: [],
  updated_at: '2026-10-15T00:00:00Z', source_version: 1,
  projection_status: 'current', projection_refreshed_at: null,
}));
const bands = ['strong', 'possible', 'none'] as const;
let body: RosterCandidatesResponse;
let client: ReturnType<typeof buildTestQueryClient>;
let closestStatus: number;
let batchStatus: number;
let requests: { path: string; method: string }[];
let unexpected: string[];
const closestReads = () => requests.filter(({ path }) => path.endsWith('/roster-candidates'));
const json = (value: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
}));

beforeEach(() => {
  requests = [];
  unexpected = [];
  closestStatus = 200;
  batchStatus = 200;
  onlineManager.setOnline(true);
  body = {
    model_id: 'fixture-model', embedding_model: 'fixture-model',
    computed_at: '2026-10-15T00:00:00Z', probe_face_count: 1, reference_face_count: 2,
    quality_flag: 'ok',
    thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
    candidates: [{ cluster_id: 'closest-person-cluster', name: 'Stale snapshot',
      roster_entry_id: 7, similarity: 0.12, band: 'none' }],
  };
  client = buildTestQueryClient();
  registerConfig({
    nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      rosterEntries: '/wp-json/acx/v1/roster/entries',
      recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
      recognitionIdentitySuggestions: '/wp-json/acx/v1/recognition/identities',
    },
  });
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    requests.push({ path: url.pathname, method });
    if (method === 'GET') {
      if (url.pathname === `/wp-json/acx/v1/recognition/clusters/${CLUSTER}/roster-candidates`) {
        expect(url.searchParams.get('top_k')).toBe('5');
        return json(closestStatus === 200 ? body : { code: 'service_unavailable' }, closestStatus);
      }
      if (url.pathname === '/wp-json/acx/v1/recognition/identities/suggestions') {
        return json(batchStatus === 200 ? emptyBatch : { code: 'service_unavailable' }, batchStatus);
      }
      if (url.pathname === '/wp-json/acx/v1/roster/entries') return json(roster);
      if (url.pathname === '/wp-json/acx/v1/recognition/clusters') {
        return json({ clusters: [], limit: 50, offset: 0, total: 0, truncated: false });
      }
    }
    unexpected.push(`${method} ${url.pathname}`);
    return json({ code: 'unexpected_fixture_route' }, 500);
  }));
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  expect(requests.filter(({ method }) => method !== 'GET')).toEqual([]);
  expect(client.getMutationCache().getAll()).toHaveLength(0);
  client.clear();
  onlineManager.setOnline(true);
  vi.unstubAllGlobals();
  resetConfigCache();
  expect(unexpected, 'fixture errors are distinct from eligibility failures').toEqual([]);
});

const mount = () => renderHook(({ enabled, labelInput }) => useClusterSuggestionsLoader({
  identityId: SOURCE, editableClusterId: CLUSTER, enabled, labelInput, debounceMs: 0,
}), { initialProps: { enabled: true, labelInput: '' }, wrapper: createQueryWrapper(client) });
const settle = async () => {
  await waitFor(() => expect(client.isFetching()).toBe(0));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)); });
};
const warmThenFail = async (band: typeof bands[number]) => {
  body.candidates[0] = { ...body.candidates[0], band, similarity: band === 'strong' ? 0.8 : 0.12 };
  const view = mount();
  await waitFor(() => expect(view.result.current.rosterCandidateOptions).toHaveLength(1));
  expect(view.result.current.rosterCandidateOptions?.[0]).toMatchObject({
    value: 'person:7', source: 'person', roster_entry_id: 7,
    cluster_id: 'closest-person-cluster', label: 'Ellyn Heald', band,
  });
  expect(view.result.current.rosterCandidateOptions?.[0]).not.toHaveProperty('suggestion_id');
  closestStatus = 503;
  await act(async () => { await client.invalidateQueries({ queryKey: closestKey }); });
  await waitFor(() => expect(view.result.current.isError).toBe(true));
  expect(view.result.current.rosterCandidateOptions).toHaveLength(1);
  await settle();
  return view;
};

describe.each(['pending proposal', 'disabled'] as const)('legacy closest hard eligibility: %s', (cause) => {
  const makeIneligible = async (view: ReturnType<typeof mount>) => {
    if (cause === 'pending proposal') {
      act(() => { client.setQueryData(batchKey, pendingBatch); });
      await waitFor(() => expect(view.result.current.identityProjection?.[0]).toMatchObject({
        identityId: SOURCE, clusterId: TARGET, suggestionId: SUGGESTION,
      }));
    } else {
      view.rerender({ enabled: false, labelInput: '' });
    }
  };

  it.each(bands)('masks cached %s evidence and errors, preserves ordinary lookup, and recovers eligibility', async (band) => {
    const view = await warmThenFail(band);
    await makeIneligible(view);
    expect(view.result.current.rosterCandidateOptions).toEqual([]);
    expect(view.result.current.isError).toBe(false);
    expect(view.result.current.namingOptions).toContainEqual(expect.objectContaining({
      value: 'person:8', label: 'Pat Nguyen', source: 'person',
    }));
    const before = requests.length;
    act(() => { view.result.current.retry?.(); });
    await settle();
    expect(requests).toHaveLength(before);

    closestStatus = 200;
    if (cause === 'pending proposal') {
      act(() => { client.setQueryData(batchKey, emptyBatch); });
    } else {
      view.rerender({ enabled: true, labelInput: 'Pat' });
    }
    await waitFor(() => expect(view.result.current.isError).toBe(false));
    await waitFor(() => expect(client.getQueryState(closestKey)?.status).toBe('success'));
    expect(view.result.current.rosterCandidateOptions?.[0]).toMatchObject({ band, roster_entry_id: 7 });
    expect(closestReads()).toHaveLength(3);
  });

  it.each(bands)('Retry spends zero GETs for cached failed %s evidence after eligibility is lost', async (band) => {
    const view = await warmThenFail(band);
    await makeIneligible(view);
    const before = requests.length;
    act(() => { view.result.current.retry?.(); });
    await settle();
    expect(requests).toHaveLength(before);
    await act(async () => { await client.invalidateQueries({ queryKey: closestKey }); });
    await settle();
    expect(requests).toHaveLength(before);
  });
});

it('retains eligible cached choices and errors during a network pause, then retries without losing typed lookup', async () => {
  const view = await warmThenFail('none');
  act(() => { onlineManager.setOnline(false); });
  view.rerender({ enabled: true, labelInput: 'Pat' });
  expect(view.result.current.rosterCandidateOptions?.[0]).toMatchObject({ band: 'none', roster_entry_id: 7 });
  expect(view.result.current.isError).toBe(true);
  const before = requests.length;
  await settle();
  expect(requests).toHaveLength(before);
  closestStatus = 200;
  act(() => { onlineManager.setOnline(true); });
  await settle();
  act(() => { view.result.current.retry?.(); });
  await waitFor(() => expect(view.result.current.isError).toBe(false));
  expect(view.result.current.namingOptions.map(({ label }) => label)).toEqual(['Pat Nguyen']);
  expect(view.result.current.rosterCandidateOptions?.[0]).toMatchObject({ label: 'Ellyn Heald', band: 'none' });
});

it('masks a disabled identity-read error and Retry spends zero GETs, then recovers on enable', async () => {
  batchStatus = 503;
  const view = mount();
  await waitFor(() => expect(view.result.current.isError).toBe(true));
  await settle();
  view.rerender({ enabled: false, labelInput: '' });
  const before = requests.length;
  act(() => { view.result.current.retry?.(); });
  await settle();
  expect(requests).toHaveLength(before);
  expect(view.result.current.isError).toBe(false);
  expect(closestReads()).toHaveLength(0);
  batchStatus = 200;
  view.rerender({ enabled: true, labelInput: '' });
  await waitFor(() => expect(view.result.current.rosterCandidateOptions).toHaveLength(1));
  expect(view.result.current.isError).toBe(false);
});
