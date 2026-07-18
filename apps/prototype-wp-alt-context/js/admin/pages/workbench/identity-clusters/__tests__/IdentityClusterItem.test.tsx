import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { IdentityClusterItem } from '../IdentityClusterItem';
import type { ClusterGroup } from '../types';

const MATCH_DEBOUNCE_MS = 300;

const findClusterByLabel = vi.fn();

vi.mock('../useClusterSuggestions', () => ({
  useClusterSuggestions: () => ({
    options: [],
    isLoading: false,
    collisionsByLabel: new Map(),
    findClusterByLabel,
  }),
}));

vi.mock('../useClusterMutations', () => ({
  useClusterMutations: () => ({
    isPending: false,
    isReverting: false,
    merge: vi.fn(),
    assignToCluster: vi.fn(),
    rename: vi.fn(),
    createClusterForIdentity: vi.fn(),
    reassign: vi.fn(),
    split: vi.fn(),
    revertMerge: vi.fn(),
    rejectSuggestion: vi.fn(),
    splitGate: { disabled: false, title: undefined, 'aria-disabled': false },
  }),
}));

const bobCluster = (): ClusterGroup => ({
  key: 'editable',
  clusterId: 'editable',
  label: 'bob',
  isAutoLabel: false,
  clusteringPending: false,
  members: [
    {
      identity_id: 'id-1',
      representative_id: 'rep-1',
      media_id: 1,
      cluster_id: 'editable',
      cluster_label: 'bob',
      is_auto_label: false,
      is_pinned: false,
      bbox: { x: 0, y: 0, width: 1, height: 1 },
      confidence: 1,
      similarity: 1,
      detected_at: '',
    },
  ],
});

const renderItem = (cluster: ClusterGroup = bobCluster()) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityClusterItem cluster={cluster} canLabel canMutate />
    </QueryClientProvider>,
  );
};

const flushMatchDebounce = async () => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(MATCH_DEBOUNCE_MS);
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('IdentityClusterItem proactive match (UXP-3-BR-39)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    findClusterByLabel.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('bob→Bob with a different Bob cluster arms Merge-with preview', async () => {
    findClusterByLabel.mockResolvedValue({
      id: 'other-bob',
      label: 'Bob',
      identityCount: 2,
    });

    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    fireEvent.change(screen.getByPlaceholderText(/enter a name/i), { target: { value: 'Bob' } });
    await flushMatchDebounce();

    expect(findClusterByLabel).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
    expect(screen.getByRole('button', { name: /Merge with Bob/i })).toBeInTheDocument();
  });

  it('exact same label does not arm proactive match / Merge-with preview', async () => {
    findClusterByLabel.mockResolvedValue({
      id: 'other-bob',
      label: 'bob',
      identityCount: 2,
    });

    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    // Re-assert exact current label (startEditing already seeds it).
    fireEvent.change(screen.getByPlaceholderText(/enter a name/i), { target: { value: 'bob' } });
    await flushMatchDebounce();

    expect(findClusterByLabel).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /Merge with/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Save$/i })).toBeInTheDocument();
  });
});
