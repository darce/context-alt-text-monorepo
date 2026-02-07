import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ClusterLabelingPanel } from '../ClusterLabelingPanel';
import { fetchClusterMembers, listRecognitionClusters, mergeCluster, updateClusterLabel } from '../../../../api/recognition';

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

describe('ClusterLabelingPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchClusterMembers).mockResolvedValue([]);
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
  });

  it('surfaces an inline Is this prompt and merges on Yes for duplicate labels', async () => {
    const onLabel = vi.fn();
    const listRecognitionClustersMock = vi.mocked(listRecognitionClusters);
    listRecognitionClustersMock.mockResolvedValue([
      {
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
      },
    ]);

    renderPanel(onLabel);

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Name'), 'Maria Correonero');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Is this Maria Correonero?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No' })).toBeInTheDocument();
    expect(updateClusterLabel).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(mergeCluster).toHaveBeenCalledWith('source-cluster-id', 'target-cluster-id', 'Maria Correonero');
    });
    await waitFor(() => {
      expect(onLabel).toHaveBeenCalledWith('Maria Correonero');
    });
  });

  it('keeps normal save path when no matching existing label exists', async () => {
    const onLabel = vi.fn();
    vi.mocked(listRecognitionClusters).mockResolvedValue([]);

    renderPanel(onLabel);

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Name'), 'A New Person');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(updateClusterLabel).toHaveBeenCalledWith('source-cluster-id', 'A New Person');
    });
    expect(mergeCluster).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(onLabel).toHaveBeenCalledWith('A New Person');
    });
  });
});
