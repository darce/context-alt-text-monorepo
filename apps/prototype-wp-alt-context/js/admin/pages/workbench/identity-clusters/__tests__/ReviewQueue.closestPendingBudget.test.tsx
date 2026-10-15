import React from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import type { RosterCandidatesResponse } from '../../../../api/recognition/rosterCandidatesApi';
import type { RosterEntry } from '../../../../api/rosterApi';
import { buildTestQueryClient } from '../../../../test-utils/queryClient';
import { MergeSurvivorProvider } from '../MergeSurvivorContext';
import { ReviewQueue } from '../ReviewQueue';

// Canon v0.26.2 TEST-15 / HAI-15: exercise the real queue and naming controls;
// ordinary roster lookup remains available independently of ranked hypotheses.

const CLUSTER_ID = 'cluster-review-probe';
const API = '/wp-json/acx/v1';
type CardKind = 'name' | 'assignment' | 'cluster';
const pendingKinds = ['name', 'assignment'] as const;
const bands = [
  ['strong', 'Strong match', 0.8],
  ['possible', 'Possible match', 0.45],
  ['none', 'Below match threshold', 0.12],
] as const;
const roster: RosterEntry[] = ['Ellyn Heald', 'Zoe Adams', 'Pat Nguyen'].map((name, index) => ({
  id: index + 7, name, person_uuid: `fixture-person-${index + 7}`, tags: [],
  cluster_count: 1, clusters: [], queue_memberships: [],
  updated_at: '2026-10-15T00:00:00Z', source_version: 1,
  projection_status: 'current', projection_refreshed_at: null,
}));
const nameProposal = {
  id: 'persisted-name-proposal', cluster_id: CLUSTER_ID, suggested_name: 'Morgan',
  confidence_score: 0.91, source: 'fixture', created_at: '2026-10-15T00:00:00Z',
  expires_at: null,
};
const assignmentProposal = {
  id: 'persisted-assignment-proposal', identity_id: 'identity-review-probe',
  suggested_cluster_id: CLUSTER_ID, representative_similarity: 0.9,
  avg_member_similarity: 0.85, cluster_label: 'Morgan', cluster_identity_count: 1,
  status: 'pending',
};
const unnamedCluster = {
  id: CLUSTER_ID, tenant_id: 'fixture-tenant', label: null, is_labeled: false,
  is_auto_label: true, identity_count: 1, user_confirmed: false,
  suggested_label: null, suggested_target_cluster_id: null,
  representatives: [{ id: 'representative-probe', media_id: 1, is_pinned: false }],
};
const candidateBody = (band: RosterCandidatesResponse['candidates'][number]['band'] = 'none', similarity = 0.12): RosterCandidatesResponse => ({
  model_id: 'fixture-model', embedding_model: 'fixture-model',
  computed_at: '2026-10-15T00:00:00Z', probe_face_count: 1, reference_face_count: 3,
  quality_flag: 'ok',
  thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
  candidates: [{ cluster_id: 'cluster-ellyn', name: 'Ellyn Heald', similarity, band, roster_entry_id: 7 }],
});
const envelope = (suggestions: unknown[]) => ({
  suggestions, limit: 25, offset: 0, data_source: 'local_projection',
});
const json = (body: unknown, status = 200): Promise<Response> => Promise.resolve(new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
}));

let client: ReturnType<typeof buildTestQueryClient>;
let cardKind: CardKind;
let closestBody: RosterCandidatesResponse;
let requests: { url: URL; method: string }[];
let unexpectedRoutes: string[];
const closestRequests = () => requests.filter(({ url }) => url.pathname.endsWith('/roster-candidates'));
const writes = () => requests.filter(({ method }) => method !== 'GET');

beforeEach(() => {
  cardKind = 'name';
  closestBody = candidateBody();
  requests = [];
  unexpectedRoutes = [];
  client = buildTestQueryClient();
  registerConfig({
    nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php', tenant_id: 'fixture-tenant',
    endpoints: {
      rosterEntries: `${API}/roster/entries`,
      recognitionClusters: `${API}/recognition/clusters`,
      recognitionSuggestions: `${API}/recognition/suggestions`,
      recognitionMergeSuggestions: `${API}/recognition/suggestions/merge`,
      recognitionNameSuggestions: `${API}/recognition/suggestions/name`,
      recognitionMediaIdentities: `${API}/recognition/media-identities`,
    },
  });
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    requests.push({ url, method });
    if (method === 'GET') {
      switch (url.pathname) {
        case `${API}/roster/entries`: return json(roster);
        case `${API}/recognition/suggestions`: return json(envelope(cardKind === 'assignment' ? [assignmentProposal] : []));
        case `${API}/recognition/suggestions/name`: return json(envelope(cardKind === 'name' ? [nameProposal] : []));
        case `${API}/recognition/suggestions/merge`: return json(envelope([]));
        case `${API}/recognition/clusters/top-unlabeled`: return json({
          clusters: cardKind === 'cluster' ? [unnamedCluster] : [], limit: 20,
          total: cardKind === 'cluster' ? 1 : 0, truncated: false, singleton_count: 0,
          has_clusters: cardKind === 'cluster', data_source: 'local_projection',
        });
        case `${API}/recognition/clusters/${CLUSTER_ID}/members`: return json({
          members: [], limit: 25, total: 0, truncated: false,
        });
        case `${API}/recognition/clusters/${CLUSTER_ID}/roster-candidates`: return json(closestBody);
        case `${API}/recognition/media-identities`: return json({ identities_by_media: {}, data_source: 'local_projection' });
      }
    }
    unexpectedRoutes.push(`${method} ${url.pathname}`);
    return json({ code: 'unexpected_fixture_route' }, 500);
  }));
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  const queryErrors = client.getQueryCache().getAll().filter((query) => query.state.status === 'error');
  client.clear();
  resetConfigCache();
  vi.unstubAllGlobals();
  expect(unexpectedRoutes, 'fixture routing errors are separate from causal regression assertions').toEqual([]);
  expect(queryErrors.map((query) => query.queryKey), 'every real API fixture must load successfully').toEqual([]);
  expect(writes(), 'display, typing and reveal never assign or send learning feedback').toHaveLength(0);
});

