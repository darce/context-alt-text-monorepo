import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { IdentityClusterList } from '../identity-clusters';
import * as api from '../../../api/recognition';
import type { MediaIdentitiesResponse } from '../../../api/recognition';

// Mock ResizeObserver for Radix UI
window.ResizeObserver = class ResizeObserver {
  observe(): void {
    return undefined;
  }
  unobserve(): void {
    return undefined;
  }
  disconnect(): void {
    return undefined;
  }
};

// Mock PointerCapture for Radix UI
window.HTMLElement.prototype.hasPointerCapture = vi.fn();
window.HTMLElement.prototype.setPointerCapture = vi.fn();
window.HTMLElement.prototype.releasePointerCapture = vi.fn();

// Mock scrollIntoView for cmdk
window.HTMLElement.prototype.scrollIntoView = vi.fn();

vi.mock('../../../api/recognition', () => ({
  mergeCluster: vi.fn(),
  updateClusterLabel: vi.fn(),
  fetchIdentitySuggestions: vi.fn().mockResolvedValue({ matches: [] }),
  listRecognitionClusters: vi.fn().mockResolvedValue([]),
  revertMergeCluster: vi.fn(),
  reassignClusterIdentity: vi.fn(),
  splitCluster: vi.fn(),
}));

const renderWithClient = (ui: React.ReactElement) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const user = userEvent.setup();
  const utils = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { client, user, ...utils };
};

const baseIdentity = {
  id: 'identity-1',
  media_id: 1,
  cluster_id: 'cluster-1',
  cluster_label: 'Cluster 1',
  is_auto_label: false,
  bbox: { x: 0, y: 0, width: 10, height: 10 },
  confidence: 0.9,
  similarity: 0.9,
  detected_at: '',
  thumbnail_url: null,
};

