/**
 * FEBT1G-H-05 / FEBT1G-H-08 / FEBT1-LC-01 regression cover for ClusterLabelingPanel.
 *
 * H-05: the submit-time remote duplicate lookup must fail CLOSED. A lookup failure is
 * not evidence that the name is free, and it is the only protection once the local
 * 20-item collision list is incomplete.
 * H-08: the declared interactive budget must be enforced by the caller, not merely
 * declared and then ignored by a request that drops its AbortSignal.
 * LC-01: a deadline that only abandons the caller still leaks the server-side write, so
 * every budgeted write must receive a live signal that the deadline actually aborts.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

import { ClusterLabelingPanel } from '../ClusterLabelingPanel';
import {
  fetchClusterMembers,
  listRecognitionClusters,
  mergeCluster,
  updateClusterLabel,
  type ClusterMembersResponse,
} from '../../../../api/recognition';
import { commitClusterToRosterEntry, type RosterEntry } from '../../../../api/rosterApi';
import { isAbortError, isClusterMutationTimeoutError } from '../clusterMutationUtils';
import { CLUSTER_LABELING_OPERATION, SAVE_TIMEOUT_MS, withTimeout } from '../clusterLabelingBudget';
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
    // Signal-deaf request: resolves never, ignores controller.abort(). The budget must
    // still fire, so cancellation and the deadline are independent guarantees.
    vi.mocked(updateClusterLabel).mockImplementation(() => new Promise<void>(() => undefined));

    vi.useFakeTimers();
    renderPanel();
    await typeNameAndSave(setupUser(true), 'Slate Willow');
    await waitFor(() => expect(updateClusterLabel).toHaveBeenCalled());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('Save is taking too long. Please try again.');
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

    expect(await screen.findByRole('alert')).toHaveTextContent('Save is taking too long. Please try again.');
  });

  it('FEBT1-LC-01: the budget aborts the signal handed to mergeCluster, not just the caller', async () => {
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
    let mergeSignal: AbortSignal | undefined;
    vi.mocked(mergeCluster).mockImplementation((_source, _target, _label, signal) => {
      mergeSignal = signal;
      return new Promise(() => undefined);
    });

    vi.useFakeTimers();
    const user = setupUser(true);
    renderPanel();
    await typeNameAndSave(user, 'Slate Willow');

    const mergeButton = await screen.findByRole('button', { name: /^Merge into group/ });
    await user.click(mergeButton);
    await waitFor(() => expect(mergeCluster).toHaveBeenCalled());

    // The signal is real and live at dispatch time: `expect.anything()` in the arity
    // assertions cannot be satisfied by a placeholder that cancels nothing.
    expect(mergeSignal).toBeInstanceOf(AbortSignal);
    expect(mergeSignal?.aborted).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(mergeSignal?.aborted).toBe(true);
    // FEBT1-LC-02: the abort reason is the branded, non-abort-like budget sentinel, so a
    // mutation `onError` cannot mistake an expired budget for a user cancel and go silent.
    expect(isClusterMutationTimeoutError(mergeSignal?.reason)).toBe(true);
  });

  it('FEBT1-LC-01: the budget aborts the roster commit signal so the POST is cancelled', async () => {
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

    expect(commitSignal).toBeInstanceOf(AbortSignal);
    expect(commitSignal?.aborted).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(commitSignal?.aborted).toBe(true);
    expect(isClusterMutationTimeoutError(commitSignal?.reason)).toBe(true);
    expect(isAbortError(commitSignal?.reason)).toBe(false);
    expect(await screen.findByRole('alert')).toHaveTextContent('Save is taking too long. Please try again.');
  });

  it('FEBT1G-M-14: "rename anyway" is a one-shot escape hatch, not a latch', async () => {
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
  });

  it('FEBT1-LC-02: an abort surfacing out of a budgeted write is never rethrown abort-like', async () => {
    // There is no cancel affordance on this path, so an AbortError here is our deadline or
    // the transport's own composed timeout. Rethrown raw it is abort-like, and a mutation
    // `onError` would treat it as a user cancel and render no error at all.
    const raw = new DOMException('The operation was aborted.', 'AbortError');
    expect(isAbortError(raw)).toBe(true);

    const rejected = await withTimeout(
      () => Promise.reject(raw),
      SAVE_TIMEOUT_MS,
      CLUSTER_LABELING_OPERATION.SAVE,
    ).catch((error: unknown) => error);

    expect(isClusterMutationTimeoutError(rejected)).toBe(true);
    expect(isAbortError(rejected)).toBe(false);
  });
});
