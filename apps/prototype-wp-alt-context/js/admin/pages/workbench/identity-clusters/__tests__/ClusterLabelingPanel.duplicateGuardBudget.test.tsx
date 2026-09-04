/**
 * FEBT1G-H-05 / FEBT1G-H-08 regression cover for ClusterLabelingPanel.
 *
 * H-05: the submit-time remote duplicate lookup must fail CLOSED. A lookup failure is
 * not evidence that the name is free, and it is the only protection once the local
 * 20-item collision list is incomplete.
 * H-08: the declared interactive budget must be enforced by the caller, not merely
 * declared and then ignored by a request that drops its AbortSignal.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

import { ClusterLabelingPanel } from '../ClusterLabelingPanel';
import { CLUSTER_MUTATION_ERROR_COPY } from '../clusterMutationUtils';
import {
  fetchClusterMembers,
  listRecognitionClusters,
  mergeCluster,
  updateClusterLabel,
  type ClusterMembersResponse,
} from '../../../../api/recognition';
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
vi.mock('../../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

const emptyMembers: ClusterMembersResponse = { members: [], limit: 500, total: 0, truncated: false };

const emptyList = { clusters: [], limit: 20, total: 0, truncated: false };

const renderPanel = () => {
  const queryClient = new QueryClient({
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

describe('ClusterLabelingPanel duplicate guard and interactive budget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchClusterMembers).mockResolvedValue(emptyMembers);
    vi.mocked(updateClusterLabel).mockResolvedValue(undefined);
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({ data: [], isLoading: false, isError: false, refetch: vi.fn() }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('FEBT1G-H-05: a failed remote duplicate lookup blocks the write instead of failing open', async () => {
    // The naming-options query (limit 20) succeeds and finds nothing; only the
    // submit-time uniqueness lookup (limit 10) fails.
    vi.mocked(listRecognitionClusters).mockImplementation(async (params?: { limit?: number }) => {
      if (params?.limit === 10) {
        throw new Error('network down');
      }
      return emptyList;
    });

    renderPanel();
    await typeNameAndSave(setupUser(false), 'Slate Willow');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not check whether that name is already in use. Please try again.',
    );
    expect(updateClusterLabel).not.toHaveBeenCalled();
  });

  it('FEBT1G-H-05: a successful lookup that finds nothing still allows the write', async () => {
    vi.mocked(listRecognitionClusters).mockResolvedValue(emptyList);

    renderPanel();
    await typeNameAndSave(setupUser(false), 'Slate Willow');

    await waitFor(() => {
      expect(updateClusterLabel).toHaveBeenCalledWith('panel-cluster-id', 'Slate Willow', expect.anything());
    });
  });

  it('FEBT1G-H-08: a save whose request ignores the abort signal still fails at the 3s budget', async () => {
    vi.mocked(listRecognitionClusters).mockResolvedValue(emptyList);
    // Signal-deaf request: resolves never, ignores controller.abort() exactly like
    // commitClusterToRosterEntry, which takes no signal at all.
    vi.mocked(updateClusterLabel).mockImplementation(() => new Promise<void>(() => undefined));

    vi.useFakeTimers();
    renderPanel();
    await typeNameAndSave(setupUser(true), 'Slate Willow');
    await waitFor(() => expect(updateClusterLabel).toHaveBeenCalled());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    // Copy is owned by docs/ux-maps/febt-1-job-error-states.md, not by this test.
    expect(await screen.findByRole('alert')).toHaveTextContent(CLUSTER_MUTATION_ERROR_COPY.timeout);
  });

  it('FEBT1G-H-08: merge is held to the same interactive budget as save', async () => {
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
    vi.mocked(mergeCluster).mockImplementation(() => new Promise(() => undefined));

    vi.useFakeTimers();
    const user = setupUser(true);
    renderPanel();
    await typeNameAndSave(user, 'Slate Willow');

    const mergeButton = await screen.findByRole('button', { name: /^Merge into group/ });
    await user.click(mergeButton);
    await waitFor(() => expect(mergeCluster).toHaveBeenCalled());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    // Copy is owned by docs/ux-maps/febt-1-job-error-states.md, not by this test.
    expect(await screen.findByRole('alert')).toHaveTextContent(CLUSTER_MUTATION_ERROR_COPY.timeout);
  });
});