describe('IdentityClusterList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders placeholder when no identities exist', () => {
    renderWithClient(<IdentityClusterList identities={[]} mediaId={1} />);
    expect(screen.getByText(/No identities detected yet/i)).toBeInTheDocument();
  });

  it('allows renaming a manually labeled cluster', async () => {
    (api.updateClusterLabel as Mock).mockResolvedValue({});
    const { client, user } = renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);

    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [
          {
            ...baseIdentity,
          },
        ],
      },
    };
    client.setQueryData(['media-identities', [1]], cacheData);

    await user.click(screen.getByRole('button', { name: /edit label/i }));
    await user.click(screen.getByRole('combobox'));
    const input = await screen.findByPlaceholderText(/enter a name/i);
    await user.type(input, 'New Label');
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-1', 'New Label'));

    const updated = client.getQueryData<MediaIdentitiesResponse>(['media-identities', [1]]);
    expect(updated?.identities_by_media['1'][0].cluster_label).toBe('New Label');
    expect(updated?.identities_by_media['1'][0].is_auto_label).toBe(false);
  });

  it('renames auto-labeled clusters to new label', async () => {
    (api.updateClusterLabel as Mock).mockResolvedValue({});
    const autoIdentity = {
      ...baseIdentity,
      id: 'auto-1',
      cluster_id: 'cluster-auto',
      cluster_label: 'cluster-auto',
      is_auto_label: true,
    };

    const { client, user } = renderWithClient(<IdentityClusterList identities={[autoIdentity]} mediaId={1} />);

    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [
          {
            ...autoIdentity,
          },
        ],
      },
    };
    client.setQueryData(['media-identities', [1]], cacheData);

    await user.click(screen.getByRole('button', { name: /Name this person/i }));
    await user.click(screen.getByRole('combobox'));
    const input = await screen.findByPlaceholderText(/enter a name/i);
    await user.type(input, 'Person A');
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-auto', 'Person A'));

    const updated = client.getQueryData<MediaIdentitiesResponse>(['media-identities', [1]]);
    expect(updated?.identities_by_media['1'][0].cluster_label).toBe('Person A');
    expect(updated?.identities_by_media['1'][0].is_auto_label).toBe(false);
  });

  it('merges into existing cluster when label matches', async () => {
    (api.mergeCluster as Mock).mockResolvedValue({
      source_id: 'cluster-1',
      source_label: 'Cluster 1',
      target_id: 'target-cluster',
      target_label: 'Existing Label',
      identities_moved: 1,
      moved_identity_ids: ['identity-1'],
      target_identity_count: 2,
    });
    // Mock existing clusters (new API)
    (api.listRecognitionClusters as Mock).mockResolvedValue([
      { id: 'target-cluster', label: 'Existing Label', identity_count: 1 },
    ]);

    // Mock window.confirm
    vi.spyOn(window, 'confirm').mockImplementation(() => true);

    const { client, user } = renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);

    // ... setup cache ...
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    client.setQueryData(['media-identities', [1]], cacheData);

    await user.click(screen.getByRole('button', { name: /edit label/i }));
    await user.click(screen.getByRole('combobox'));
    const input = await screen.findByPlaceholderText(/enter a name/i);
    await user.type(input, 'Existing Label');
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'Existing Label'));
  });

  it('shows undo when merge completes and reverts on request', async () => {
    (api.mergeCluster as Mock).mockResolvedValue({
      source_id: 'cluster-1',
      source_label: 'Cluster 1',
      target_id: 'target-cluster',
      target_label: 'Existing Label',
      identities_moved: 1,
      moved_identity_ids: ['identity-1'],
      target_identity_count: 2,
    });
    (api.revertMergeCluster as Mock).mockResolvedValue({
      restored_cluster_id: 'restored-1',
      restored_label: 'Cluster 1',
      restored_identity_count: 1,
      target_cluster_id: 'target-cluster',
      target_identity_count: 1,
    });
    // Mock existing clusters (new API)
    (api.listRecognitionClusters as Mock).mockResolvedValue([
      { id: 'target-cluster', label: 'Existing Label', identity_count: 1 },
    ]);
    vi.spyOn(window, 'confirm').mockImplementation(() => true);

    const { client, user } = renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    client.setQueryData(['media-identities', [1]], cacheData);

    await user.click(screen.getByRole('button', { name: /edit label/i }));
    await user.click(screen.getByRole('combobox'));
    const input = await screen.findByPlaceholderText(/enter a name/i);
    await user.type(input, 'Existing Label');
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'Existing Label'));

    const undoButton = await screen.findByRole('button', { name: /Undo merge/i });
    await user.click(undoButton);

    await waitFor(() =>
      expect(api.revertMergeCluster).toHaveBeenCalledWith({
        targetClusterId: 'target-cluster',
        movedIdentityIds: ['identity-1'],
        sourceLabel: 'Cluster 1',
      }),
    );
  });

  it('renders persisted thumbnails when provided', () => {
    const identityWithThumb = {
      ...baseIdentity,
      thumbnail_url: 'https://example.com/thumb.jpg',
    };

    renderWithClient(<IdentityClusterList identities={[identityWithThumb]} mediaId={1} />);
    const image = screen.getByRole('img', { name: /detected identity thumbnail/i });
    expect(image).toHaveAttribute('src', 'https://example.com/thumb.jpg');
  });

  it('allows clicking the unlabeled text to start editing', async () => {
    const unlabeled = {
      ...baseIdentity,
      cluster_label: null,
    };
    const { user } = renderWithClient(<IdentityClusterList identities={[unlabeled]} mediaId={1} />);
    await user.click(screen.getByRole('button', { name: /cluster-clust/i }));
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  it('allows unlinking an identity (wrong person)', async () => {
    (api.reassignClusterIdentity as Mock).mockResolvedValue({});
    vi.spyOn(window, 'confirm').mockImplementation(() => true);

    const { client, user } = renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    client.setQueryData(['media-identities', [1]], cacheData);

    await user.click(screen.getByRole('button', { name: /wrong person/i }));

    await waitFor(() =>
      expect(api.reassignClusterIdentity).toHaveBeenCalledWith({
        identityId: 'identity-1',
        targetClusterId: null,
      }),
    );
  });

  it('allows splitting a cluster', async () => {
    (api.splitCluster as Mock).mockResolvedValue({ moved_count: 5 });
    vi.spyOn(window, 'confirm').mockImplementation(() => true);

    const { client, user } = renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    client.setQueryData(['media-identities', [1]], cacheData);

    await user.click(screen.getByRole('button', { name: /split cluster/i }));

    // Split always forces 2 clusters to guarantee a split happens
    await waitFor(() => expect(api.splitCluster).toHaveBeenCalledWith('cluster-1', 2));
  });
});
