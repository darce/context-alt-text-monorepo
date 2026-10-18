import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import { fetchClusterRosterCandidates } from '../../../../api/recognition/rosterCandidatesApi';
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
  expect(unexpectedRoutes, 'every request must match an explicit HTTP fixture').toEqual([]);
});

const mount = () => {
  const onCommit = vi.mocked(commitClusterToRosterEntry);
  return { onCommit, ...render(
    <ClusterLabelingPanel clusterId={CLUSTER_ID} onClose={vi.fn()} onLabel={vi.fn()} />,
    { wrapper: createQueryWrapper(client) },
  ) };
};
const Collapsed = ({ visible, onCommit }: { visible: boolean; onCommit: () => void }) => visible ? (
  <ClusterLabelingPanel clusterId={CLUSTER_ID} onClose={vi.fn()} onLabel={onCommit} />
) : null;
const openNaming = async () => {
  const input = screen.getByRole('combobox', { name: 'Name' });
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.focus(input);
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  return input;
};

// These are consumer regressions: real NameFaceControl, real React Query and real
// candidate adapter. No future hook import or mocked candidate read can cause RED.
describe('ClusterLabelingPanel closest roster candidates (c82 F1)', () => {
  it('F1 fixture control: the configured real adapter reads top 5 and rejects the scripted 503', async () => {
    await expect(fetchClusterRosterCandidates(CLUSTER_ID)).resolves.toEqual(candidateBody);
    candidateStatus = 503;
    await expect(fetchClusterRosterCandidates(CLUSTER_ID)).rejects.toMatchObject({ status: 503 });
    expect(candidateRequests()).toHaveLength(2);
    expect(candidateRequests().every(({ method, url }) => method === 'GET' && url.searchParams.get('top_k') === '5')).toBe(true);
  });

  it('F1 display control: rendering and opening the real naming list never assigns or creates a person', async () => {
    const { onCommit } = mount();
    await openNaming();
    expect(await screen.findByRole('option', { name: /Confirm match with Ellyn Heald/ })).toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
    expect(updateClusterLabel).not.toHaveBeenCalled();
    expect(writeRequests()).toHaveLength(0);
  });

  it('F1 unmount control: invalidation after closing an opened control does not fetch candidates', async () => {
    const view = mount();
    await openNaming();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)); });
    view.unmount();
    const before = candidateRequests().length;
    await act(async () => { await client.invalidateQueries(); });
    expect(candidateRequests()).toHaveLength(before);
    expect(writeRequests()).toHaveLength(0);
  });

  it('F1 requests exactly one top-5 candidate GET for the visible editable unnamed cluster', async () => {
    mount();
    await openNaming();
    await waitFor(() => expect(candidateRequests()).toHaveLength(1));
    expect(candidateRequests()[0]?.url.pathname).toBe(`/wp-json/acx/v1/recognition/clusters/${CLUSTER_ID}/roster-candidates`);
    expect(candidateRequests()[0]?.url.searchParams.get('top_k')).toBe('5');
    expect(candidateRequests()[0]?.method).toBe('GET');
    expect(writeRequests()).toHaveLength(0);
    expect(commitClusterToRosterEntry).not.toHaveBeenCalled();
    expect(updateClusterLabel).not.toHaveBeenCalled();
  });

  it('F1 shows the weak candidate under its canonical cached person name and selecting binds the existing ID', async () => {
    const { onCommit } = mount();
    await openNaming();
    const option = await screen.findByRole('option', { name: /Confirm match with Ellyn Heald/ });
    await waitFor(() => expect(option).toHaveTextContent(/Below match threshold/i));
    expect(option).not.toHaveTextContent(/Gilded Cypress|medium|strong match|12%/i);
    expect(screen.queryByRole('option', { name: /Gilded Cypress/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /no close match|name as new person/i })).toBeInTheDocument();
    expect(writeRequests()).toHaveLength(0);
    expect(onCommit).not.toHaveBeenCalled();
    expect(updateClusterLabel).not.toHaveBeenCalled();
    await userEvent.setup().click(option);
    await waitFor(() => expect(onCommit).toHaveBeenCalledExactlyOnceWith(
      { clusterId: CLUSTER_ID, rosterEntryId: PERSON_ID }, expect.any(AbortSignal),
    ));
    expect(updateClusterLabel).not.toHaveBeenCalled();
  });

  it('F1 keeps closest weak alternatives and abstention visible while entering a different manual name', async () => {
    mount();
    const input = await openNaming();
    await waitFor(() => expect(candidateRequests()).toHaveLength(1));
    await userEvent.setup().type(input, 'Zoe');
    expect(await screen.findByRole('option', { name: /Confirm match with Ellyn Heald/ })).toHaveTextContent(/Below match threshold/i);
    expect(screen.getByRole('button', { name: /no close match|name as new person/i })).toBeInTheDocument();
    expect(input).toHaveValue('Zoe');
    expect(writeRequests()).toHaveLength(0);
  });

  it('F1 exposes a candidate 503 as an alert, permits manual input, and Retry performs a real GET', async () => {
    candidateStatus = 503;
    const { onCommit } = mount();
    const input = await openNaming();
    await waitFor(() => expect(candidateRequests()).toHaveLength(1));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not load|unable to load|failed/i);
    expect(screen.queryByText(/no (close )?matches found|no suggestions available/i)).not.toBeInTheDocument();
    expect(input).toBeEnabled();
    await userEvent.setup().type(input, 'Zoe');
    expect(input).toHaveValue('Zoe');
    expect(onCommit).not.toHaveBeenCalled();
    expect(updateClusterLabel).not.toHaveBeenCalled();
    candidateStatus = 200;
    await userEvent.setup().click(within(alert).getByRole('button', { name: /retry/i }));
    await waitFor(() => expect(candidateRequests()).toHaveLength(2));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(await screen.findByRole('option', { name: /Confirm match with Ellyn Heald/ })).toHaveTextContent(/Below match threshold/i);
    expect(input).toHaveValue('Zoe');
    expect(writeRequests()).toHaveLength(0);
  });

  it('F1 lazy control: collapsed and unmounted naming performs no candidate GET', async () => {
    const onCommit = vi.fn();
    const view = render(<Collapsed visible={false} onCommit={onCommit} />, { wrapper: createQueryWrapper(client) });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)); });
    expect(candidateRequests()).toHaveLength(0);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    view.unmount();
    await act(async () => { await client.invalidateQueries(); });
    expect(candidateRequests()).toHaveLength(0);
    expect(onCommit).not.toHaveBeenCalled();
  });

});
