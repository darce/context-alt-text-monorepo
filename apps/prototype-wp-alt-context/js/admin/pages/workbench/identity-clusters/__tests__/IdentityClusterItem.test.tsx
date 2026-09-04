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
    atRestTotal: 80,
    atRestTruncated: true,
    isAtRestMode: true,
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

const CLUSTER_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

const member = (overrides: Partial<ClusterGroup['members'][number]> = {}): ClusterGroup['members'][number] => ({
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
  ...overrides,
});

const bobCluster = (): ClusterGroup => ({
  key: 'editable',
  clusterId: 'editable',
  label: 'bob',
  isAutoLabel: false,
  clusteringPending: false,
  members: [member()],
});

const unlabeledCluster = (overrides: Partial<ClusterGroup> = {}): ClusterGroup => ({
  key: 'unlabeled',
  clusterId: CLUSTER_ID,
  label: null,
  isAutoLabel: false,
  clusteringPending: false,
  members: [
    member({
      cluster_id: CLUSTER_ID,
      cluster_label: null,
    }),
  ],
  ...overrides,
});

const renderItem = (cluster: ClusterGroup = bobCluster(), { canMutate = true }: { canMutate?: boolean } = {}) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityClusterItem cluster={cluster} canLabel canMutate={canMutate} />
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
    expect(screen.getByRole('button', { name: /^Save name$/i })).toBeInTheDocument();
  });

  it('exact-dupe remote "bob" + typed "Bob" keeps Save (no Merge-with) — UXP-3-BR-44', async () => {
    // Remote match label exactly equals current cluster label → save-path renames (BR-40).
    // Preview must not promise Merge/Assign.
    findClusterByLabel.mockResolvedValue({
      id: 'dupe-bob',
      label: 'bob',
      identityCount: 3,
    });

    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    fireEvent.change(screen.getByPlaceholderText(/enter a name/i), { target: { value: 'Bob' } });
    await flushMatchDebounce();

    expect(findClusterByLabel).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));
    expect(screen.queryByRole('button', { name: /Merge with/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Save name$/i })).toBeInTheDocument();
  });

  it('reverting to exact label aborts in-flight match so preview stays Save — UXP-3-BR-45', async () => {
    let resolveMatch!: (value: { id: string; label: string; identityCount: number }) => void;
    const deferred = new Promise<{ id: string; label: string; identityCount: number }>((resolve) => {
      resolveMatch = resolve;
    });
    findClusterByLabel.mockImplementation((_label: string, signal?: AbortSignal) =>
      deferred.then((value) => {
        if (signal?.aborted) {
          const err = new Error('Aborted');
          err.name = 'AbortError';
          throw err;
        }
        return value;
      }),
    );

    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    const input = screen.getByPlaceholderText(/enter a name/i);
    fireEvent.change(input, { target: { value: 'Bob' } });
    await flushMatchDebounce();

    expect(findClusterByLabel).toHaveBeenCalledWith('Bob', expect.any(AbortSignal));

    // Bail to exact current label before the deferred response settles.
    fireEvent.change(input, { target: { value: 'bob' } });
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      resolveMatch({ id: 'other-bob', label: 'Bob', identityCount: 2 });
      await deferred;
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByRole('button', { name: /Merge with/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Save name$/i })).toBeInTheDocument();
  });
});

describe('IdentityClusterItem Library save copy (UXW2-3-R1-16i)', () => {
  afterEach(() => {
    cleanup();
  });

  it('default Library row commit button is Save name (UXW2-3-R1-16i)', () => {
    renderItem();
    fireEvent.click(screen.getByRole('button', { name: 'bob' }));
    expect(screen.getByRole('button', { name: 'Save name' })).toBeInTheDocument();
  });
});

describe('IdentityClusterItem at-rest hint wiring (REV2-01)', () => {
  afterEach(() => {
    cleanup();
  });

  it('passes at-rest truncation props through so the labelled editor describes the truncated page', () => {
    renderItem();

    fireEvent.click(screen.getByRole('button', { name: 'bob' }));

    const hint = screen.getByText(/Showing \d+ of 80 labels/);
    expect(hint).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Person name' })).toHaveAccessibleDescription(
      hint.textContent ?? '',
    );
  });
});

describe('IdentityClusterItem unlabeled copy (UXW2-4-R7E-02)', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders Unnamed person when the cluster has a UUID and no human label', () => {
    renderItem(unlabeledCluster());

    expect(screen.getByRole('button', { name: 'Unnamed person' })).toBeInTheDocument();
    expect(screen.queryByText(/cluster-[0-9a-f]{8}/i)).not.toBeInTheDocument();
  });

  it('does not render auto-shape cluster-* as a person name', () => {
    renderItem(
      unlabeledCluster({
        label: 'cluster-7',
        members: [member({ cluster_id: CLUSTER_ID, cluster_label: 'cluster-7' })],
      }),
    );

    expect(screen.queryByRole('button', { name: 'cluster-7' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unnamed person' })).toBeInTheDocument();
  });
});

describe('IdentityClusterItem mutation affordance gates (WBUX6-W3-L6-02 / WBUX6-W3-L6-03)', () => {
  afterEach(() => {
    cleanup();
  });

  const splitButton = () => screen.queryByRole('button', { name: /split group/i });
  const removeButton = () => screen.queryByRole('button', { name: /remove from group/i });

  // A group whose own clusterId is null but whose member still carries one:
  // getEditableClusterId falls back to the member, so the row stays editable
  // (canEdit) and only the split gate observes the missing group id. This is the
  // only fixture shape that isolates `Boolean(cluster.clusterId)` from canEdit.
  const memberOnlyClusterId = (): ClusterGroup => ({
    key: 'member-only',
    clusterId: null,
    label: 'bob',
    isAutoLabel: false,
    clusteringPending: false,
    members: [member({ cluster_id: 'editable' })],
  });

  const twoMemberCluster = (): ClusterGroup => ({
    ...bobCluster(),
    members: [member(), member({ identity_id: 'id-2', representative_id: 'rep-2', media_id: 2 })],
  });

  it('offers Split only when the group itself carries a cluster id', () => {
    renderItem(bobCluster());
    expect(splitButton()).toBeInTheDocument();

    cleanup();

    renderItem(memberOnlyClusterId());
    // Row is still editable via the member-derived id, so the absence below is
    // the split gate, not a blanket "no actions" early return.
    expect(screen.getByRole('button', { name: /edit label/i })).toBeInTheDocument();
    expect(splitButton()).not.toBeInTheDocument();
  });

  it('offers Remove from group only for a single-member group', () => {
    renderItem(bobCluster());
    expect(removeButton()).toBeInTheDocument();

    cleanup();

    renderItem(twoMemberCluster());
    expect(screen.getByRole('button', { name: /edit label/i })).toBeInTheDocument();
    expect(removeButton()).not.toBeInTheDocument();
  });

  it('withholds both mutating affordances when canMutate is false', () => {
    renderItem(bobCluster(), { canMutate: false });

    expect(screen.getByRole('button', { name: /edit label/i })).toBeInTheDocument();
    expect(splitButton()).not.toBeInTheDocument();
    expect(removeButton()).not.toBeInTheDocument();
  });
});
