import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import { ClusterLabelingPanel } from '../ClusterLabelingPanel';
import {
  fetchClusterMembers,
  listRecognitionClusters,
  mergeCluster,
  revertMergeCluster,
  updateClusterLabel,
  type ClusterIdentity,
  type ClusterListResponse,
  type ClusterMembersResponse,
} from '../../../../api/recognition';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import type { TopUnlabeledClustersResponse } from '../../../../api/recognition/types/cluster';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../../test-utils/mockHooks';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
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
    revertMergeCluster: vi.fn(),
  };
});
vi.mock('../../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

const renderPanel = (onLabel: (label: string) => void = vi.fn(), clusterId = 'panel-cluster-id') => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });

  return {
    onLabel,
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ClusterLabelingPanel clusterId={clusterId} onClose={() => undefined} onLabel={onLabel} />
      </QueryClientProvider>,
    ),
  };
};

const duplicateClusterMatch = {
  id: 'target-cluster-id',
  label: 'Slate Willow',
  is_auto_label: false,
  identity_count: 10,
  member_ids: [],
  representative_identity: {
    media_id: 1,
    bbox: { x: 0, y: 0, width: 1, height: 1 },
  },
  sample_identities: [],
};

const makeClusterListResponse = (clusters: ClusterListResponse['clusters'] = [duplicateClusterMatch]) => ({
  clusters,
  limit: 10,
  total: clusters.length,
  truncated: false,
});

const makeClusterMembersResponse = (members: ClusterIdentity[] = []): ClusterMembersResponse => ({
  members,
  limit: 500,
  total: members.length,
  truncated: false,
});