const QueueHarness = () => {
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  return <ReviewQueue index={0} kind="all" band="all" selectedIds={selectedIds}
    onSelectedIdsChange={setSelectedIds} onClampIndex={vi.fn()} onStepIndex={vi.fn()}
    onKindChange={vi.fn()} onBandChange={vi.fn()} onClearFilters={vi.fn()} />;
};
const mount = () => render(
  <QueryClientProvider client={client}>
    <MergeSurvivorProvider><QueueHarness /></MergeSurvivorProvider>
  </QueryClientProvider>,
);
const openNaming = async () => {
  const input = await screen.findByRole('combobox', { name: 'Name this person' });
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.focus(input);
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  await waitFor(() => expect(client.isFetching()).toBe(0));
  return input;
};
const settle = async () => {
  await waitFor(() => expect(client.isFetching()).toBe(0));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)); });
};
const assertPendingCard = (kind: typeof pendingKinds[number]) => {
  expect(screen.getByTestId('acx-review-card')).toHaveAttribute('data-review-kind', kind);
  if (kind === 'name') {
    expect(screen.getByRole('button', { name: 'Show suggestion' })).toBeDisabled();
    expect(screen.queryByText(/Suggested name:/)).not.toBeInTheDocument();
  }
};
const warmFromUnnamedQueue = async (kind: typeof pendingKinds[number]) => {
  cardKind = 'cluster';
  const view = mount();
  await openNaming();
  expect(await screen.findByRole('option', { name: /Confirm match with Ellyn Heald/ })).toHaveTextContent(/match/i);
  expect(closestRequests()).toHaveLength(1);
  expect(client.getQueryData(queryKeys.clusters.rosterCandidates(CLUSTER_ID, 5))).toEqual(closestBody);
  view.unmount();
  client.removeQueries({ queryKey: queryKeys.suggestions.all });
  client.removeQueries({ queryKey: queryKeys.clusters.topUnlabeled('fixture-tenant') });
  cardKind = kind;
  requests = [];
};

describe('ReviewQueue persisted proposal closest-candidate budget (c82 F2)', () => {
  it.each(pendingKinds)('F2-budget-%s: eligible persisted proposal spends zero fallback GETs', async (kind) => {
    cardKind = kind;
    mount();
    await openNaming();
    await settle();
    assertPendingCard(kind);
    expect(closestRequests(), 'the existing pending proposal is authoritative; no second fallback read').toHaveLength(0);
  });

  describe.each(pendingKinds)('F2-cache-%s', (kind) => {
    it.each(bands)('hides cached %s ranked alternatives before judgment/reveal', async (band, label, similarity) => {
      closestBody = candidateBody(band, similarity);
      await warmFromUnnamedQueue(kind);
      mount();
      await openNaming();
      assertPendingCard(kind);
      expect(closestRequests()).toHaveLength(0);
      expect(screen.queryByText(label), 'a cache warmed by another unnamed view must not leak ranked evidence').not.toBeInTheDocument();
      expect(screen.queryByText(/^(?:(Strong|Possible|Weak) match|Below match threshold)$/)).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /No close match: name as new person/ })).not.toBeInTheDocument();
    });
  });

  it.each(pendingKinds)('F2-manual-%s: ordinary roster lookup and naming correction remain available', async (kind) => {
    cardKind = kind;
    mount();
    const input = await openNaming();
    await userEvent.setup().type(input, 'Zoe');
    expect(input).toHaveValue('Zoe');
    expect(screen.getByRole('option', { name: /Confirm match with Zoe Adams/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Pat Nguyen/ })).not.toBeInTheDocument();
    assertPendingCard(kind);
  });

  it('F2-reveal-control: NAME judgment still precedes explicit persisted suggestion reveal', async () => {
    mount();
    await openNaming();
    const reveal = screen.getByRole('button', { name: 'Show suggestion' });
    expect(reveal).toBeDisabled();
    const user = userEvent.setup();
    await user.type(screen.getByRole('textbox', { name: 'Independent name judgment' }), 'Zoe');
    await user.click(screen.getByRole('button', { name: 'Record judgment' }));
    expect(screen.queryByText(/Suggested name:/)).not.toBeInTheDocument();
    await user.click(reveal);
    expect(screen.getByText(/Suggested name:/)).toHaveTextContent('Morgan');
    expect(screen.getByRole('button', { name: 'Accept suggestion' })).toBeEnabled();
  });

  it('F2-healthy: unnamed CLUSTER without pending proposal reads top 5 and keeps weak choices while typing Zoe', async () => {
    cardKind = 'cluster';
    mount();
    const input = await openNaming();
    const option = await screen.findByRole('option', { name: /Confirm match with Ellyn Heald/ });
    expect(option).toHaveTextContent('Below match threshold');
    expect(closestRequests()).toHaveLength(1);
    expect(closestRequests()[0]?.url.searchParams.get('top_k')).toBe('5');
    expect(closestRequests()[0]?.method).toBe('GET');
    await userEvent.setup().type(input, 'Zoe');
    expect(input).toHaveValue('Zoe');
    expect(option).toHaveTextContent('Below match threshold');
    expect(screen.getByRole('option', { name: /Confirm match with Zoe Adams/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Pat Nguyen/ })).not.toBeInTheDocument();
    expect(closestRequests()).toHaveLength(1);
  });
});
