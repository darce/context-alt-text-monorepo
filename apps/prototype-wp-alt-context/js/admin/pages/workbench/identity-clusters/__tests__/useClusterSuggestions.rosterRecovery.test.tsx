import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig } from '../../../../api/config';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../../test-utils/mockHooks';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { namingOptionValue } from '../buildNamingOptions';
import { useClusterSuggestions } from '../useClusterSuggestions';

vi.mock('../../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

/**
 * Roster-recovery RED (c82-fir-ui-recovery-red). Drives the public
 * useClusterSuggestions hook through global fetch so the real api/recognition
 * request path runs. Imports only modules that exist on main. Each failing
 * assertion names a behaviour the source lane must add: isError and retry on
 * the hook, a lazy top_k=5 roster-candidates read, and a committable-only
 * choice list that keeps payload order.
 */

const IDENTITY_ID = 'identity-1';
const UNNAMED_CLUSTER_ID = 'cluster-unnamed';
const ELLYN_CLUSTER_ID = '5a1e0c00-0000-4000-8000-0000000000e1';
const PAT_CLUSTER_ID = '5a1e0c00-0000-4000-8000-0000000000a9';
const GHOST_CLUSTER_ID = '5a1e0c00-0000-4000-8000-0000000000c3';
const BATCH_SUFFIX = '/suggestions';
const ROSTER_SUFFIX = '/roster-candidates';

type RosterBand = 'strong' | 'possible' | 'none';

interface RosterCandidateRow {
  cluster_id: string;
  name: string;
  similarity: number;
  band: RosterBand;
  roster_entry_id: number | null;
}

interface ScriptedResponse {
  status: number;
  body: unknown;
}

interface RecordedRequest {
  method: string;
  pathname: string;
  searchParams: URLSearchParams;
}

/** The public hook plus the read-state fields this lane requires (absent on main). */
type SuggestionsReadResult = ReturnType<typeof useClusterSuggestions> & {
  isError?: boolean;
  retry?: () => void;
};

const ELLYN: RosterCandidateRow = {
  cluster_id: ELLYN_CLUSTER_ID,
  name: 'Ellyn Heald',
  similarity: 0.12,
  band: 'none',
  roster_entry_id: 7,
};
const PAT: RosterCandidateRow = {
  cluster_id: PAT_CLUSTER_ID,
  name: 'Pat Nguyen',
  similarity: 0.38,
  band: 'possible',
  roster_entry_id: 9,
};
const GHOST: RosterCandidateRow = {
  cluster_id: GHOST_CLUSTER_ID,
  name: 'Ghost Name',
  similarity: 0.61,
  band: 'strong',
  roster_entry_id: null,
};
const PENDING_BEA = {
  cluster_id: 'cluster-bea',
  label: 'Bea Burke',
  similarity: 0.41,
  identity_count: 9,
  suggestion_id: 'sug-bea-1',
};

const ok = (body: unknown): ScriptedResponse => ({ status: 200, body });
const unavailable = (): ScriptedResponse => ({ status: 503, body: { code: 'service_unavailable' } });

const rosterBody = (candidates: RosterCandidateRow[]) => ({
  model_id: 'probe-space-test',
  embedding_model: 'probe-space-test',
  computed_at: '2026-10-15T00:00:00Z',
  probe_face_count: 1,
  reference_face_count: 1,
  quality_flag: 'ok',
  thresholds: { suggestion_floor: 0.35, suggestion_ceiling: 0.55, similarity_threshold: 0.55 },
  candidates,
});

const batchBody = (rows: unknown[]) => ({ matches: { [IDENTITY_ID]: rows } });

// Scripted queues: the last entry repeats, so one entry covers every later call.
const script: { batch: ScriptedResponse[]; roster: ScriptedResponse[] } = { batch: [], roster: [] };
let requests: RecordedRequest[] = [];

const takeScripted = (queue: ScriptedResponse[], fallback: ScriptedResponse): ScriptedResponse => {
  const next = queue.length > 1 ? queue.shift() : queue[0];
  return next ?? fallback;
};

const handleRequest = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  const url = new URL(raw, window.location.origin);
  const method = (init?.method ?? 'GET').toUpperCase();
  requests.push({ method, pathname: url.pathname, searchParams: url.searchParams });

  let scripted: ScriptedResponse;
  if (method !== 'GET') {
    scripted = ok({});
  } else if (url.pathname.endsWith(ROSTER_SUFFIX)) {
    scripted = takeScripted(script.roster, ok(rosterBody([])));
  } else if (url.pathname.endsWith(BATCH_SUFFIX)) {
    scripted = takeScripted(script.batch, ok(batchBody([])));
  } else {
    scripted = ok({ clusters: [], limit: 20, offset: 0, total: 0, truncated: false });
  }
  return Promise.resolve(
    new Response(JSON.stringify(scripted.body), {
      status: scripted.status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
};

const mutationRequests = (): RecordedRequest[] => requests.filter((request) => request.method !== 'GET');
const batchRequests = (): RecordedRequest[] => requests.filter((request) => request.pathname.endsWith(BATCH_SUFFIX));
const rosterRequests = (): RecordedRequest[] =>
  requests.filter((request) => request.pathname.endsWith(ROSTER_SUFFIX));
const labelsOf = (result: { current: SuggestionsReadResult }): string[] =>
  result.current.options.map((option) => option.label);

describe('useClusterSuggestions roster recovery (RED)', () => {
  let queryClient: ReturnType<typeof buildTestQueryClient>;
  let wrapper: ReturnType<typeof createQueryWrapper>;

  const renderUnnamedCard = (enabled = true) =>
    renderHook(
      () =>
        useClusterSuggestions({
          identityId: IDENTITY_ID,
          enabled,
          editableClusterId: UNNAMED_CLUSTER_ID,
          labelInput: '',
          debounceMs: 0,
        }) as SuggestionsReadResult,
      { wrapper },
    );

  beforeEach(() => {
    vi.clearAllMocks();
    requests = [];
    script.batch = [];
    script.roster = [];
    registerConfig({
      nonce: 'a1b2c3d4e5f6a7b8',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        recognitionIdentitySuggestions: '/wp-json/acx/v1/recognition/identities',
        recognitionClusters: '/wp-json/acx/v1/recognition/clusters',
      },
    });
    vi.stubGlobal('fetch', vi.fn(handleRequest));
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
    queryClient = buildTestQueryClient();
    wrapper = createQueryWrapper(queryClient);
  });

  afterEach(() => {
    queryClient.clear();
    vi.unstubAllGlobals();
  });

  it('reports a failed lazy closest-match read as isError with a callable retry, not as an empty list', async () => {
    // Predicted first failure (pre-fix): the hook issues no roster-candidates read and
    // exposes no isError, so the waitFor on rosterRequests times out first.
    script.batch = [ok(batchBody([]))];
    script.roster = [unavailable()];
    const { result } = renderUnnamedCard();

    await waitFor(() => expect(rosterRequests().length).toBeGreaterThan(0));
    expect(rosterRequests()[0]?.searchParams.get('top_k')).toBe('5');
    expect(rosterRequests()[0]?.pathname).toContain(`/clusters/${UNNAMED_CLUSTER_ID}/`);

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(typeof result.current.retry).toBe('function');
    expect(mutationRequests()).toHaveLength(0);
  });

  it('retry after a 503 re-requests the closest-match read and shows the weak person choice', async () => {
    // Predicted first failure (pre-fix): isError is undefined, so the first waitFor fails
    // and retry is never invoked.
    script.batch = [ok(batchBody([]))];
    script.roster = [unavailable(), ok(rosterBody([ELLYN]))];
    const { result } = renderUnnamedCard();

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(typeof result.current.retry).toBe('function');

    act(() => {
      result.current.retry?.();
    });

    await waitFor(() => expect(labelsOf(result)).toContain('Ellyn Heald'));
    expect(result.current.isError).toBe(false);
    expect(rosterRequests().length).toBeGreaterThanOrEqual(2);
    expect(mutationRequests()).toHaveLength(0);
  });

  it('surfaces a failed identity-batch read as isError with a retry, not as a clean no-suggestion state', async () => {
    // Predicted first failure (pre-fix): the hook return has no isError field, so a failed
    // batch read reaches the caller indistinguishable from "no suggestion".
    script.batch = [unavailable(), ok(batchBody([]))];
    const { result } = renderUnnamedCard();

    // Fixture health: the 503 batch read is actually issued, so the failure below is the missing isError.
    await waitFor(() => expect(batchRequests().length).toBeGreaterThan(0));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(typeof result.current.retry).toBe('function');

    act(() => {
      result.current.retry?.();
    });
    await waitFor(() => expect(result.current.isError).toBe(false));
  });

  it('presents the closest named person as a stable (roster_entry_id, named cluster) choice', async () => {
    // Predicted first failure (pre-fix): no roster-derived option exists, so the
    // 'Ellyn Heald' wait fails before the tuple is checked.
    script.batch = [ok(batchBody([]))];
    script.roster = [ok(rosterBody([ELLYN]))];
    const { result } = renderUnnamedCard();

    await waitFor(() => expect(labelsOf(result)).toContain('Ellyn Heald'));
    const choice = result.current.options.find((option) => option.label === 'Ellyn Heald');
    expect(choice).toMatchObject({
      value: namingOptionValue('cluster', ELLYN_CLUSTER_ID),
      roster_entry_id: 7,
    });
    expect(mutationRequests()).toHaveLength(0);
  });

  it('keeps the on-demand closest person visible after a pending identity row disappears on refetch', async () => {
    // Predicted first failure (pre-fix): no roster read follows the pending row clearing,
    // so 'Ellyn Heald' never appears after the refetch. Before the refetch, no roster read
    // may run while a pending row exists (lazy gate).
    script.batch = [ok(batchBody([PENDING_BEA])), ok(batchBody([]))];
    script.roster = [ok(rosterBody([ELLYN]))];
    const { result } = renderUnnamedCard();

    await waitFor(() => expect(labelsOf(result)).toContain('Bea Burke'));
    expect(rosterRequests()).toHaveLength(0);

    await act(async () => {
      await queryClient.invalidateQueries();
    });

    await waitFor(() => expect(labelsOf(result)).toContain('Ellyn Heald'));
    expect(mutationRequests()).toHaveLength(0);
  });

  it('renders roster candidates in payload order with one row per person and no client re-sort', async () => {
    // Predicted first failure (pre-fix): no roster choice list exists. Pat (0.38) outranks
    // Ellyn (0.12) by similarity, so a client-side similarity sort would put Pat first.
    script.batch = [ok(batchBody([]))];
    script.roster = [ok(rosterBody([ELLYN, PAT]))];
    const { result } = renderUnnamedCard();

    const people = ['Ellyn Heald', 'Pat Nguyen'];
    const peopleLabels = () => labelsOf(result).filter((label) => people.includes(label));
    await waitFor(() => expect(peopleLabels()).toHaveLength(2));
    expect(peopleLabels()).toEqual(['Ellyn Heald', 'Pat Nguyen']);
  });

  it('never offers a candidate with a null roster_entry_id as a committable choice', async () => {
    // Predicted first failure (pre-fix): no roster choice exists, so the committable
    // 'Ellyn Heald' row is absent before the null-mapped 'Ghost Name' row is checked.
    script.batch = [ok(batchBody([]))];
    script.roster = [ok(rosterBody([GHOST, ELLYN]))];
    const { result } = renderUnnamedCard();

    await waitFor(() => expect(labelsOf(result)).toContain('Ellyn Heald'));
    expect(labelsOf(result)).not.toContain('Ghost Name');
    expect(mutationRequests()).toHaveLength(0);
  });

  it('issues no roster read while the card is collapsed (lazy guard, expected GREEN on main)', async () => {
    // Guard, not RED: nothing reads the roster on main, so this passes today. It pins the
    // lazy contract so the source lane cannot fan out one read per card.
    script.batch = [ok(batchBody([]))];
    script.roster = [ok(rosterBody([ELLYN]))];
    const { result } = renderUnnamedCard(false);

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(rosterRequests()).toHaveLength(0);
    expect(labelsOf(result)).not.toContain('Ellyn Heald');
  });
});
