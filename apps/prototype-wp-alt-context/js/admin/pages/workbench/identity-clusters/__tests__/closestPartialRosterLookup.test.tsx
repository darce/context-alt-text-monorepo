import React from 'react';
import { cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import type { RosterCandidatesResponse } from '../../../../api/recognition/rosterCandidatesApi';
import type { RosterEntry } from '../../../../api/rosterApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { buildNamingOptions, namingOptionValue } from '../buildNamingOptions';
import { NameFaceControl, type NameFaceResolution } from '../NameFaceControl';
import { mergeRosterCandidateOptions, useClusterRosterCandidates } from '../useClusterRosterCandidates';
import { useClusterSuggestions } from '../useClusterSuggestions';

const CLUSTER_ID = 'cluster-probe';
const IDENTITY_ID = 'identity-probe';
// Deliberately not alphabetic or similarity order: preserve the server's order.
const names = ['Cara Cole', 'Amy Ames', 'Ben Bell', 'Dan Dale', 'Eli Evans', 'Zoe Zane'];
const roster: RosterEntry[] = names.map((name, index) => ({
  id: index + 11, name, person_uuid: `person-${index + 11}`, tags: [],
  cluster_count: 1, clusters: [], queue_memberships: [],
  updated_at: '2026-10-15T00:00:00Z', source_version: 1,
  projection_status: 'current', projection_refreshed_at: null,
}));
const body: RosterCandidatesResponse = {
  model_id: 'fixture-model', embedding_model: 'fixture-model',
  computed_at: '2026-10-15T00:00:00Z', probe_face_count: 1, reference_face_count: 5,
  quality_flag: 'ok',
  thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
  candidates: roster.slice(0, 5).map((person, index) => ({
    cluster_id: `cluster-person-${person.id}`, roster_entry_id: person.id,
    name: `Stale snapshot ${person.id}`, similarity: (index + 1) / 10,
    band: index === 0 ? 'strong' : index === 1 ? 'possible' : 'none',
  })),
};
type Path = 'candidate merge' | 'legacy selector';
let client: ReturnType<typeof buildTestQueryClient>;
let requests: { method: string; url: URL }[];
let unexpected: string[];
const json = (payload: unknown) => Promise.resolve(new Response(JSON.stringify(payload), {
  status: 200, headers: { 'Content-Type': 'application/json' },
}));

beforeEach(() => {
  client = buildTestQueryClient();
  requests = [];
  unexpected = [];
  registerConfig({ nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php', endpoints: {
    rosterEntries: '/wp-json/acx/v1/roster/entries',
    recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
    recognitionIdentitySuggestions: '/wp-json/acx/v1/recognition/identities',
  } });
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const method = init?.method ?? 'GET';
    requests.push({ method, url });
    if (method === 'GET') {
      switch (url.pathname) {
        case `/wp-json/acx/v1/recognition/clusters/${CLUSTER_ID}/roster-candidates`: return json(body);
        case '/wp-json/acx/v1/roster/entries': return json(roster);
        case '/wp-json/acx/v1/recognition/identities/suggestions': return json({ matches: { [IDENTITY_ID]: [] } });
        case '/wp-json/acx/v1/recognition/clusters': return json({ clusters: [], limit: 50, total: 0, truncated: false });
      }
    }
    unexpected.push(`${method} ${url.pathname}`);
    return Promise.reject(new Error('Unexpected fixture request'));
  }));
});

afterEach(async () => {
  cleanup();
  await client.cancelQueries();
  expect(unexpected, 'fixture failures are distinct from behavior failures').toEqual([]);
  expect(client.getQueryCache().getAll().filter((query) => query.state.status === 'error')).toHaveLength(0);
  expect(requests.every(({ method }) => method === 'GET')).toBe(true);
  expect(client.getMutationCache().getAll()).toHaveLength(0);
  client.clear();
  resetConfigCache();
  vi.unstubAllGlobals();
});

const Control = ({ options, value, setValue, onCommit }: {
  options: React.ComponentProps<typeof NameFaceControl>['options'];
  value: string; setValue: (value: string) => void;
  onCommit: (resolution: NameFaceResolution) => void;
}) => <NameFaceControl options={options} value={value} onValueChange={setValue}
  onCommit={onCommit} ariaLabel="Name" commitLabel="Save name" previewCommit />;

