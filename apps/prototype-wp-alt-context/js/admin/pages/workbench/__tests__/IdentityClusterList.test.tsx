import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
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

// Mock EventSource for useClusterEvents
class MockEventSource {
  onmessage: any = null;
  onerror: any = null;
  close = vi.fn();
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  constructor(_url: string) {}
}

const setupMocks = () => {
  // Mock AltContextAdmin config
  (window as any).AltContextAdmin = {
    nonce: 'test-nonce',
    endpoints: {
      recognition: 'http://localhost:8000',
      recognitionClusters: 'http://localhost:8000/clusters',
      workbenchFaceClusters: 'http://localhost:8000/clusters',
      workbenchRecognitionClusters: 'http://localhost:8000/clusters',
      workbenchRecognitionReassignIdentity: 'http://localhost:8000/reassign-identity',
      recognitionRevertMerge: 'http://localhost:8000/revert-merge',
      workbenchRecognitionRevertMerge: 'http://localhost:8000/revert-merge',
      workbenchRecognitionCreateClusterForIdentity: 'http://localhost:8000/create-for-identity',
      recognitionFaceSuggestions: 'http://localhost:8000/suggestions',
      workbenchRecognitionFaceSuggestions: 'http://localhost:8000/suggestions',
    },
    tenant_id: 'test-tenant',
  };

  window.EventSource = MockEventSource as any;
};

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
  identity_id: 'identity-1',
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
    setupMocks();
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
    fireEvent.change(input, { target: { value: 'New Label' } });
    await waitFor(() => expect(input).toHaveValue('New Label'));
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() =>
      expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-1', 'New Label', expect.anything()),
    );

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
    fireEvent.change(input, { target: { value: 'Person A' } });
    await waitFor(() => expect(input).toHaveValue('Person A'));
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() =>
      expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-auto', 'Person A', expect.anything()),
    );

    const updated = client.getQueryData<MediaIdentitiesResponse>(['media-identities', [1]]);
    expect(updated?.identities_by_media['1'][0].cluster_label).toBe('Person A');
    expect(updated?.identities_by_media['1'][0].is_auto_label).toBe(false);
  });

  it('shows identity suggestions in the overlay', async () => {
    (api.fetchIdentitySuggestions as Mock).mockResolvedValueOnce({
      matches: [
        {
          cluster_id: 'cluster-suggested',
          label: 'Ada Lovelace',
          similarity: 0.92,
          identity_count: 3,
        },
      ],
    });

    const { user } = renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);

    await user.click(screen.getByRole('button', { name: /edit label/i }));
    const input = await screen.findByRole('combobox');
    fireEvent.change(input, { target: { value: 'Ada' } });

    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument();
    expect(api.listRecognitionClusters).not.toHaveBeenCalled();
  });

  it('pages cluster lookup when saving to an existing label', async () => {
    const firstPage = Array.from({ length: 500 }, (_, index) => ({
      id: `cluster-${index}`,
      label: `Label ${index}`,
      identity_count: 1,
    }));
    const secondPage = [{ id: 'cluster-500', label: 'Erin McCleod', identity_count: 1 }];

    (api.listRecognitionClusters as Mock).mockResolvedValueOnce(firstPage).mockResolvedValueOnce(secondPage);
    (api.mergeCluster as Mock).mockResolvedValue({
      source_id: 'cluster-1',
      source_label: 'Cluster 1',
      target_id: 'cluster-500',
      target_label: 'Erin McCleod',
      identities_moved: 1,
      moved_identity_ids: ['identity-1'],
      target_identity_count: 2,
    });
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
    fireEvent.change(input, { target: { value: 'Erin McCleod' } });
    await waitFor(() => expect(input).toHaveValue('Erin McCleod'));
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() =>
      expect(api.listRecognitionClusters).toHaveBeenCalledWith(
        { limit: 500, offset: 0, labeled_only: true },
        expect.anything(),
      ),
    );
    await waitFor(() =>
      expect(api.listRecognitionClusters).toHaveBeenCalledWith(
        { limit: 500, offset: 500, labeled_only: true },
        expect.anything(),
      ),
    );
    await waitFor(() =>
      expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'cluster-500', 'Erin McCleod', expect.anything()),
    );
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
    fireEvent.change(input, { target: { value: 'Existing Label' } });
    await waitFor(() => expect(input).toHaveValue('Existing Label'));
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() =>
      expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'target-cluster', 'Existing Label', expect.anything()),
    );
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
    fireEvent.change(input, { target: { value: 'Existing Label' } });
    await waitFor(() => expect(input).toHaveValue('Existing Label'));
    await user.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() =>
      expect(api.mergeCluster).toHaveBeenCalledWith('cluster-1', 'target-cluster', 'Existing Label', expect.anything()),
    );

    const closeButton = await screen.findByRole('button', { name: /Close/i });
    await user.click(closeButton);

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

  it('renders face thumbnail when media_url is provided', () => {
    const identityWithMediaUrl = {
      ...baseIdentity,
      media_url: 'https://example.com/photo.jpg',
    };

    renderWithClient(<IdentityClusterList identities={[identityWithMediaUrl]} mediaId={1} />);
    const image = screen.getByRole('img', { name: /detected identity thumbnail/i });
    expect(image).toHaveAttribute('src', 'https://example.com/photo.jpg');
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

  it('allows unlinking an identity (wrong person) only for singletons', async () => {
    (api.reassignClusterIdentity as Mock).mockResolvedValue({});
    vi.spyOn(window, 'confirm').mockImplementation(() => true);

    // 1. Singleton case - button should be visible
    const { client, user, unmount } = renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity],
      },
    };
    client.setQueryData(['media-identities', [1]], cacheData);

    const wrongPersonButton = await screen.findByText('Wrong person', { selector: 'button' });
    expect(wrongPersonButton).toBeInTheDocument();

    await user.click(wrongPersonButton);
    await waitFor(() =>
      expect(api.reassignClusterIdentity).toHaveBeenCalledWith({
        identityId: 'identity-1',
        targetClusterId: null,
        blockFromCluster: true,
      }),
    );
    unmount();

    // 2. Multi-member case - button should be hidden
    const member1 = { ...baseIdentity, identity_id: '1', cluster_id: 'c1', cluster_label: 'Startrek' };
    const member2 = { ...baseIdentity, identity_id: '2', cluster_id: 'c1', cluster_label: 'Startrek' };

    // We need to mock the API return for listClusters or rely on the component using the updated identities
    // The component groups identities by cluster_id.
    // However, IdentityClusterList takes `identities` prop.
    renderWithClient(<IdentityClusterList identities={[member1, member2]} mediaId={1} />);

    expect(screen.queryByRole('button', { name: /wrong person/i })).not.toBeInTheDocument();
  });

  it('allows splitting a cluster', async () => {
    (api.splitCluster as Mock).mockResolvedValue({ moved_count: 5 });

    const secondIdentity = {
      ...baseIdentity,
      identity_id: 'identity-2',
      media_id: 2,
    };

    const { client, user } = renderWithClient(
      <IdentityClusterList identities={[baseIdentity, secondIdentity]} mediaId={1} />,
    );
    const cacheData: MediaIdentitiesResponse = {
      identities_by_media: {
        '1': [baseIdentity, secondIdentity],
      },
    };
    client.setQueryData(['media-identities', [1]], cacheData);

    await user.click(screen.getByRole('button', { name: /split cluster/i }));

    await user.click(await screen.findByRole('button', { name: /use face from media #1/i }));

    // Split always forces 2 clusters to guarantee a split happens
    await waitFor(() =>
      expect(api.splitCluster).toHaveBeenCalledWith('cluster-1', {
        nClusters: 2,
        anchorIdentityId: 'identity-1',
        splitMode: 'forced',
        mode: 'sync',
      }),
    );
  });
});
