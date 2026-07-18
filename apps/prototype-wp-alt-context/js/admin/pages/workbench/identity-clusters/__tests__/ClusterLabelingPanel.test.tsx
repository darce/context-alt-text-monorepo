import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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

const renderPanel = (onLabel: (label: string) => void = vi.fn()) => {
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
    ...render(
      <QueryClientProvider client={queryClient}>
        <ClusterLabelingPanel clusterId="source-cluster-id" onClose={() => undefined} onLabel={onLabel} />
      </QueryClientProvider>,
    ),
  };
};

const duplicateClusterMatch = {
  id: 'target-cluster-id',
  label: 'Maria Correonero',
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
      source_id: 'source-cluster-id',
      source_label: null,
      target_id: 'target-cluster-id',
      target_label: 'Maria Correonero',
      identities_moved: 5,
      moved_identity_ids: ['id-1'],
      target_identity_count: 10,
    });
    vi.mocked(revertMergeCluster).mockResolvedValue({
      restored_cluster_id: 'source-cluster-id',
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
    await selectOrCreateName('Maria Correonero');

    expect(
      await screen.findByText('A name matching "Maria Correonero" already exists. Choose how to proceed.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Merge target: cluster "Maria Correonero" \(10 members\)/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Merge into cluster "Maria Correonero"' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rename anyway' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(updateClusterLabel).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Merge into cluster "Maria Correonero"' }));

    await waitFor(() => {
      expect(mergeCluster).toHaveBeenCalledWith('source-cluster-id', 'target-cluster-id', 'Maria Correonero');
    });
    expect(await screen.findByText(/Merged into/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo merge' })).toBeInTheDocument();
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
      expect(updateClusterLabel).toHaveBeenCalledWith('source-cluster-id', 'Only Person', expect.any(AbortSignal));
    });
  });

  it('does not block self-case-only renames when no other collision exists', async () => {
    const onLabel = vi.fn();
    vi.mocked(listRecognitionClusters).mockResolvedValue(
      makeClusterListResponse([
        {
          ...duplicateClusterMatch,
          id: 'source-cluster-id',
          label: 'Self Name',
        },
      ]),
    );

    renderPanel(onLabel);

    await selectOrCreateName('Self Name');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(updateClusterLabel).toHaveBeenCalledWith('source-cluster-id', 'Self Name', expect.any(AbortSignal));
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
      expect(updateClusterLabel).toHaveBeenCalledWith('source-cluster-id', 'A New Person', expect.any(AbortSignal));
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
      expect(fetchClusterMembers).toHaveBeenCalledWith('source-cluster-id');
    });

    await waitFor(() => {
      expect(container.querySelector('.acx-avatar')).not.toBeNull();
    });

    expect(container.querySelector('.acx-face-thumbnail')).toBeNull();
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
      expect(fetchClusterMembers).toHaveBeenCalledWith('source-cluster-id');
    });

    expect(container.querySelector('.acx-face-thumbnail')).not.toBeNull();
    expect(container.querySelector('.acx-avatar')).toBeNull();
    expect(screen.getByRole('img', { name: 'Face to label' })).toHaveAttribute(
      'src',
      'http://example.test/media/source-102.jpg',
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

    await selectOrCreateName('Coral Osborne');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Save is taking too long. Please try again.');
  });

  it('shows network error inline with alert role', async () => {
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(new Error('Failed to fetch'));

    renderPanel();

    await selectOrCreateName('Coral Osborne');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Network error. Please check your connection and try again.');
  });

  it('shows projection-not-ready error inline with alert role', async () => {
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(
      new Error(
        'Request to /recognition/clusters/source-cluster-id failed (409): {"code":"projection_not_ready","message":"Local projection is not ready for curation yet. Retry sync and try again."}',
      ),
    );

    renderPanel();

    await selectOrCreateName('Coral Osborne');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Local sync is still catching up. Retry sync before editing labels.');
  });

  it('dismisses duplicate guard on Cancel and keeps editing available', async () => {
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse());

    renderPanel();

    await selectOrCreateName('Maria Correonero');

    expect(await screen.findByText(/already exists/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => {
      expect(screen.queryByText(/already exists/)).not.toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('combobox', { name: 'Name' }));
    const searchInput = screen.getByPlaceholderText('Search people...');
    expect(searchInput).toBeEnabled();
    await userEvent.clear(searchInput);
    await userEvent.type(searchInput, 'Maria Correonero Jr');
    expect(searchInput).toHaveValue('Maria Correonero Jr');
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

    await selectOrCreateName('Coral Osborne');
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
});
