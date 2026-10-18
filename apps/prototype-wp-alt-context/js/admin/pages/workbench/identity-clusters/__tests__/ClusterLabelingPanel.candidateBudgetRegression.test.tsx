import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../../api/config';
import { ClusterLabelingPanel } from '../ClusterLabelingPanel';
import { CLUSTER_MUTATION_ERROR_COPY } from '../clusterMutationUtils';
import {
  fetchClusterMembers,
  listRecognitionClusters,
  updateClusterLabel,
  type ClusterMembersResponse,
} from '../../../../api/recognition';
import { commitClusterToRosterEntry, type RosterEntry } from '../../../../api/rosterApi';
import { isAbortError, isClusterMutationTimeoutError } from '../clusterMutationUtils';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../../test-utils/mockHooks';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text
      .replace(/%(\d+)\$[sd]/g, (_match, group: string) => String(values[Number(group) - 1] ?? ''))
      .replace(/%[sd]/g, () => String(values[index++] ?? ''));
  },
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchClusterMembers: vi.fn(),
    listRecognitionClusters: vi.fn(),
    updateClusterLabel: vi.fn(),
    mergeCluster: vi.fn(),
  };
});
vi.mock('../../../../api/rosterApi', () => ({
  commitClusterToRosterEntry: vi.fn(),
}));
vi.mock('../../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

const emptyMembers: ClusterMembersResponse = { members: [], limit: 500, total: 0, truncated: false };

const emptyList = { clusters: [], limit: 20, total: 0, truncated: false };

const rosterEntry = (id: number, name: string): RosterEntry => ({
  id,
  person_uuid: `uuid-${id}`,
  name,
  tags: [],
  cluster_count: 0,
  clusters: [],
  queue_memberships: [],
  updated_at: '2026-01-01T00:00:00Z',
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: null,
});

let queryClient: QueryClient;

const renderPanel = () => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ClusterLabelingPanel clusterId="panel-cluster-id" onClose={() => undefined} onLabel={vi.fn()} />
    </QueryClientProvider>,
  );
};

type TestUser = ReturnType<typeof userEvent.setup>;

const setupUser = (fakeTimers: boolean): TestUser =>
  fakeTimers
    ? userEvent.setup({ advanceTimers: (ms: number) => vi.advanceTimersByTimeAsync(ms) })
    : userEvent.setup();

const typeNameAndSave = async (user: TestUser, name: string) => {
  const input = await screen.findByRole('combobox', { name: 'Name' });
  await user.clear(input);
  await user.type(input, name);
  await user.click(screen.getByRole('button', { name: 'Save name' }));
};

// Real candidate adapter fails through an explicit HTTP fixture; write mocks stay
// signal-deaf so only the production deadline can cancel the dispatched write.
describe('ClusterLabelingPanel candidate-read isolation from write budgets', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    registerConfig({
      nonce: 'fixture-nonce', ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: { recognitionClusters: '/wp-json/acx/v1/recognition/clusters' },
    });
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, window.location.origin);
      expect(url.pathname).toBe('/wp-json/acx/v1/recognition/clusters/panel-cluster-id/roster-candidates');
      expect(url.searchParams.get('top_k')).toBe('5');
      expect(init?.method).toBe('GET');
      return Promise.resolve(new Response(JSON.stringify({ code: 'service_unavailable' }), {
        status: 503, headers: { 'Content-Type': 'application/json' },
      }));
    }));
    vi.mocked(fetchClusterMembers).mockResolvedValue(emptyMembers);
    vi.mocked(updateClusterLabel).mockResolvedValue(undefined);
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({ data: [], isLoading: false, isError: false, refetch: vi.fn() }),
    );
  });
  afterEach(async () => {
    cleanup();
    await queryClient.cancelQueries();
    queryClient.clear();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    resetConfigCache();
  });
  it('candidate read failure preserves FEBT1-LC-01: the budget aborts the roster commit signal so the POST is cancelled', async () => {
    vi.mocked(listRecognitionClusters).mockResolvedValue(emptyList);
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [rosterEntry(42, 'Slate Willow')],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
    let commitSignal: AbortSignal | undefined;
    vi.mocked(commitClusterToRosterEntry).mockImplementation((_request, signal) => {
      commitSignal = signal;
      return new Promise(() => undefined);
    });

    vi.useFakeTimers();
    renderPanel();
    await typeNameAndSave(setupUser(true), 'Slate Willow');
    await waitFor(() => expect(commitClusterToRosterEntry).toHaveBeenCalled());

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load name suggestions.');
    expect(screen.getByRole('combobox', { name: 'Name' })).toBeEnabled();
    expect(updateClusterLabel).not.toHaveBeenCalled();
    expect(commitSignal).toBeInstanceOf(AbortSignal);
    expect(commitSignal?.aborted).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(commitSignal?.aborted).toBe(true);
    expect(isClusterMutationTimeoutError(commitSignal?.reason)).toBe(true);
    expect(isAbortError(commitSignal?.reason)).toBe(false);
    expect(await screen.findByText(CLUSTER_MUTATION_ERROR_COPY.timeout)).toBeInTheDocument();
    expect(screen.getAllByRole('alert')).toHaveLength(2);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('healthy empty-roster control preserves FEBT1G-M-14: "rename anyway" is a one-shot escape hatch, not a latch', async () => {
    // The guard's escape hatch must clear on the submit it authorised. If it stayed armed,
    // every later save in the same session would skip duplicate protection entirely —
    // the same fail-open class as H-04, reintroduced through the extracted hook.
    vi.mocked(listRecognitionClusters).mockResolvedValue({
      clusters: [
        {
          id: 'target-cluster-id',
          label: 'Slate Willow',
          is_auto_label: false,
          identity_count: 10,
          member_ids: [],
          representative_identity: { media_id: 1, bbox: { x: 0, y: 0, width: 1, height: 1 } },
          sample_identities: [],
        },
      ],
      limit: 20,
      total: 1,
      truncated: false,
    });
    vi.mocked(updateClusterLabel).mockRejectedValue(new Error('write rejected'));

    const user = setupUser(false);
    renderPanel();
    await typeNameAndSave(user, 'Slate Willow');

    // First submit is blocked by the collision.
    const renameAnyway = await screen.findByRole('button', { name: 'Rename anyway' });
    expect(updateClusterLabel).not.toHaveBeenCalled();

    // The operator overrides once; the write is attempted and fails, so nothing resets it.
    await user.click(renameAnyway);
    await waitFor(() => expect(updateClusterLabel).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole('alert')).toBeInTheDocument();

    // Saving the same colliding name again must re-arm the guard, not ride the override.
    await user.click(screen.getByRole('button', { name: 'Save name' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Rename anyway' })).toBeInTheDocument());
    expect(updateClusterLabel).toHaveBeenCalledTimes(1);
    expect(fetch).not.toHaveBeenCalled();
  });

});
