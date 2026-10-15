import React from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ComboboxMatchBand, ComboboxOption } from '../../../../../components/ui/combobox';
import { registerConfig, resetConfigCache } from '../../../../api/config';
import type { RosterCandidatesResponse } from '../../../../api/recognition/rosterCandidatesApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { NameFaceControl, type NameFaceResolution } from '../NameFaceControl';
import { NAMING_GROUP_SUGGESTED, namingOptionValue } from '../buildNamingOptions';
import { useClusterRosterCandidates } from '../useClusterRosterCandidates';

const candidate = (id: number, band: ComboboxMatchBand, similarity: number): ComboboxOption => ({
  value: namingOptionValue('person', id),
  label: `Person ${id}`,
  source: 'person',
  group: NAMING_GROUP_SUGGESTED,
  roster_entry_id: id,
  cluster_id: `cluster-${id}`,
  band,
  similarity,
});

const abstainName = 'No close match: name as new person';

const Harness = ({
  options,
  onCommit,
  onReject = vi.fn(),
  initialValue = '',
}: {
  options: readonly ComboboxOption[];
  onCommit: (resolution: NameFaceResolution) => void;
  onReject?: (id: string) => void;
  initialValue?: string;
}) => {
  const [value, setValue] = React.useState(initialValue);
  return (
    <NameFaceControl
      options={options}
      value={value}
      onValueChange={setValue}
      onCommit={onCommit}
      onRejectSuggestion={onReject}
      ariaLabel="Name this person"
      commitLabel="Save name"
    />
  );
};

let queryClient: ReturnType<typeof buildTestQueryClient> | undefined;

afterEach(async () => {
  cleanup();
  await queryClient?.cancelQueries();
  queryClient?.clear();
  queryClient = undefined;
  resetConfigCache();
  vi.unstubAllGlobals();
});

describe('server match bands and explicit abstention', () => {
  it.each([0.17, 0.11, 0.06])('labels band none at %s as below threshold without a probability', async (similarity) => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness options={[candidate(7, 'none', similarity)]} onCommit={onCommit} />);
    await user.keyboard('{ArrowDown}');

    const row = screen.getByRole('option', { name: /Person 7/ });
    expect(within(row).getByText('Below match threshold', { exact: true })).toBeInTheDocument();
    expect(row).not.toHaveTextContent(/Weak match|Strong match|Possible match|%/);
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('preserves strong and possible wording and server order without deriving bands from scores', async () => {
    const user = userEvent.setup();
    render(<Harness options={[candidate(7, 'strong', 0.11), candidate(8, 'possible', 0.9)]} onCommit={vi.fn()} />);
    await user.keyboard('{ArrowDown}');

    const rows = screen.getAllByRole('option');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAccessibleName(/Person 7/);
    expect(rows[0]).toHaveTextContent('Strong match');
    expect(rows[1]).toHaveAccessibleName(/Person 8/);
    expect(rows[1]).toHaveTextContent('Possible match');
    for (const row of rows) {
      expect(row).not.toHaveTextContent(/Below match threshold|Weak match|%/);
    }
  });

  it.each(['strong', 'possible', 'mixed'] as const)('offers manual entry for an all-%s list with no none row', async (bands) => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    const onReject = vi.fn();
    const options = bands === 'mixed'
      ? [candidate(7, 'strong', 0.8), candidate(8, 'possible', 0.5)]
      : [candidate(7, bands, 0.8)];
    render(<Harness options={options} onCommit={onCommit} onReject={onReject} />);
    const input = screen.getByRole('combobox', { name: 'Name this person' });
    await user.keyboard('{ArrowDown}');
    const abstain = screen.getByRole('button', { name: abstainName });
    await user.click(abstain);

    expect(input).toHaveFocus();
    expect(onCommit).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /^Reject/ })).not.toBeInTheDocument();
    await user.type(input, 'Novel Name');
    expect(screen.getAllByRole('option')).toHaveLength(options.length);
    expect(onCommit).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: abstainName }));
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'create', name: 'Novel Name' });
    expect(onReject).not.toHaveBeenCalled();
  });

  it('abstaining from an existing typed roster name focuses entry without creating or binding', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness options={[candidate(7, 'strong', 0.8)]} initialValue="Person 7" onCommit={onCommit} />);
    await user.keyboard('{ArrowDown}');
    await user.click(screen.getByRole('button', { name: abstainName }));

    expect(screen.getByRole('combobox', { name: 'Name this person' })).toHaveFocus();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('rendering, opening and typing are read-only; Save explicitly creates a novel name', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const onCommit = vi.fn();
    const onReject = vi.fn();
    render(<Harness options={[candidate(7, 'possible', 0.5)]} onCommit={onCommit} onReject={onReject} />);
    await user.keyboard('{ArrowDown}');
    await user.type(screen.getByRole('combobox', { name: 'Name this person' }), 'Novel Name');

    expect(screen.getByRole('option', { name: /Person 7/ })).toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
    expect(onReject).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Save name' }));
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'create', name: 'Novel Name' });
  });

  it('keyboard confirmation preserves the selected roster ID and does not auto-commit on opening', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness options={[candidate(7, 'strong', 0.8), candidate(8, 'possible', 0.5)]} onCommit={onCommit} />);
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(onCommit).not.toHaveBeenCalled();
    const row = screen.getByRole('option', { name: /Person 8/ });
    expect(row).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('combobox')).toHaveAttribute('aria-activedescendant', row.id);
    await user.keyboard('{Enter}');
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'roster', rosterEntryId: 8, name: 'Person 8' });
  });

  it('renders quality-ok below-floor GET rows through the real reader without any writes', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    const requests: { url: URL; method: string }[] = [];
    const body: RosterCandidatesResponse = {
      model_id: 'fixture-model', embedding_model: 'fixture-model',
      computed_at: '2026-10-15T00:00:00Z', probe_face_count: 1, reference_face_count: 3,
      quality_flag: 'ok',
      thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
      candidates: [0.17, 0.11, 0.06].map((similarity, index) => ({
        cluster_id: `cluster-${index + 7}`, roster_entry_id: index + 7,
        name: `Person ${index + 7}`, band: 'none', similarity,
      })),
    };
    registerConfig({ nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php', endpoints: {
      recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
    } });
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, window.location.origin);
      const method = init?.method ?? 'GET';
      requests.push({ url, method });
      if (method !== 'GET' || url.pathname !== '/wp-json/acx/v1/recognition/clusters/probe/roster-candidates') {
        return Promise.reject(new Error('Unexpected fixture request'));
      }
      return Promise.resolve(new Response(JSON.stringify(body), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }));
    }));
    const ReadHarness = () => {
      const closest = useClusterRosterCandidates({
        clusterId: 'probe', enabled: true,
        rosterEntries: [7, 8, 9].map((id) => ({ id, name: `Person ${id}` })),
      });
      return <Harness options={closest.options} onCommit={onCommit} />;
    };
    queryClient = buildTestQueryClient();
    render(<ReadHarness />, { wrapper: createQueryWrapper(queryClient) });
    await waitFor(() => expect(queryClient?.isFetching()).toBe(0));
    await user.type(screen.getByRole('combobox', { name: 'Name this person' }), 'Novel Name');

    expect(screen.getAllByRole('option')).toHaveLength(3);
    expect(screen.getAllByText('Below match threshold', { exact: true })).toHaveLength(3);
    expect(screen.getByRole('button', { name: abstainName })).toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
    expect(requests).toHaveLength(1);
    expect(requests[0].url.searchParams.get('top_k')).toBe('5');
    expect(requests.map(({ method }) => method)).toEqual(['GET']);
  });
});
