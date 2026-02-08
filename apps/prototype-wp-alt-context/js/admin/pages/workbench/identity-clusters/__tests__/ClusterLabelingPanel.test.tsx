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
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(
      new Error('Request to /recognition/clusters/source-cluster-id failed (409): conflict'),
    );
    listRecognitionClustersMock.mockResolvedValue([duplicateClusterMatch]);

    renderPanel(onLabel);

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Name'), 'Maria Correonero');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Is this Maria Correonero?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No' })).toBeInTheDocument();
    expect(updateClusterLabel).toHaveBeenCalledWith('source-cluster-id', 'Maria Correonero', expect.any(AbortSignal));

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

    renderPanel(onLabel);

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Name'), 'A New Person');
    await user.click(screen.getByRole('button', { name: 'Save' }));

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

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Name'), 'Coral Osborne');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Save is taking too long. Please try again.');
  });

  it('shows network error inline with alert role', async () => {
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(new Error('Failed to fetch'));

    renderPanel();

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Name'), 'Coral Osborne');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Network error. Please check your connection and try again.');
  });

  it('dismisses duplicate prompt on No and keeps editing available', async () => {
    vi.mocked(updateClusterLabel).mockRejectedValueOnce(
      new Error('Request to /recognition/clusters/source-cluster-id failed (409): conflict'),
    );
    vi.mocked(listRecognitionClusters).mockResolvedValue([duplicateClusterMatch]);

    renderPanel();

    const user = userEvent.setup();
    const input = await screen.findByLabelText('Name');
    await user.type(input, 'Maria Correonero');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Is this Maria Correonero?')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'No' }));

    await waitFor(() => {
      expect(screen.queryByText('Is this Maria Correonero?')).not.toBeInTheDocument();
    });

    expect(input).toBeEnabled();
    await user.type(input, ' Jr');
    expect(input).toHaveValue('Maria Correonero Jr');
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

    const user = userEvent.setup();
    const input = await screen.findByLabelText('Name');
    await user.type(input, 'Coral Osborne');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
    expect(input).not.toBeDisabled();

    await act(async () => {
      resolveSave?.();
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
    });
  });
});
