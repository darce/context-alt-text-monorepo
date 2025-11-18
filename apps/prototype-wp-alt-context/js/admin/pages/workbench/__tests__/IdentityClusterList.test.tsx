import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { IdentityClusterList } from '../IdentityClusterList';
import * as api from '../../../api/recognitionApi';

vi.mock('../../../api/recognitionApi', () => ({
  mergeCluster: vi.fn(),
  updateClusterLabel: vi.fn(),
}));

const renderWithClient = (ui: React.ReactElement) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
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
  it('renders placeholder when no identities exist', () => {
    renderWithClient(<IdentityClusterList identities={[]} mediaId={1} />);
    expect(screen.getByText(/No identities detected yet/i)).toBeInTheDocument();
  });

  it('allows renaming a manually labeled cluster', async () => {
    (api.updateClusterLabel as vi.Mock).mockResolvedValue({});
    renderWithClient(<IdentityClusterList identities={[baseIdentity]} mediaId={1} />);

    fireEvent.click(screen.getByRole('button', { name: /edit label/i }));
    const input = screen.getByPlaceholderText(/enter a name/i);
    fireEvent.change(input, { target: { value: 'New Label' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => expect(api.updateClusterLabel).toHaveBeenCalledWith('cluster-1', 'New Label'));
  });

  it('merges auto-labeled clusters via mergeCluster', async () => {
    (api.mergeCluster as vi.Mock).mockResolvedValue({});
    const autoIdentity = {
      ...baseIdentity,
      id: 'auto-1',
      cluster_id: 'cluster-auto',
      cluster_label: 'cluster-auto',
      is_auto_label: true,
    };

    renderWithClient(<IdentityClusterList identities={[autoIdentity]} mediaId={1} />);

    fireEvent.click(screen.getByRole('button', { name: /Name this person/i }));
    const input = screen.getByPlaceholderText(/enter a name/i);
    fireEvent.change(input, { target: { value: 'Person A' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/i }));

    await waitFor(() => expect(api.mergeCluster).toHaveBeenCalledWith('cluster-auto', 'Person A'));
  });
});
