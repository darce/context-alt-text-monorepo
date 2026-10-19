import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ComboboxOption } from '../../../../../components/ui/combobox';
import { registerConfig, resetConfigCache } from '../../../../api/config';
import type { RosterEntry } from '../../../../api/rosterApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { buildNamingOptions } from '../buildNamingOptions';
import { ClusterEditForm } from '../ClusterEditForm';
import { NameFaceControl } from '../NameFaceControl';
import { selectClusterSuggestions, useClusterSuggestions } from '../useClusterSuggestions';

const group = { clusterId: 'cluster-for-42', label: 'Alex Rivera', similarity: 0.8,
  identityCount: 2, suggestionId: 'suggestion-for-42', identityId: 'source-face' };
const preceding = Array.from({ length: 19 }, (_, i) => ({ id: 100 + i, name: `Other ${i}` }));
const namesakes = [{ id: 41, name: 'Alex Rivera' }, { id: 42, name: 'Alex Rivera' }];
const open = () => fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' });
afterEach(cleanup);

describe('canonical person proof through the real producer', () => {
  it.each([false, true])('preserves the original group action without proof (cap20=%s)', (atCap) => {
    const built = buildNamingOptions({ rosterEntries: [...(atCap ? preceding : []), ...namesakes],
      labelMatches: [], filter: '', excludeClusterId: 'edited-cluster' });
    const options = selectClusterSuggestions({ identityProjection: [group], namingOptions: built.options,
      editableClusterId: 'edited-cluster', labelInput: '' });
    if (atCap) {
      expect(built.options).toHaveLength(20);
      expect(built.options.at(-1)?.value).toBe('person:41');
      expect(built.options.some(option => option.value === 'person:42')).toBe(false);
    } else {
      // Original name-dedup counterexample: both distinct IDs must survive the builder.
      expect(built.options.map(option => option.value)).toEqual(['person:41', 'person:42']);
    }
    expect(built.collisionsByLabel.get('alex rivera')?.map(option => option.value)).toEqual(['person:41', 'person:42']);
    const onCommit = vi.fn();
    const onOptionConfirm = vi.fn();
    render(<NameFaceControl options={options} value="" onValueChange={vi.fn()} onCommit={onCommit}
      onOptionConfirm={onOptionConfirm} commitLabel="Save name" />);
    open();
    fireEvent.click(screen.getAllByRole('option')[0]);
    expect(onCommit).not.toHaveBeenCalled();
    expect(onOptionConfirm).toHaveBeenCalledExactlyOnceWith(options[0]);
  });

  it('keeps the actual form from dispatching person 41 at the exact 20-option boundary', () => {
    const built = buildNamingOptions({ rosterEntries: [...preceding, ...namesakes], labelMatches: [] });
    const options = selectClusterSuggestions({ identityProjection: [group], namingOptions: built.options });
    const onPersonSelect = vi.fn();
    const onLabelChange = vi.fn();
    render(<ClusterEditForm labelInput="" onLabelChange={onLabelChange} options={options}
      isLoading={false} isPending={false} onSave={vi.fn()} onPersonSelect={onPersonSelect}
      onConfirmSuggestion={vi.fn()} onCancel={vi.fn()} />);
    open();
    fireEvent.click(screen.getAllByRole('option')[0]);
    expect(onPersonSelect).not.toHaveBeenCalled();
    expect(onLabelChange).toHaveBeenCalledExactlyOnceWith('Alex Rivera');
  });

  it('retains same-label groups with different IDs unless a binding proves equivalence', () => {
    const built = buildNamingOptions({ rosterEntries: [namesakes[0]], labelMatches: [
      { id: 'first', label: 'Alex Rivera' }, { id: 'second', label: 'Alex Rivera' },
    ] });
    const options = selectClusterSuggestions({ identityProjection: [group], namingOptions: built.options });
    expect(options.map(option => option.value)).toEqual([
      'cluster:cluster-for-42', 'person:41', 'cluster:first', 'cluster:second',
    ]);
  });
});

