import React from 'react';
import { cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import {
  fetchClusterRosterCandidates,
  type RosterCandidateBand,
  type RosterCandidatesResponse,
} from '../../../../api/recognition/rosterCandidatesApi';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../../test-utils/mockHooks';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { NameFaceControl, type NameFaceResolution } from '../NameFaceControl';
import { namingOptionValue } from '../buildNamingOptions';
import { useClusterSuggestions } from '../useClusterSuggestions';

vi.mock('../../../../hooks/useRosterHooks', () => ({ useRosterEntries: vi.fn() }));

const IDENTITY_ID = 'identity-unnamed';
const CLUSTER_ID = '5a1e0c00-0000-4000-8000-000000000001';
const ELLYN_CLUSTER_ID = '5a1e0c00-0000-4000-8000-0000000000e1';

const body = (quality: 'ok' | 'low_quality', band: RosterCandidateBand): RosterCandidatesResponse => ({
  model_id: 'fixture-model',
  embedding_model: 'fixture-model',
  computed_at: '2026-10-15T00:00:00Z',
  probe_face_count: 1,
  reference_face_count: 2,
  quality_flag: quality,
  thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
  candidates: [{
    cluster_id: ELLYN_CLUSTER_ID,
    roster_entry_id: 7,
    name: 'Ellyn Heald',
    similarity: band === 'strong' ? 0.8 : 0.12,
    band,
  }],
});

let responseBody: RosterCandidatesResponse;
let requests: { url: URL; method: string }[];
let queryClient: ReturnType<typeof buildTestQueryClient>;
let wrapper: ReturnType<typeof createQueryWrapper>;

const rosterRequests = () => requests.filter(({ url }) => url.pathname.endsWith('/roster-candidates'));

beforeEach(() => {
  responseBody = body('ok', 'none');
  requests = [];
  queryClient = buildTestQueryClient();
  wrapper = createQueryWrapper(queryClient);
  registerConfig({
    nonce: 'fixture-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
      recognitionIdentitySuggestions: '/wp-json/acx/v1/recognition/identities',
    },
  });
  vi.mocked(useRosterEntries).mockReturnValue(createMockQuery({ data: [] }));
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    requests.push({ url, method: init?.method ?? 'GET' });
    let payload: unknown;
    if (url.pathname.endsWith('/roster-candidates')) {
      payload = responseBody;
    } else if (url.pathname.endsWith('/identities/suggestions')) {
      payload = { matches: { [IDENTITY_ID]: [] } };
    } else if (url.pathname.endsWith('/clusters')) {
      payload = { clusters: [], limit: 50, total: 0, truncated: false };
    } else {
      throw new Error(`Unexpected fixture route: ${url.pathname}`);
    }
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  }));
});

afterEach(async () => {
  cleanup();
  await queryClient.cancelQueries();
  queryClient.clear();
  resetConfigCache();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const useUnnamedSuggestions = (labelInput: string) => useClusterSuggestions({
  identityId: IDENTITY_ID,
  editableClusterId: CLUSTER_ID,
  enabled: true,
  labelInput,
  debounceMs: 0,
});

const NamingHarness = ({ onCommit }: { onCommit: (resolution: NameFaceResolution) => void }) => {
  const [value, setValue] = React.useState('');
  const suggestions = useUnnamedSuggestions(value);
  return (
    <NameFaceControl
      options={suggestions.options}
      value={value}
      onValueChange={setValue}
      onCommit={onCommit}
      isLoading={suggestions.isLoading}
      suggestionsError={suggestions.isError}
      onRetrySuggestions={suggestions.retry}
      ariaLabel="Name this person"
      commitLabel="Save name"
    />
  );
};

describe('F4 real closest-roster read during manual naming', () => {
  it.each(['Unnamed person', 'Zoe'])('retains the fetched weak tuple when labelInput changes to %s', async (labelInput) => {
    const { result, rerender } = renderHook(({ value }) => useUnnamedSuggestions(value), {
      initialProps: { value: '' }, wrapper,
    });
    const expected = {
      value: namingOptionValue('person', 7), roster_entry_id: 7,
      cluster_id: ELLYN_CLUSTER_ID, band: 'none', label: 'Ellyn Heald',
    };
    await waitFor(() => expect(result.current.options).toContainEqual(expect.objectContaining(expected)));
    expect(rosterRequests()).toHaveLength(1);
    expect(rosterRequests()[0]?.url.searchParams.get('top_k')).toBe('5');

    rerender({ value: labelInput });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.options).toContainEqual(expect.objectContaining(expected));
    expect(result.current.isError).toBe(false);
    expect(requests.every(({ method }) => method === 'GET')).toBe(true);
  });
});

describe('F5 probe quality across the real HTTP adapter, query and naming control', () => {
  it('rejects a low_quality/strong HTTP 200 envelope at the adapter boundary', async () => {
    responseBody = body('low_quality', 'strong');
    await expect(fetchClusterRosterCandidates(CLUSTER_ID)).rejects.toThrow(/quality|band|strong/i);
    expect(rosterRequests()).toHaveLength(1);
  });

  it('reports low_quality/strong as isError instead of a clean successful choice', async () => {
    responseBody = body('low_quality', 'strong');
    const { result } = renderHook(() => useUnnamedSuggestions(''), { wrapper });
    await waitFor(() => expect(rosterRequests()).toHaveLength(1));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isError).toBe(true);
    expect(result.current.options.some((option) => option.band === 'strong')).toBe(false);
  });

  it('shows a visible error for low_quality/strong and never presents Strong match', async () => {
    responseBody = body('low_quality', 'strong');
    const onCommit = vi.fn();
    render(<NamingHarness onCommit={onCommit} />, { wrapper });
    await waitFor(() => expect(rosterRequests()).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole('combobox')).toBeEnabled());
    const user = userEvent.setup();
    await user.click(screen.getByRole('combobox'));
    await user.keyboard('{ArrowDown}');

    expect(screen.queryByText('Strong match')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load name suggestions.');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it.each([['low_quality', 'none', 'Below match threshold'], ['ok', 'strong', 'Strong match']] as const)(
    'retains a valid %s/%s choice as %s and commits only on selection',
    async (quality, band, label) => {
      responseBody = body(quality, band);
      const user = userEvent.setup();
      const onCommit = vi.fn();
      render(<NamingHarness onCommit={onCommit} />, { wrapper });
      await waitFor(() => expect(rosterRequests()).toHaveLength(1));
      await waitFor(() => expect(screen.getByRole('combobox')).toBeEnabled());
      await user.click(screen.getByRole('combobox'));
      await user.keyboard('{ArrowDown}');
      const option = screen.getByRole('option', { name: /Ellyn Heald/ });
      expect(option).toHaveTextContent(label);
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(onCommit).not.toHaveBeenCalled();
      expect(requests.every(({ method }) => method === 'GET')).toBe(true);
      await user.click(option);
      expect(onCommit).toHaveBeenCalledExactlyOnceWith({ kind: 'roster', rosterEntryId: 7, name: 'Ellyn Heald' });
    },
  );
});
