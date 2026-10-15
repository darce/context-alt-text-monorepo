/**
 * RED (c82 FIR roster-candidates): an Unnamed person with no pending suggestion
 * must surface the closest named roster people from GET
 * /clusters/{id}/roster-candidates, including below-floor matches as weak
 * options. Nothing in the frontend calls that route today (audit F1), so the
 * roster assertions fail for a causal reason: the request is never made and
 * the weak candidate never reaches the naming options.
 *
 * Fixtures reuse the existing useClusterSuggestions mocks (identity batch,
 * cluster list, roster entries). Transport is intercepted at globalThis.fetch,
 * so no module that does not yet exist is imported.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { parseNamingOptionValue } from '../buildNamingOptions';
import { useClusterSuggestions } from '../useClusterSuggestions';
import * as recognitionApi from '../../../../api/recognition';
import { registerConfig, resetConfigCache } from '../../../../api/config';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';

vi.mock('../../../../api/recognition', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../../api/recognition')>()),
  fetchIdentitiesSuggestions: vi.fn(),
  listRecognitionClusters: vi.fn(),
}));

vi.mock('../../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

const IDENTITY_ID = 'identity-unnamed';
const UNNAMED_CLUSTER_ID = 'c-unnamed';
const ELLYN_CLUSTER_ID = 'c-ellyn';

interface RosterCandidateWire {
  cluster_id: string;
  name: string;
  similarity: number;
  band: 'strong' | 'possible' | 'none';
  roster_entry_id: number | null;
}

/**
 * Backend envelope from GET /clusters/{id}/roster-candidates, matching every required
 * field of packages/shared-contracts/schemas/roster-candidates-response.schema.json.
 * Candidates are ranked, and below-floor matches are kept with band none.
 */
const rosterCandidatesBody = (candidates: RosterCandidateWire[]) => ({
  model_id: 'fixture-model',
  embedding_model: 'fixture-embedding',
  computed_at: '2026-10-15T00:00:00Z',
  probe_face_count: 1,
  reference_face_count: 2,
  quality_flag: 'ok',
  thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.6 },
  candidates,
});

/** Closest named person, below the automatic suggestion floor: band none, not a pending row. */
const belowFloorEllyn: RosterCandidateWire = {
  cluster_id: ELLYN_CLUSTER_ID,
  name: 'Ellyn Heald',
  similarity: 0.42,
  band: 'none',
  roster_entry_id: 7,
};

let fetchMock: ReturnType<typeof vi.fn>;

const requestUrls = (): URL[] =>
  fetchMock.mock.calls.map(([input]) => new URL(String(input), 'http://localhost'));

const rosterRequestUrls = (): URL[] => requestUrls().filter((url) => url.pathname.includes('/roster-candidates'));

const renderUnnamedCard = (enabled = true) =>
  renderHook(
    () =>
      useClusterSuggestions({
        identityId: IDENTITY_ID,
        enabled,
        editableClusterId: UNNAMED_CLUSTER_ID,
        labelInput: '',
        debounceMs: 0,
      }),
    { wrapper: createQueryWrapper(buildTestQueryClient()) },
  );

beforeEach(() => {
  registerConfig({
    nonce: 'fixture-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {
      recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
    },
  });
  // No pending suggestion row for the unnamed identity: the batch comes back empty.
  vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({ matches: {} });
  vi.mocked(recognitionApi.listRecognitionClusters).mockResolvedValue({
    clusters: [],
    total: 0,
    truncated: false,
  } as never);
  vi.mocked(useRosterEntries).mockReturnValue({
    data: [],
    isLoading: false,
    isError: false,
  } as never);

  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname.includes('/roster-candidates')) {
      return new Response(JSON.stringify(rosterCandidatesBody([belowFloorEllyn])), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    return new Response('{}', { status: 404, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  resetConfigCache();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('useClusterSuggestions roster candidates (RED c82 FIR)', () => {
  it('opening naming on an unnamed card with no pending row requests roster candidates bounded to top 5', async () => {
    // Predicted first failure: zero roster-candidates requests; no frontend caller exists (audit F1).
    renderUnnamedCard();

    await waitFor(() => expect(rosterRequestUrls()).toHaveLength(1));
    const [url] = rosterRequestUrls();
    expect(url?.pathname).toContain(`/clusters/${UNNAMED_CLUSTER_ID}/roster-candidates`);
    expect(url?.searchParams.get('top_k')).toBe('5');
  });

  it('offers the closest named person below the floor as a weak option, keeping the person and cluster tuple, with no write on display', async () => {
    // Predicted first failure: options never contain 'Ellyn Heald' because the candidate is never fetched.
    const { result } = renderUnnamedCard();

    await waitFor(() => expect(result.current.options.some((option) => option.label === 'Ellyn Heald')).toBe(true));
    const option = result.current.options.find((candidate) => candidate.label === 'Ellyn Heald');

    expect(parseNamingOptionValue(String(option?.value))).toMatchObject({ source: 'person', id: '7' });
    expect(JSON.stringify(option)).toContain(ELLYN_CLUSTER_ID);
    expect(option).toMatchObject({ band: 'none' });

    // Display is read-only: every request issued while showing candidates is a GET.
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true);
  });

  it('does not request roster candidates while the card is not expanded (lazy query budget control)', async () => {
    // Control: passes on the current tree because no roster request exists at all. Keeps the lazy budget pinned once the feature lands.
    renderUnnamedCard(false);

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(rosterRequestUrls()).toHaveLength(0);
  });

  it('shows the newest canonical person name after a rename, not the cached Gilded snapshot', async () => {
    // Predicted first failure: the stale batch row label 'Gilded Cypress' is projected verbatim onto the cluster suggestion.
    vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({
      matches: {
        [IDENTITY_ID]: [
          {
            cluster_id: ELLYN_CLUSTER_ID,
            label: 'Gilded Cypress',
            similarity: 0.9,
            identity_count: 1,
            suggestion_id: 'sug-stale-gilded',
          },
        ],
      },
    } as never);
    vi.mocked(recognitionApi.listRecognitionClusters).mockResolvedValue({
      clusters: [{ id: ELLYN_CLUSTER_ID, label: 'Ellyn Heald', identity_count: 1 }],
      total: 1,
      truncated: false,
    } as never);
    vi.mocked(useRosterEntries).mockReturnValue({
      data: [{ id: 7, name: 'Ellyn Heald' }],
      isLoading: false,
      isError: false,
    } as never);

    const { result } = renderUnnamedCard();

    await waitFor(() => expect(result.current.options.length).toBeGreaterThan(0));
    const labels = result.current.options.map((option) => option.label);
    expect(labels).not.toContain('Gilded Cypress');
    expect(labels).toContain('Ellyn Heald');
  });
});