describe('ClusterLabelingPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchClusterMembers).mockResolvedValue(makeClusterMembersResponse());
    vi.mocked(updateClusterLabel).mockResolvedValue(undefined);
    vi.mocked(mergeCluster).mockResolvedValue({
      source_id: 'retired-source-id',
      source_label: null,
      target_id: 'target-cluster-id',
      target_label: 'Slate Willow',
      identities_moved: 5,
      moved_identity_ids: ['id-1'],
      target_identity_count: 10,
    });
    vi.mocked(revertMergeCluster).mockResolvedValue({
      restored_cluster_id: 'panel-cluster-id',
      restored_label: null,
      restored_identity_count: 5,
      target_cluster_id: 'target-cluster-id',
      target_identity_count: 5,
    });
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse([]));
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
  });

  const selectOrCreateName = async (name: string) => {
    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, name);
    // Prefer selecting an existing option; Create only appears when the list is empty.
    const option = await screen.findByRole('option', { name: new RegExp(name, 'i') }).catch(() => null);
    if (option) {
      await user.click(option);
      return;
    }
    await user.click(screen.getByRole('button', { name: `Create "${name}"` }));
  };

  it('blocks save with pre-save duplicate guard for an existing cluster and merges with named target (PR-18/23/24)', async () => {
    // Predicted first failure: save calls updateClusterLabel without showing guard UI
    const onLabel = vi.fn();
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse());

    renderPanel(onLabel);

    // Selecting a cluster option primes the guard (INT-07 outcome sample on the same surface).
    await selectOrCreateName('Slate Willow');

    expect(
      await screen.findByText('A name matching "Slate Willow" already exists. Choose how to proceed.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Merge target: cluster "Slate Willow" \(10 members\)/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Merge into cluster "Slate Willow"' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rename anyway' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(updateClusterLabel).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Merge into cluster "Slate Willow"' }));

    await waitFor(() => {
      expect(mergeCluster).toHaveBeenCalledWith('panel-cluster-id', 'target-cluster-id', 'Slate Willow');
    });
    expect(await screen.findByText(/Merged into/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo merge' })).toBeInTheDocument();
  });

  it('R1-17: merge success drops result.source_id from topUnlabeled', async () => {
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse());
    vi.mocked(mergeCluster).mockResolvedValue({
      source_id: 'retired-source-id',
      source_label: 'Source',
      target_id: 'target-cluster-id',
      target_label: 'Slate Willow',
      identities_moved: 1,
      moved_identity_ids: ['id-1'],
      target_identity_count: 11,
    });
    const { queryClient } = renderPanel();
    const topKey = queryKeys.clusters.topUnlabeled('t');
    queryClient.setQueryData<TopUnlabeledClustersResponse>(topKey, {
      clusters: [
        {
          id: 'retired-source-id',
          tenant_id: 't',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 2,
          user_confirmed: false,
          representatives: [],
        },
        {
          id: 'panel-cluster-id',
          tenant_id: 't',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 2,
          user_confirmed: false,
          representatives: [],
        },
        {
          id: 'target-cluster-id',
          tenant_id: 't',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 10,
          user_confirmed: false,
          representatives: [],
        },
      ],
      limit: 20,
      total: 3,
      truncated: false,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    await selectOrCreateName('Slate Willow');
    await userEvent.click(screen.getByRole('button', { name: 'Merge into cluster "Slate Willow"' }));
    await waitFor(() => {
      expect(mergeCluster).toHaveBeenCalled();
    });
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topKey)?.clusters.map((cluster) => cluster.id),
    ).toEqual(['panel-cluster-id', 'target-cluster-id']);
  });

  it('offers rename-anyway without merge when only a person collides (no unique cluster target)', async () => {
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse([]));
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 11,
            name: 'Only Person',
            person_uuid: 'p11',
            tags: [],
            cluster_count: 0,
            clusters: [],
            queue_memberships: [],
            updated_at: '',
            source_version: 0,
            projection_status: 'current',
            projection_refreshed_at: null,
          },
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    renderPanel();

    await selectOrCreateName('Only Person');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByText('A name matching "Only Person" already exists. Choose how to proceed.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Merge into cluster/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rename anyway' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Rename anyway' }));

    await waitFor(() => {
      expect(updateClusterLabel).toHaveBeenCalledWith('panel-cluster-id', 'Only Person', expect.any(AbortSignal));
    });
  });

  it('does not block self-case-only renames when no other collision exists', async () => {
    const onLabel = vi.fn();
    vi.mocked(listRecognitionClusters).mockResolvedValue(
      makeClusterListResponse([
        {
          ...duplicateClusterMatch,
          id: 'panel-cluster-id',
          label: 'Self Name',
        },
      ]),
    );

    renderPanel(onLabel);

    await selectOrCreateName('Self Name');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(updateClusterLabel).toHaveBeenCalledWith('panel-cluster-id', 'Self Name', expect.any(AbortSignal));
    });
    expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(onLabel).toHaveBeenCalledWith('Self Name');
    });
  });

  it('keeps normal save path when no matching existing label exists', async () => {
    const onLabel = vi.fn();

    renderPanel(onLabel);

    await selectOrCreateName('A New Person');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(updateClusterLabel).toHaveBeenCalledWith('panel-cluster-id', 'A New Person', expect.any(AbortSignal));
    });
    expect(mergeCluster).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(onLabel).toHaveBeenCalledWith('A New Person');
    });
  });

  it('has no dead duplicateMatch / 409 Is-this branch references', () => {
    // Compile-time greenfield check is the absence of the old Yes/No 409 UI.
    renderPanel();
    expect(screen.queryByText(/Is this /)).not.toBeInTheDocument();
  });

  it('E21-14-BR-15: members projection failure shows error, not "No members found."', async () => {
    vi.mocked(fetchClusterMembers).mockRejectedValue(new Error('acx_projection_query_failed'));

    renderPanel();

    expect(await screen.findByText('Unable to load cluster members.')).toBeInTheDocument();
    expect(screen.queryByText('No members found.')).not.toBeInTheDocument();
  });

  // UI-05: members error must offer retry that re-invokes the members query.
  it('UI-05: members error Retry re-invokes fetchClusterMembers', async () => {
    const fetchMock = vi.mocked(fetchClusterMembers);
    fetchMock.mockRejectedValue(new Error('acx_projection_query_failed'));

    renderPanel();

    const error = await screen.findByTestId('acx-cluster-members-error');
    expect(error).toHaveTextContent('Unable to load cluster members.');
    const callsBefore = fetchMock.mock.calls.length;

    await userEvent.click(within(error).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('prefers dedicated face-thumb URLs before client-side crop data', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-thumb',
          media_id: 101,
          similarity: 0.97,
          confidence: 0.99,
          thumb_url: '/recognition/face-thumbs/job-1/101?x=1&y=2&width=20&height=20',
          media_url: '/recognition/blobs/job-1/101',
          bbox: { x: 1, y: 2, width: 20, height: 20 },
        },
      ]),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchClusterMembers).toHaveBeenCalledWith('panel-cluster-id');
    });

    await waitFor(() => {
      expect(container.querySelector('.acx-avatar')).not.toBeNull();
    });

    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
  });

  it('pages through show-all when the members envelope is truncated', async () => {
    const fetchMock = vi.mocked(fetchClusterMembers);
    fetchMock.mockImplementation((_clusterId, params = {}): Promise<ClusterMembersResponse> => {
      if ((params.offset ?? 0) === 0) {
        return Promise.resolve({
          members: [
            {
              identity_id: 'identity-1',
              media_id: 1,
              similarity: 0.9,
              confidence: 0.9,
              bbox: { x: 0, y: 0, width: 10, height: 10 },
              thumb_url: '/recognition/face-thumbs/job/1?x=0&y=0&width=10&height=10',
            },
          ],
          limit: 1,
          total: 2,
          truncated: true,
        });
      }
      return Promise.resolve({
        members: [
          {
            identity_id: 'identity-2',
            media_id: 2,
            similarity: 0.9,
            confidence: 0.9,
            bbox: { x: 0, y: 0, width: 10, height: 10 },
            thumb_url: '/recognition/face-thumbs/job/2?x=0&y=0&width=10&height=10',
          },
        ],
        limit: 1,
        total: 2,
        truncated: false,
      });
    });

    const { container } = renderPanel();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Show all (2)' })).toBeInTheDocument();
    });
    expect(container.querySelectorAll('.acx-cluster-labeling-panel__face')).toHaveLength(1);

    await userEvent.click(screen.getByRole('button', { name: 'Show all (2)' }));

    await waitFor(() => {
      expect(container.querySelectorAll('.acx-cluster-labeling-panel__face')).toHaveLength(2);
    });
    expect(screen.queryByRole('button', { name: 'Show all (2)' })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('panel-cluster-id', { limit: 1, offset: 1 });

    // AT affordance: completion is announced and focus lands on the member
    // grid because the show-all button just unmounted.
    expect(screen.getByText('All 2 members shown')).toHaveAttribute('role', 'status');
    expect(container.querySelector('.acx-cluster-labeling-panel__grid')).toHaveFocus();
  });

  it('prefers a face crop over a generic media thumbnail when bbox data is available', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-generic-thumb',
          media_id: 102,
          similarity: 0.94,
          confidence: 0.98,
          thumb_url: 'http://example.test/uploads/102.jpg',
          media_url: 'http://example.test/media/source-102.jpg',
          bbox: { x: 3, y: 4, width: 26, height: 28 },
        },
      ]),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchClusterMembers).toHaveBeenCalledWith('panel-cluster-id');
    });

    expect(container.querySelector('.acx-face-thumbnail')).not.toBeNull();
    expect(container.querySelector('.acx-avatar')).toBeNull();
    expect(screen.getByRole('img', { name: 'Face to label' })).toHaveAttribute(
      'src',
      'http://example.test/media/source-102.jpg',
    );
  });

  // E21-16 W3/BR-05: zero-extent bbox must not enter FaceThumbnail; show labelled unavailable.
  it('does not render FaceThumbnail for a zero-extent bbox', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-zero-bbox',
          media_id: 200,
          similarity: 0.9,
          confidence: 0.95,
          thumb_url: null,
          media_url: 'http://example.test/media/label-zero.jpg',
          bbox: { x: 0, y: 0, width: 0, height: 0 },
        },
      ]),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchClusterMembers).toHaveBeenCalledWith('panel-cluster-id');
    });

    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
    expect(screen.getByText('No image')).toBeInTheDocument();
    const unavailable = screen.getByRole('img', { name: 'Face to label — image unavailable' });
    expect(unavailable).toBeInTheDocument();
    expect(unavailable).toHaveClass('acx-cluster-labeling-panel__face-unavailable');
  });

  it('renders FaceThumbnail for a positive-extent bbox when no dedicated thumb exists', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue(
      makeClusterMembersResponse([
        {
          identity_id: 'identity-positive-bbox',
          media_id: 201,
          similarity: 0.9,
          confidence: 0.95,
          thumb_url: null,
          media_url: 'http://example.test/media/label-positive.jpg',
          bbox: { x: 5, y: 7, width: 30, height: 36 },
        },
      ]),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchClusterMembers).toHaveBeenCalledWith('panel-cluster-id');
    });

    expect(container.querySelector('.acx-face-thumbnail')).not.toBeNull();
    expect(screen.queryByText('No image')).not.toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Face to label' })).toHaveAttribute(
      'src',
      'http://example.test/media/label-positive.jpg',
    );
  });

  it('renders loading state while members query is pending', () => {
    vi.mocked(fetchClusterMembers).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          void resolve;
        }),
    );

    renderPanel();

    expect(screen.getByText('Loading faces...')).toBeInTheDocument();
  });

  it('shows timeout error inline with alert role', async () => {
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(new Error('save request timed out'));

    renderPanel();

    await selectOrCreateName('Pewter Hollow');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Save is taking too long. Please try again.');
  });

  it('shows network error inline with alert role', async () => {
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(new Error('Failed to fetch'));

    renderPanel();

    await selectOrCreateName('Pewter Hollow');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Network error. Please check your connection and try again.');
  });

  it('shows projection-not-ready error inline with alert role', async () => {
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(
      new Error(
        'Request to /recognition/clusters/panel-cluster-id failed (409): {"code":"projection_not_ready","message":"Local projection is not ready for curation yet. Retry sync and try again."}',
      ),
    );

    renderPanel();

    await selectOrCreateName('Pewter Hollow');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Local sync is still catching up. Retry sync before editing labels.');
  });

  it('dismisses duplicate guard on Cancel and keeps editing available', async () => {
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse());

    renderPanel();

    await selectOrCreateName('Slate Willow');

    expect(await screen.findByText(/already exists/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('combobox', { name: 'Name' }));
    const searchInput = screen.getByPlaceholderText('Search people...');
    expect(searchInput).toBeEnabled();
    await userEvent.clear(searchInput);
    await userEvent.type(searchInput, 'Slate Willow Jr');
    expect(searchInput).toHaveValue('Slate Willow Jr');
  });

  it('keeps input editable while save is pending', async () => {
    let resolveSave: (() => void) | null = null;
    vi.mocked(updateClusterLabel).mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveSave = resolve;
        }),
    );

    renderPanel();

    await selectOrCreateName('Pewter Hollow');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
    await userEvent.click(screen.getByRole('combobox', { name: 'Name' }));
    expect(screen.getByPlaceholderText('Search people...')).not.toBeDisabled();

    await act(async () => {
      resolveSave?.();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    });
  });

  it('announces roster degraded state when roster query errors (A11Y-24)', async () => {
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [] as const,
        isLoading: false,
        isError: true,
        isSuccess: false,
        status: 'error',
        error: new Error('roster unavailable'),
        refetch: vi.fn(),
      }),
    );

    renderPanel();

    expect(await screen.findByText('People list unavailable; showing labeled clusters only.')).toBeInTheDocument();
  });

  it('announces roster loading and empty states (A11Y-24 / FIX-7)', async () => {
    // Predicted first failure: loading/empty strings not announced in live region
    // Cast: createMockQuery's success-shaped defaults disagree with loading flags.
    vi.mocked(useRosterEntries).mockReturnValue(
      {
        data: [],
        isLoading: true,
        isError: false,
        isSuccess: false,
        isPending: true,
        status: 'pending',
        fetchStatus: 'fetching',
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof useRosterEntries>,
    );

    const { rerender, queryClient } = renderPanel();

    // Multiple status regions exist (result count + show-all announce).
    expect(screen.getByText('Loading people…')).toHaveAttribute('role', 'status');

    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        isSuccess: true,
        status: 'success',
        refetch: vi.fn(),
      }),
    );
    rerender(
      <QueryClientProvider client={queryClient}>
        <ClusterLabelingPanel clusterId="panel-cluster-id" onClose={() => undefined} onLabel={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('No naming options available.')).toBeInTheDocument();
  });

  it('resets guard/input/banner when clusterId changes (FIX-4)', async () => {
    // Predicted first failure: armed guard from cluster A remains after switching to B
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse());

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <ClusterLabelingPanel clusterId="panel-cluster-id" onClose={() => undefined} onLabel={vi.fn()} />
      </QueryClientProvider>,
    );

    await selectOrCreateName('Slate Willow');
    expect(await screen.findByText(/already exists/)).toBeInTheDocument();

    rerender(
      <QueryClientProvider client={queryClient}>
        <ClusterLabelingPanel clusterId="other-cluster-id" onClose={() => undefined} onLabel={vi.fn()} />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
    });
    // Cleared input shows the empty-state placeholder on the combobox trigger.
    expect(screen.getByRole('combobox', { name: 'Name' })).toHaveTextContent(/Enter name/i);
  });

  it('arms guard from remote exact match when local collision set is empty (FIX-8)', async () => {
    // Predicted first failure: empty local set → silent create without guard
    // Union query uses limit:20 (empty); submit-time remote lookup uses limit:10 (hit).
    vi.mocked(listRecognitionClusters).mockImplementation((params?: { limit?: number }) => {
      if (params?.limit === 10) {
        return Promise.resolve(makeClusterListResponse([duplicateClusterMatch]));
      }
      return Promise.resolve(makeClusterListResponse([]));
    });

    renderPanel();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, 'Slate Willow');
    // Create free-text path (no option select) so local collisions stay empty until remote.
    const createButton = screen.queryByRole('button', { name: /Create "/i });
    if (createButton) {
      await user.click(createButton);
    }
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByText('A name matching "Slate Willow" already exists. Choose how to proceed.'),
    ).toBeInTheDocument();
    expect(updateClusterLabel).not.toHaveBeenCalled();
    expect(mergeCluster).not.toHaveBeenCalled();
  });

  it('reserved machine-shaped input is rejected before remote guard runs (BR-46)', async () => {
    const machineDuplicate = {
      ...duplicateClusterMatch,
      id: 'machine-target-id',
      label: 'cluster-auto-1',
      identity_count: 3,
    };
    vi.mocked(listRecognitionClusters).mockImplementation((params?: { limit?: number }) => {
      if (params?.limit === 10) {
        return Promise.resolve(makeClusterListResponse([machineDuplicate]));
      }
      return Promise.resolve(makeClusterListResponse([]));
    });

    renderPanel();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, 'cluster-auto-1');
    const createButton = screen.queryByRole('button', { name: /Create "/i });
    if (createButton) {
      await user.click(createButton);
    }
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByRole('alert'),
    ).toHaveTextContent(
      'This label format is reserved for automatic cluster IDs. Choose a descriptive name.',
    );
    expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
    expect(updateClusterLabel).not.toHaveBeenCalled();
    expect(mergeCluster).not.toHaveBeenCalled();
    expect(
      vi.mocked(listRecognitionClusters).mock.calls.some((call) => call[0]?.limit === 10),
    ).toBe(false);
  });

  it('remote guard collides on machine-shaped label via case-insensitive raw equality (BR-50 / BR-42)', async () => {
    // Cluster-Auto-1 passes isHumanLabeledTarget (uppercase fails MACHINE_RE; non-hex fails HEX_RE)
    // while the remote row is lowercase cluster-auto-1 — raw equality must still arm the guard.
    // BR-58 / BR-66: collision warning stays, but merge affordance AND outcome-sample copy are
    // suppressed for machine-labeled targets (copy must not advertise a merge the button withholds).
    const machineDuplicate = {
      ...duplicateClusterMatch,
      id: 'machine-target-id',
      label: 'cluster-auto-1',
      identity_count: 3,
    };
    vi.mocked(listRecognitionClusters).mockImplementation((params?: { limit?: number }) => {
      if (params?.limit === 10) {
        return Promise.resolve(makeClusterListResponse([machineDuplicate]));
      }
      return Promise.resolve(makeClusterListResponse([]));
    });

    renderPanel();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, 'Cluster-Auto-1');
    const createButton = screen.queryByRole('button', { name: /Create "/i });
    if (createButton) {
      await user.click(createButton);
    }
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByText('A name matching "Cluster-Auto-1" already exists. Choose how to proceed.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Merge target: cluster "cluster-auto-1"/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Merge into cluster/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rename anyway' })).toBeInTheDocument();
    expect(updateClusterLabel).not.toHaveBeenCalled();
    expect(mergeCluster).not.toHaveBeenCalled();
  });

  it('BR-46 / BR-66: human-labeled merge target offers copy + clickable merge (control)', async () => {
    // Predicted first failure (pre B): cluster.label.toLowerCase() throws on null → catch fail-open
    // BR-58/BR-66 control: human-labeled collision offers merge copy + button; click closes oracle gap.
    const nullLabeledRow = {
      ...duplicateClusterMatch,
      id: 'null-label-cluster',
      label: null as string | null,
      identity_count: 2,
    };
    const realMatch = {
      ...duplicateClusterMatch,
      id: 'real-match-id',
      label: 'Pat Rivera',
      identity_count: 7,
    };
    vi.mocked(listRecognitionClusters).mockImplementation((params?: { limit?: number }) => {
      if (params?.limit === 10) {
        return Promise.resolve(makeClusterListResponse([nullLabeledRow, realMatch]));
      }
      return Promise.resolve(makeClusterListResponse([]));
    });

    renderPanel();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, 'Pat Rivera');
    const createButton = screen.queryByRole('button', { name: /Create "/i });
    if (createButton) {
      await user.click(createButton);
    }
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByText('A name matching "Pat Rivera" already exists. Choose how to proceed.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Merge target: cluster "Pat Rivera"/)).toBeInTheDocument();
    const mergeButton = screen.getByRole('button', { name: 'Merge into cluster "Pat Rivera"' });
    expect(mergeButton).toBeInTheDocument();
    expect(updateClusterLabel).not.toHaveBeenCalled();
    expect(mergeCluster).not.toHaveBeenCalled();

    await user.click(mergeButton);
    await waitFor(() => {
      expect(mergeCluster).toHaveBeenCalledWith('panel-cluster-id', 'real-match-id', 'Pat Rivera');
    });
  });

  it('BR-46: remote guard with only a null-labeled row resolves to no collision', async () => {
    // Null-only labeled_only hit must not arm the guard. Oracle: remote guard ran (limit:10)
    // and save completed via the normal no-collision path (updateClusterLabel with typed label).
    const nullLabeledRow = {
      ...duplicateClusterMatch,
      id: 'null-only-cluster',
      label: null as string | null,
      identity_count: 1,
    };
    const listMock = vi.mocked(listRecognitionClusters);
    listMock.mockImplementation((params?: { limit?: number }) => {
      if (params?.limit === 10) {
        return Promise.resolve(makeClusterListResponse([nullLabeledRow]));
      }
      return Promise.resolve(makeClusterListResponse([]));
    });

    renderPanel();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, 'Unique Name Zq');
    const createButton = screen.queryByRole('button', { name: /Create "/i });
    if (createButton) {
      await user.click(createButton);
    }
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(listMock.mock.calls.some((call) => call[0]?.limit === 10 && call[0]?.labeled_only === true)).toBe(
        true,
      );
      expect(updateClusterLabel).toHaveBeenCalledWith(
        'panel-cluster-id',
        'Unique Name Zq',
        expect.any(AbortSignal),
      );
    });
    expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('BR-46: reserved machine-shaped label is rejected before remote guard', async () => {
    // Predicted first failure (pre C): save reaches remote guard / update without reserved inline error
    const listMock = vi.mocked(listRecognitionClusters);
    listMock.mockImplementation((params?: { limit?: number }) => {
      if (params?.limit === 10) {
        return Promise.resolve(makeClusterListResponse([duplicateClusterMatch]));
      }
      return Promise.resolve(makeClusterListResponse([]));
    });

    renderPanel();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, 'cluster-1a2b3c4d');
    const createButton = screen.queryByRole('button', { name: /Create "/i });
    if (createButton) {
      await user.click(createButton);
    }
    // Snapshot remote-guard-shaped calls before Save (union query uses limit:20).
    const remoteGuardCallsBefore = listMock.mock.calls.filter((call) => call[0]?.limit === 10).length;

    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByRole('alert'),
    ).toHaveTextContent(
      'This label format is reserved for automatic cluster IDs. Choose a descriptive name.',
    );
    expect(updateClusterLabel).not.toHaveBeenCalled();
    expect(mergeCluster).not.toHaveBeenCalled();
    expect(listMock.mock.calls.filter((call) => call[0]?.limit === 10).length).toBe(
      remoteGuardCallsBefore,
    );
  });

  it('BR-46: human label Cluster-Dad proceeds past reserved validation to save', async () => {
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse([]));

    renderPanel();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, 'Cluster-Dad');
    const createButton = screen.queryByRole('button', { name: /Create "/i });
    if (createButton) {
      await user.click(createButton);
    }
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(updateClusterLabel).toHaveBeenCalledWith(
        'panel-cluster-id',
        'Cluster-Dad',
        expect.any(AbortSignal),
      );
    });
    expect(screen.queryByText(/reserved for automatic cluster IDs/i)).not.toBeInTheDocument();
  });

  it('person+cluster same name still offers named merge into the cluster (PR-18 / FIX-9)', async () => {
    // Predicted first failure: person-preferred dedupe hides cluster so merge not offered
    vi.mocked(listRecognitionClusters).mockResolvedValue(
      makeClusterListResponse([
        {
          ...duplicateClusterMatch,
          id: 'cluster-alice',
          label: 'Alice',
          identity_count: 6,
        },
      ]),
    );
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 1,
            name: 'Alice',
            person_uuid: 'p1',
            tags: [],
            cluster_count: 0,
            clusters: [],
            queue_memberships: [],
            updated_at: '',
            source_version: 0,
            projection_status: 'current',
            projection_refreshed_at: null,
          },
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    renderPanel();

    await selectOrCreateName('Alice');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Merge into cluster "Alice"' })).toBeInTheDocument();
    expect(screen.getByText(/Merge target: cluster "Alice"/)).toBeInTheDocument();
    expect(updateClusterLabel).not.toHaveBeenCalled();
  });

  it('TRUE case-only self rename is not blocked (FIX-9)', async () => {
    // Predicted first failure: guard blocks 'self name' when cluster is 'Self Name'
    vi.mocked(listRecognitionClusters).mockResolvedValue(
      makeClusterListResponse([
        {
          ...duplicateClusterMatch,
          id: 'panel-cluster-id',
          label: 'Self Name',
        },
      ]),
    );

    renderPanel();

    const user = userEvent.setup();
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, 'self name');
    const createButton = screen.queryByRole('button', { name: /Create "/i });
    if (createButton) {
      await user.click(createButton);
    } else {
      // Combobox may set value via typing alone
    }
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(updateClusterLabel).toHaveBeenCalledWith('panel-cluster-id', 'self name', expect.any(AbortSignal));
    });
    expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
  });

  it('two same-name clusters hide merge (no unique target, PR-24 / FIX-9)', async () => {
    // Predicted first failure: merge offered against ambiguous multi-cluster collision
    vi.mocked(listRecognitionClusters).mockResolvedValue(
      makeClusterListResponse([
        {
          ...duplicateClusterMatch,
          id: 'cluster-a',
          label: 'Dup Name',
          identity_count: 3,
        },
        {
          ...duplicateClusterMatch,
          id: 'cluster-b',
          label: 'Dup Name',
          identity_count: 4,
        },
      ]),
    );

    renderPanel();

    await selectOrCreateName('Dup Name');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Merge into cluster/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rename anyway' })).toBeInTheDocument();
  });

  it('typed free-text Save arms guard with merge when local collision is loaded (FIX-9)', async () => {
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse());

    renderPanel();

    const user = userEvent.setup();
    // Type into combobox without selecting the option — exercise handleSubmit free-text path.
    await user.click(await screen.findByRole('combobox', { name: 'Name' }));
    const search = screen.getByPlaceholderText('Search people...');
    await user.clear(search);
    await user.type(search, 'Slate Willow');
    // Wait for labeled clusters query to populate collisions
    await waitFor(() => expect(listRecognitionClusters).toHaveBeenCalled());
    // Escape/close list and save typed value
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByText('A name matching "Slate Willow" already exists. Choose how to proceed.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Merge into cluster "Slate Willow"' })).toBeInTheDocument();
    expect(updateClusterLabel).not.toHaveBeenCalled();
  });
});
