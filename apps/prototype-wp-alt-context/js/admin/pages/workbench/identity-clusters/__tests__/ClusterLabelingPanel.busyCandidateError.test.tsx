import React from 'react';
import { act, cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache, registerConfig } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import { useClusterRosterCandidates } from '../useClusterRosterCandidates';
import type { RosterEntry } from '../../../../api/rosterApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { ClusterLabelingPanel } from '../ClusterLabelingPanel';
import { commitClusterToRosterEntry } from '../../../../api/rosterApi';
import { updateClusterLabel } from '../../../../api/recognition';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => count === 1 ? single : plural,
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text.replace(/%((\d+)\$)?[sd]/g, (_match, _position, explicit) =>
      String(values[explicit ? Number(explicit) - 1 : index++] ?? ''));
  },
}));
vi.mock('../../../../api/rosterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../../api/rosterApi')>()),
  commitClusterToRosterEntry: vi.fn(),
}));
vi.mock('../../../../api/recognition', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../../api/recognition')>()),
  updateClusterLabel: vi.fn(),
}));
const CLUSTER_ID = 'cluster-unnamed';
const CANONICAL_NAME = 'Ellyn Heald';
const STALE_NAME = 'Gilded Cypress';
const PERSON_ID = 7;
const person: RosterEntry = {
  id: PERSON_ID, name: CANONICAL_NAME, person_uuid: 'person-7', tags: [],
  cluster_count: 1, clusters: [], queue_memberships: [],
  updated_at: '2026-10-15T00:00:00Z', source_version: 1,
  projection_status: 'current', projection_refreshed_at: '2026-10-15T00:00:00Z',
};
const candidateBody = {
  model_id: 'fixture-model', embedding_model: 'fixture-model',
  computed_at: '2026-10-15T00:00:00Z', probe_face_count: 1,
  reference_face_count: 2, quality_flag: 'ok',
  thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
  candidates: [{ cluster_id: 'cluster-ellyn', name: STALE_NAME, similarity: 0.12,
    band: 'none', roster_entry_id: PERSON_ID }],
};
interface RequestRecord { url: URL; method: string }
let requests: RequestRecord[];
let unexpectedRoutes: string[];
let candidateStatus: number;
let client: ReturnType<typeof buildTestQueryClient>;
const candidateRequests = () => requests.filter(({ url }) => url.pathname.endsWith('/roster-candidates'));
const writeRequests = () => requests.filter(({ method }) => method !== 'GET');
const json = (body: unknown, status = 200): Promise<Response> => Promise.resolve(new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
}));

beforeEach(() => {
  vi.clearAllMocks();
  requests = [];
  unexpectedRoutes = [];
  candidateStatus = 200;
  registerConfig({
    nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      rosterEntries: '/wp-json/acx/v1/roster/entries',
      recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
      recognitionIdentitySuggestions: '/wp-json/acx/v1/recognition/identities',
    },
  });
  client = buildTestQueryClient();
  client.setQueryData(queryKeys.roster.entries(), [person]);
  vi.mocked(commitClusterToRosterEntry).mockResolvedValue({
    cluster_id: CLUSTER_ID, person_id: PERSON_ID, person_uuid: 'person-7',
    person_name: CANONICAL_NAME, updated_at: '2026-10-15T00:00:00Z',
  });
  vi.mocked(updateClusterLabel).mockResolvedValue(undefined);
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    requests.push({ url, method });
    if (method === 'GET' && url.pathname === `/wp-json/acx/v1/recognition/clusters/${CLUSTER_ID}/roster-candidates`) {
      return candidateStatus === 200 ? json(candidateBody) : json({ code: 'service_unavailable' }, candidateStatus);
    }
    if (method === 'GET' && url.pathname === '/wp-json/acx/v1/roster/entries') return json([person]);
    if (method === 'GET' && url.pathname === `/wp-json/acx/v1/recognition/clusters/${CLUSTER_ID}/members`) {
      return json({ members: [], limit: 500, offset: 0, total: 0, truncated: false });
    }
    if (method === 'GET' && url.pathname === '/wp-json/acx/v1/recognition/clusters') {
      return json({ clusters: [], limit: 20, offset: 0, total: 0, truncated: false });
    }
    if (method === 'GET' && url.pathname.endsWith('/suggestions')) return json({ matches: {} });
    unexpectedRoutes.push(`${method} ${url.pathname}`);
    return json({ code: 'unexpected_fixture_route' }, 500);
  }));
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  client.clear();
  vi.unstubAllGlobals();
  resetConfigCache();
  expect(unexpectedRoutes, 'every request must match an explicit HTTP fixture').toEqual([]);
});

