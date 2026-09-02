import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { IdentityClusterItem } from '../IdentityClusterItem';
import { pendingMergeTwinForCluster } from '../pendingMergeTwin';
import type { ClusterGroup } from '../types';
import type { PendingMergeSuggestion } from '../../../../api/recognition/types';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

vi.mock('../useClusterSuggestions', () => ({
  useClusterSuggestions: () => ({
    options: [],
    isLoading: false,
    collisionsByLabel: new Map(),
    findClusterByLabel: vi.fn(),
    atRestTotal: 0,
    atRestTruncated: false,
    isAtRestMode: false,
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

const UNLABELED_ID = 'cluster-b-unlabeled';
const LABELED_ID = 'cluster-a-labeled';

const member = (overrides: Partial<ClusterGroup['members'][number]> = {}): ClusterGroup['members'][number] => ({
  identity_id: 'id-1',
  representative_id: 'rep-1',
  media_id: 1,
  cluster_id: UNLABELED_ID,
  cluster_label: null,
  is_auto_label: true,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 1,
  detected_at: '',
  ...overrides,
});

const unlabeledCluster = (overrides: Partial<ClusterGroup> = {}): ClusterGroup => ({
  key: UNLABELED_ID,
  clusterId: UNLABELED_ID,
  label: null,
  isAutoLabel: true,
  clusteringPending: false,
  members: [member()],
  ...overrides,
});

const labeledCluster = (): ClusterGroup => ({
  key: LABELED_ID,
  clusterId: LABELED_ID,
  label: 'Ada Lovelace',
  isAutoLabel: false,
  clusteringPending: false,
  members: [
    member({
      cluster_id: LABELED_ID,
      cluster_label: 'Ada Lovelace',
      is_auto_label: false,
    }),
  ],
});

const mergeTwin = (overrides: Partial<{
  suggestionId: string;
  survivorLabel: string;
  onAccept: () => void;
  onReject: () => void;
  isPending: boolean;
  disabledReason: string | null;
}> = {}) => ({
  suggestionId: 'merge-1',
  survivorLabel: 'Ada Lovelace',
  onAccept: vi.fn(),
  onReject: vi.fn(),
  isPending: false,
  disabledReason: null,
  ...overrides,
});

const pendingSuggestion = (
  overrides: Partial<PendingMergeSuggestion> = {},
): PendingMergeSuggestion => ({
  id: 'merge-1',
  cluster_a_id: LABELED_ID,
  cluster_b_id: UNLABELED_ID,
  similarity: 0.91,
  status: 'pending',
  cluster_a_label: 'Ada Lovelace',
  cluster_b_label: null,
  cluster_a_identity_count: 7,
  cluster_b_identity_count: 3,
  ...overrides,
});

const renderItem = (cluster: ClusterGroup, twin?: ReturnType<typeof mergeTwin>) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityClusterItem cluster={cluster} canLabel canMutate mergeTwin={twin} />
    </QueryClientProvider>,
  );
};

describe('IdentityClusterItem twin chip (WBUX-6/C3)', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders the same-person chip on an unlabeled cluster with a labeled survivor', () => {
    renderItem(unlabeledCluster(), mergeTwin());

    const chip = screen.getByTestId('acx-identity-clusters__twin-chip');
    expect(chip).toHaveTextContent('⇢ Same person as Ada Lovelace?');
    expect(screen.getByRole('button', { name: 'Merge into Ada' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Not the same' })).toBeInTheDocument();
  });

  it('does not render the chip on a labeled cluster even when mergeTwin is passed', () => {
    renderItem(labeledCluster(), mergeTwin());

    expect(screen.queryByTestId('acx-identity-clusters__twin-chip')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Merge into Ada' })).not.toBeInTheDocument();
  });

  it('does not render the chip when mergeTwin is omitted', () => {
    renderItem(unlabeledCluster());

    expect(screen.queryByTestId('acx-identity-clusters__twin-chip')).not.toBeInTheDocument();
  });

  it('calls onAccept and onReject from the chip buttons', async () => {
    const onAccept = vi.fn();
    const onReject = vi.fn();
    const user = userEvent.setup();
    renderItem(unlabeledCluster(), mergeTwin({ onAccept, onReject }));

    await user.click(screen.getByRole('button', { name: 'Merge into Ada' }));
    await user.click(screen.getByRole('button', { name: 'Not the same' }));

    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it('disables chip buttons while pending and surfaces the reason', () => {
    renderItem(
      unlabeledCluster(),
      mergeTwin({ isPending: true, disabledReason: 'Saving merge suggestion…' }),
    );

    const accept = screen.getByRole('button', { name: 'Merge into Ada' });
    const reject = screen.getByRole('button', { name: 'Not the same' });
    expect(accept).toBeDisabled();
    expect(reject).toBeDisabled();
    expect(accept).toHaveAttribute('title', 'Saving merge suggestion…');
    expect(reject).toHaveAttribute('title', 'Saving merge suggestion…');
  });

  it.each(['Cluster-9f2', ' cluster-9f2', 'cluster_9f2'])(
    'does not render the chip when the survivor label is reserved (%j)',
    (survivorLabel) => {
      renderItem(unlabeledCluster(), mergeTwin({ survivorLabel }));

      expect(screen.queryByTestId('acx-identity-clusters__twin-chip')).not.toBeInTheDocument();
    },
  );
});

describe('pendingMergeTwinForCluster (WBUX-6/C3 labeled-side map)', () => {
  it('maps an unlabeled cluster_b onto a pending suggestion whose cluster_a is labeled', () => {
    expect(pendingMergeTwinForCluster(UNLABELED_ID, [pendingSuggestion()])).toEqual({
      suggestionId: 'merge-1',
      survivorLabel: 'Ada Lovelace',
    });
  });

  it('returns null for labeled↔labeled pairs', () => {
    expect(
      pendingMergeTwinForCluster(
        UNLABELED_ID,
        [
          pendingSuggestion({
            cluster_a_label: 'Ada Lovelace',
            cluster_b_label: 'Grace Hopper',
          }),
        ],
      ),
    ).toBeNull();
  });

  it('returns null when both sides are unlabeled', () => {
    expect(
      pendingMergeTwinForCluster(
        UNLABELED_ID,
        [pendingSuggestion({ cluster_a_label: null, cluster_b_label: null })],
      ),
    ).toBeNull();
  });

  it.each(['Cluster-9f2', ' cluster-9f2', 'cluster_9f2'])(
    'returns null when the supposed labeled side is reserved (%j)',
    (cluster_a_label) => {
      expect(
        pendingMergeTwinForCluster(UNLABELED_ID, [pendingSuggestion({ cluster_a_label })]),
      ).toBeNull();
    },
  );

  it('returns null for the labeled cluster_a side', () => {
    expect(pendingMergeTwinForCluster(LABELED_ID, [pendingSuggestion()])).toBeNull();
  });
});