// HTTP fixtures exercise roster/cluster codecs, the actual loader's default cap,
// projection, selector, and the unchanged form. No complete option list is injected.
describe('existing canonical binding reads', () => {
  let client: ReturnType<typeof buildTestQueryClient>;
  let requests: string[];
  let roster: RosterEntry[];
  let clusters: object[];
  const person = (id: number, name: string): RosterEntry => ({ id, name, person_uuid: `backend-person-${id}`,
    tags: [], cluster_count: 0, clusters: [], queue_memberships: [], updated_at: '', source_version: 1,
    projection_status: 'current', projection_refreshed_at: null });
  const summary = (personUuid?: string | null) => ({ id: group.clusterId, label: group.label,
    person_uuid: personUuid, identity_count: 2, member_ids: [], sample_identities: [],
    representative_identity: { media_id: null, bbox: { x: 0, y: 0, width: 0, height: 0 } } });
  beforeEach(() => {
    client = buildTestQueryClient();
    requests = [];
    roster = [...preceding, ...namesakes].map(entry => person(entry.id, entry.name));
    clusters = [summary('backend-person-42')];
    registerConfig({ nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php', endpoints: {
      rosterEntries: '/wp-json/acx/v1/roster/entries', recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
      recognitionIdentitySuggestions: '/wp-json/acx/v1/recognition/identities',
    } });
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, window.location.origin);
      requests.push(`${init?.method ?? 'GET'} ${url.pathname}`);
      let payload: unknown;
      switch (url.pathname) {
        case '/wp-json/acx/v1/roster/entries': payload = roster; break;
        case '/wp-json/acx/v1/recognition/identities/suggestions': payload = { matches: { 'source-face': [{
          cluster_id: group.clusterId, label: group.label, similarity: group.similarity,
          identity_count: 2, suggestion_id: group.suggestionId,
        }] } }; break;
        case '/wp-json/acx/v1/recognition/clusters':
          payload = { clusters, limit: 50, total: 200, truncated: true }; break;
        default: throw new Error(`Unexpected fixture request: ${url.pathname}`);
      }
      return Promise.resolve(new Response(JSON.stringify(payload), { status: 200,
        headers: { 'Content-Type': 'application/json' } }));
    }));
  });
  afterEach(async () => {
    cleanup();
    await client.cancelQueries();
    expect(requests).toHaveLength(3);
    expect(requests.every(request => request.startsWith('GET '))).toBe(true);
    expect(client.getMutationCache().getAll()).toHaveLength(0);
    client.clear();
    resetConfigCache();
    vi.unstubAllGlobals();
  });
  const mount = async (labelInput = '') => {
    const onPersonSelect = vi.fn();
    const onLabelChange = vi.fn();
    let latestOptions: ComboboxOption[] = [];
    const Harness = () => {
      const suggestions = useClusterSuggestions({ identityId: 'source-face', editableClusterId: 'edited-cluster',
        enabled: true, debounceMs: 0, labelInput });
      latestOptions = suggestions.options;
      return <ClusterEditForm labelInput={labelInput} onLabelChange={onLabelChange} options={suggestions.options}
        isLoading={suggestions.isLoading} isPending={false} onSave={vi.fn()} onPersonSelect={onPersonSelect}
        onConfirmSuggestion={vi.fn()} onCancel={vi.fn()} />;
    };
    render(<Harness />, { wrapper: createQueryWrapper(client) });
    await waitFor(() => expect(requests).toHaveLength(3));
    await waitFor(() => expect(client.isFetching()).toBe(0));
    open();
    return { onPersonSelect, onLabelChange, getOptions: () => latestOptions };
  };
  it('binds 42 by UUID mapping beyond the cap, preserving namesake 41 as a separate choice', async () => {
    expect(buildNamingOptions({ rosterEntries: roster, labelMatches: [] }).options.some(option => option.value === 'person:42')).toBe(false);
    const { onPersonSelect, onLabelChange, getOptions } = await mount();
    expect(getOptions()[0]).toEqual({ value: 'person:42', label: 'Alex Rivera', source: 'person', group: 'Suggested' });
    const rows = screen.getAllByRole('option');
    expect(rows).toHaveLength(5);
    expect(rows[0]).toHaveAccessibleName('Confirm match with Alex Rivera');
    // A manual roster choice never inherits the group's confidence or reject action.
    expect(rows[0]).not.toHaveTextContent('%');
    expect(screen.queryByRole('button', { name: /Reject/ })).not.toBeInTheDocument();
    fireEvent.click(rows[0]);
    expect(onPersonSelect).toHaveBeenCalledExactlyOnceWith('Alex Rivera', 42);
    expect(onLabelChange).not.toHaveBeenCalled();
  });
  it.each(['Alex Rivera', 'Alex Canonical'])('collapses one proved person/group into one choice named %s', async (name) => {
    roster = [person(42, name)];
    const { onPersonSelect } = await mount();
    const rows = screen.getAllByRole('option');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAccessibleName(`Confirm match with ${name}`);
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter' });
    expect(onPersonSelect).toHaveBeenCalledExactlyOnceWith(name, 42);
  });
  it('resolves proof before filtering by the canonical name rather than the stale group label', async () => {
    roster = [person(42, 'Alex Canonical')];
    const { onPersonSelect } = await mount('Canonical');
    expect(screen.getAllByRole('option')).toHaveLength(1);
    fireEvent.click(screen.getAllByRole('option')[0]);
    expect(onPersonSelect).toHaveBeenCalledExactlyOnceWith('Alex Canonical', 42);
  });
  it('never treats the roster projection’s same-name cluster aggregate as binding proof', async () => {
    clusters = [];
    // The real roster projection groups namesakes and unions their clusters under
    // the first entry. This list can include a cluster bound to a different ID.
    roster = [person(41, 'Alex Rivera')];
    roster[0].clusters = [{ cluster_id: group.clusterId, identity_count: 2, representative_identity: null, instances: [] }];
    const { onPersonSelect, onLabelChange } = await mount();
    fireEvent.click(screen.getAllByRole('option')[0]);
    expect(onPersonSelect).not.toHaveBeenCalled();
    expect(onLabelChange).toHaveBeenCalledExactlyOnceWith('Alex Rivera');
  });
  it.each(['unmapped UUID', 'absent UUID', 'numeric-looking UUID'])('fails closed for %s on a partial roster page', async (kind) => {
    roster = [person(41, 'Alex Rivera')];
    clusters = [summary(kind === 'unmapped UUID' ? 'backend-person-42' : kind === 'numeric-looking UUID' ? '41' : undefined)];
    const { onPersonSelect, onLabelChange } = await mount();
    expect(screen.getAllByRole('option')).toHaveLength(2);
    fireEvent.click(screen.getAllByRole('option')[0]);
    expect(onPersonSelect).not.toHaveBeenCalled();
    expect(onLabelChange).toHaveBeenCalledExactlyOnceWith('Alex Rivera');
  });
  it('keeps distinct proved same-name IDs as two explicit manual choices', async () => {
    roster = [person(41, 'Alex Rivera'), person(42, 'Alex Rivera')];
    const { onPersonSelect } = await mount();
    const rows = screen.getAllByRole('option');
    expect(rows).toHaveLength(2);
    fireEvent.click(rows[0]);
    expect(onPersonSelect).toHaveBeenCalledExactlyOnceWith('Alex Rivera', 42);
  });
});