const CandidateHarness = ({ onCommit }: { onCommit: (resolution: NameFaceResolution) => void }) => {
  const [value, setValue] = React.useState('');
  const closest = useClusterRosterCandidates({ clusterId: CLUSTER_ID, enabled: true, rosterEntries: roster });
  const ordinary = buildNamingOptions({ rosterEntries: roster, labelMatches: [], filter: value, limit: null }).options;
  return <Control options={mergeRosterCandidateOptions(closest.options, ordinary.map((option) => ({ ...option })))}
    value={value} setValue={setValue} onCommit={onCommit} />;
};
const LegacyHarness = ({ onCommit }: { onCommit: (resolution: NameFaceResolution) => void }) => {
  const [value, setValue] = React.useState('');
  const suggestions = useClusterSuggestions({ identityId: IDENTITY_ID, editableClusterId: CLUSTER_ID,
    enabled: true, labelInput: value, debounceMs: 0 });
  return <Control options={suggestions.options} value={value} setValue={setValue} onCommit={onCommit} />;
};
const mount = async (path: Path) => {
  const onCommit = vi.fn<(resolution: NameFaceResolution) => void>();
  const Harness = path === 'candidate merge' ? CandidateHarness : LegacyHarness;
  render(<Harness onCommit={onCommit} />, { wrapper: createQueryWrapper(client) });
  await waitFor(() => expect(requests.filter(({ url }) => url.pathname.endsWith('/roster-candidates'))).toHaveLength(1));
  await waitFor(() => expect(client.isFetching()).toBe(0));
  const user = userEvent.setup();
  const input = screen.getByRole('combobox', { name: 'Name' });
  await user.click(input);
  await user.keyboard('{ArrowDown}');
  return { onCommit, user, input };
};
const row = (name: string) => screen.getByRole('option', { name: new RegExp(`Confirm match with ${name}`) });

// Real hooks -> production merge/selector -> real NameFaceControl, with only HTTP fixtures.
describe.each<Path>(['candidate merge', 'legacy selector'])('closest partial lookup via %s', (path) => {
  it.each([[3, 'Dan'], [4, 'Eli']] as const)('finds closest index %i by partial %s and binds its real person ID', async (index, partial) => {
    const { user, input, onCommit } = await mount(path);
    await user.type(input, partial);
    await waitFor(() => expect(row(names[index])).toBeVisible());
    expect(screen.getAllByRole('option', { name: new RegExp(names[index]) })).toHaveLength(1);
    expect(onCommit).not.toHaveBeenCalled();
    await user.click(row(names[index]));
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'roster', rosterEntryId: index + 11, name: names[index] });
  });

  it.each([3, 4])('exact existing closest index %i resolves once without Create person or ambiguity', async (index) => {
    const { user, input, onCommit } = await mount(path);
    await user.type(input, names[index]);
    await waitFor(() => expect(screen.getByRole('button', { name: `Save as ${names[index]}` })).toBeEnabled());
    expect(screen.queryByRole('button', { name: /Create person/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Multiple people match. Choose one.')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: `Save as ${names[index]}` }));
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'roster', rosterEntryId: index + 11, name: names[index] });
  });

  it('keeps the top-three server order and bands while unrelated typing finds the ordinary sixth person', async () => {
    const { user, input, onCommit } = await mount(path);
    const atRestRows = screen.getAllByRole('option');
    expect(atRestRows.length).toBeLessThanOrEqual(5);
    expect(new Set(atRestRows.map((option) => option.getAttribute('aria-label'))).size).toBe(atRestRows.length);
    await user.type(input, 'Zoe');
    await waitFor(() => expect(row(names[5])).toBeVisible());
    expect(screen.getAllByRole('option').map((option) => option.getAttribute('aria-label'))).toEqual(
      [names[0], names[1], names[2], names[5]].map((name) => `Confirm match with ${name}`),
    );
    expect(row(names[0])).toHaveTextContent('Strong match');
    expect(row(names[1])).toHaveTextContent('Possible match');
    expect(row(names[2])).toHaveTextContent('Below match threshold');
    expect(onCommit).not.toHaveBeenCalled();
    await user.click(row(names[5]));
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'roster', rosterEntryId: 16, name: names[5] });
    const closest = requests.filter(({ url }) => url.pathname.endsWith('/roster-candidates'));
    expect(closest).toHaveLength(1);
    expect(closest[0]?.url.searchParams.get('top_k')).toBe('5');
  });
});

it('retains all five fetched closest tuples in server order before overlay budgeting', async () => {
  const { result } = renderHook(() => useClusterRosterCandidates({ clusterId: CLUSTER_ID, enabled: true, rosterEntries: roster }),
    { wrapper: createQueryWrapper(client) });
  await waitFor(() => expect(result.current.options).toHaveLength(5));
  expect(result.current.options).toEqual(body.candidates.map((candidate, index) => ({
    value: namingOptionValue('person', index + 11), label: names[index], source: 'person', group: 'Suggested',
    roster_entry_id: index + 11, cluster_id: candidate.cluster_id, band: candidate.band, similarity: candidate.similarity,
  })));
  expect(result.current.options.every((option) => option.suggestion_id === undefined && option.suggestion_identity_id === undefined)).toBe(true);
});
