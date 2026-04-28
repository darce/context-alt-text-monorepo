import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ClusterLabelingPanel } from '../ClusterLabelingPanel';
import {
  fetchClusterMembers,
  listRecognitionClusters,
  mergeCluster,
  updateClusterLabel,
} from '../../../../api/recognition';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../../test-utils/mockHooks';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, value: string) => text.replace('%s', value),
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

const makeClusterListResponse = (clusters = [duplicateClusterMatch]) => ({
  clusters,
  limit: 10,
  total: clusters.length,
  truncated: false,
});

const makeClusterMembersResponse = (members = []) => ({
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
      moved_identity_ids: [],
      target_identity_count: 10,
    });
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
    await user.type(screen.getByPlaceholderText('Search people...'), name);
    await user.click(screen.getByRole('button', { name: `Create "${name}"` }));
  };

  it('surfaces an inline Is this prompt and merges on Yes for duplicate labels', async () => {
    const onLabel = vi.fn();
    const listRecognitionClustersMock = vi.mocked(listRecognitionClusters);
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(
      new Error('Request to /recognition/clusters/source-cluster-id failed (409): conflict'),
    );
    listRecognitionClustersMock.mockResolvedValue(makeClusterListResponse());

    renderPanel(onLabel);

    await selectOrCreateName('Maria Correonero');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Is this Maria Correonero?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No' })).toBeInTheDocument();
    expect(updateClusterLabel).toHaveBeenCalledWith('source-cluster-id', 'Maria Correonero', expect.any(AbortSignal));

    await userEvent.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(mergeCluster).toHaveBeenCalledWith('source-cluster-id', 'target-cluster-id', 'Maria Correonero');
    });
    await waitFor(() => {
      expect(onLabel).toHaveBeenCalledWith('Maria Correonero');
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
    expect(listRecognitionClusters).not.toHaveBeenCalled();
    expect(mergeCluster).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(onLabel).toHaveBeenCalledWith('A New Person');
    });
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

  it('dismisses duplicate prompt on No and keeps editing available', async () => {
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(
      new Error('Request to /recognition/clusters/source-cluster-id failed (409): conflict'),
    );
    vi.mocked(listRecognitionClusters).mockResolvedValue(makeClusterListResponse());

    renderPanel();

    await selectOrCreateName('Maria Correonero');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Is this Maria Correonero?')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'No' }));

    await waitFor(() => {
      expect(screen.queryByText('Is this Maria Correonero?')).not.toBeInTheDocument();
    });

    await userEvent.click(screen.getByRole('combobox', { name: 'Name' }));
    const searchInput = screen.getByPlaceholderText('Search people...');
    expect(searchInput).toBeEnabled();
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
});