const mount = () => {
  const onCommit = vi.mocked(commitClusterToRosterEntry);
  return { onCommit, ...render(
    <ClusterLabelingPanel clusterId={CLUSTER_ID} onClose={vi.fn()} onLabel={vi.fn()} />,
    { wrapper: createQueryWrapper(client) },
  ) };
};
const closestKey = queryKeys.clusters.rosterCandidates(CLUSTER_ID, 5);
const settle = async () => {
  await waitFor(() => expect(client.isFetching()).toBe(0));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)); });
};
const beginSave = async () => {
  let rejectWrite: (error: Error) => void = () => { throw new Error('Write not started'); };
  vi.mocked(commitClusterToRosterEntry).mockImplementation(() => new Promise((_resolve, reject) => {
    rejectWrite = reject;
  }));
  const user = userEvent.setup();
  const input = screen.getByRole('combobox', { name: 'Name' });
  await user.type(input, CANONICAL_NAME);
  await user.click(screen.getByRole('button', { name: 'Save name' }));
  await waitFor(() => expect(commitClusterToRosterEntry).toHaveBeenCalledTimes(1));
  expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
  return { user, input, rejectWrite };
};

describe('ClusterLabelingPanel busy candidate recovery', () => {
  it('keeps a failed-read warning during Saving, disables Retry, pauses automatic reads and resumes recovery', async () => {
    candidateStatus = 503;
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load name suggestions.');
    await settle();
    const before = candidateRequests().length;
    const { user, input, rejectWrite } = await beginSave();

    const warning = screen.getByText('Could not load name suggestions.').closest('[role="alert"]');
    expect(warning).toBeVisible();
    const retry = screen.getByRole('button', { name: 'Retry' });
    expect(retry).toBeDisabled();
    expect(input).toBeEnabled();
    await user.clear(input);
    await user.type(input, 'Zoe');
    expect(input).toHaveValue('Zoe');
    await user.click(retry);
    await act(async () => { await client.invalidateQueries({ queryKey: closestKey }); });
    act(() => { window.dispatchEvent(new Event('focus')); });
    await settle();
    expect(candidateRequests()).toHaveLength(before);
    expect(commitClusterToRosterEntry).toHaveBeenCalledTimes(1);
    expect(updateClusterLabel).not.toHaveBeenCalled();
    expect(writeRequests()).toHaveLength(0);

    await act(async () => {
      rejectWrite(new Error('Write rejected by fixture'));
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled());
    await settle();
    candidateStatus = 200;
    const beforeRetry = candidateRequests().length;
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(candidateRequests()).toHaveLength(beforeRetry + 1));
    await waitFor(() => expect(screen.queryByText('Could not load name suggestions.')).not.toBeInTheDocument());
    expect(input).toHaveValue('Zoe');
    expect(commitClusterToRosterEntry).toHaveBeenCalledTimes(1);
    expect(updateClusterLabel).not.toHaveBeenCalled();
    expect(writeRequests()).toHaveLength(0);
  });

  it('retains eligible cached choices and errors while reads are paused, without automatic or manual GETs', async () => {
    const { result, rerender } = renderHook(({ paused }) => useClusterRosterCandidates({
      clusterId: CLUSTER_ID, enabled: true, rosterEntries: [person], ...{ paused },
    }), { initialProps: { paused: false }, wrapper: createQueryWrapper(client) });
    await waitFor(() => expect(result.current.options).toHaveLength(1));
    candidateStatus = 503;
    await act(async () => { await client.invalidateQueries({ queryKey: closestKey }); });
    await waitFor(() => expect(result.current.isError).toBe(true));
    rerender({ paused: true });
    expect(result.current.options[0]).toMatchObject({ band: 'none', roster_entry_id: PERSON_ID });
    expect(result.current.isError).toBe(true);
    const before = candidateRequests().length;
    await act(async () => { await client.invalidateQueries({ queryKey: closestKey }); });
    act(() => { result.current.retry(); });
    await settle();
    expect(candidateRequests()).toHaveLength(before);
    expect(writeRequests()).toHaveLength(0);
    expect(commitClusterToRosterEntry).not.toHaveBeenCalled();
    expect(updateClusterLabel).not.toHaveBeenCalled();
  });

  it('masks cached ranked choices and errors when semantic eligibility is disabled, with no GET or Retry read', async () => {
    const { result, rerender } = renderHook(({ enabled }) => useClusterRosterCandidates({
      clusterId: CLUSTER_ID, enabled, rosterEntries: [person],
    }), { initialProps: { enabled: true }, wrapper: createQueryWrapper(client) });
    await waitFor(() => expect(result.current.options).toHaveLength(1));
    candidateStatus = 503;
    await act(async () => { await client.invalidateQueries({ queryKey: closestKey }); });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.options[0]).toMatchObject({ band: 'none', roster_entry_id: PERSON_ID });
    rerender({ enabled: false });
    expect(result.current.options).toEqual([]);
    expect(result.current.isError).toBe(false);
    const before = candidateRequests().length;
    act(() => { result.current.retry(); });
    await act(async () => { await client.invalidateQueries({ queryKey: closestKey }); });
    await settle();
    expect(candidateRequests()).toHaveLength(before);
    expect(writeRequests()).toHaveLength(0);
    expect(commitClusterToRosterEntry).not.toHaveBeenCalled();
    expect(updateClusterLabel).not.toHaveBeenCalled();
  });
});
