import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
import * as recognitionApi from '../../../../api/recognition';
import { DATA_SOURCE, type DataSource } from '../../../../api/recognition/types';
import type { DetectedIdentity, PendingMergeSuggestion } from '../../../../api/recognition/types';
import { IdentityClusterList } from '../IdentityClusterList';
import { isPendingMergePageTruncated } from '../usePendingMergeTwins';

const { scheduleAcceptMerge, scheduleRejectMerge } = vi.hoisted(() => ({
  scheduleAcceptMerge: vi.fn(),
  scheduleRejectMerge: vi.fn(),
}));

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

vi.mock('../useSuggestionReviewMutations', () => ({
  useSuggestionReviewMutations: () => ({
    scheduleAcceptMerge,
    scheduleRejectMerge,
    isCardActionsDisabled: () => false,
    isCommitting: false,
    mutations: {
      acceptMerge: { isPending: false },
      rejectMerge: { isPending: false },
    },
  }),
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>(
    '../../../../api/recognition',
  );
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
    fetchIdentitiesSuggestions: vi.fn(),
    acceptMergeSuggestion: vi.fn(),
    rejectMergeSuggestion: vi.fn(),
  };
});

const UNLABELED_ID = 'cluster-b-unlabeled';
const LABELED_ID = 'cluster-a-labeled';
const OTHER_UNLABELED_ID = 'cluster-c-other';

const identity = (overrides: Partial<DetectedIdentity> = {}): DetectedIdentity => ({
  identity_id: 'id-unlabeled',
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

const pendingMerge = (overrides: Partial<PendingMergeSuggestion> = {}): PendingMergeSuggestion => ({
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

const renderList = (identities: DetectedIdentity[], dataSource?: DataSource) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityClusterList identities={identities} dataSource={dataSource} />
    </QueryClientProvider>,
  );
};

describe('IdentityClusterList twin chip (WBUX-6/C3 S4-F1/F4/F6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      tenant_id: 'tenant-1',
      endpoints: {
        recognitionClusters: 'http://localhost/recognition/clusters',
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
      },
    };
    resetConfigCache();
    scheduleAcceptMerge.mockReset();
    scheduleRejectMerge.mockReset();
    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(recognitionApi.fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
    });
    vi.mocked(recognitionApi.fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({ matches: {} });
    vi.mocked(recognitionApi.fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [pendingMerge()],
      limit: 50,
      offset: 0,
    });
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockResolvedValue(pendingMerge());
    vi.mocked(recognitionApi.rejectMergeSuggestion).mockResolvedValue(pendingMerge());
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the chip from mergeSuggestions and routes Accept/Reject through schedulers', async () => {
    const user = userEvent.setup();
    renderList([identity()]);

    await waitFor(() => {
      expect(screen.getByRole('group', { name: /same person as ada lovelace/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'Merge into Ada' }));
    await user.click(screen.getByRole('button', { name: 'Not the same' }));

    expect(scheduleAcceptMerge).toHaveBeenCalledTimes(1);
    expect(scheduleAcceptMerge).toHaveBeenCalledWith('merge-1');
    expect(scheduleRejectMerge).toHaveBeenCalledTimes(1);
    expect(scheduleRejectMerge).toHaveBeenCalledWith('merge-1');
    expect(recognitionApi.acceptMergeSuggestion).not.toHaveBeenCalled();
    expect(recognitionApi.rejectMergeSuggestion).not.toHaveBeenCalled();
  });

  it('subscribes only to pending merges at the twin page limit', async () => {
    renderList([identity()]);

    await waitFor(() => {
      expect(recognitionApi.fetchPendingMergeSuggestions).toHaveBeenCalled();
    });

    expect(recognitionApi.fetchPendingMergeSuggestions).toHaveBeenCalledWith(50, 0);
    expect(recognitionApi.fetchPendingSuggestions).not.toHaveBeenCalled();
    expect(recognitionApi.fetchPendingNameSuggestions).not.toHaveBeenCalled();
    expect(recognitionApi.fetchTopUnlabeledClusters).not.toHaveBeenCalled();
  });

  it('renders the review-queue link for unlabeled clusters without a twin when truncated', async () => {
    vi.mocked(recognitionApi.fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [pendingMerge()],
      limit: 50,
      offset: 0,
      total: 2,
    } as Awaited<ReturnType<typeof recognitionApi.fetchPendingMergeSuggestions>> & { total: number });

    renderList([
      identity(),
      identity({
        identity_id: 'id-other',
        cluster_id: OTHER_UNLABELED_ID,
      }),
    ]);

    await waitFor(() => {
      expect(screen.getByRole('group', { name: /same person as ada lovelace/i })).toBeInTheDocument();
    });
    expect(screen.getByRole('link', { name: 'Review pending merges' })).toBeInTheDocument();
  });

  it('does not render a silent-twin fallback link when the loaded page is complete', async () => {
    vi.mocked(recognitionApi.fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [pendingMerge(), pendingMerge({ id: 'merge-2', cluster_b_id: 'cluster-other-labeled' })],
      limit: 50,
      offset: 0,
    });

    renderList([
      identity(),
      identity({
        identity_id: 'id-other',
        cluster_id: OTHER_UNLABELED_ID,
      }),
    ]);

    await waitFor(() => {
      expect(screen.getByRole('group', { name: /same person as ada lovelace/i })).toBeInTheDocument();
    });
    expect(screen.queryByRole('link', { name: 'Review pending merges' })).not.toBeInTheDocument();
  });

  it('does not offer the twin chip on label-only BACKEND_PROXY rows', async () => {
    renderList([identity()], DATA_SOURCE.BACKEND_PROXY);

    await waitFor(() => {
      expect(recognitionApi.fetchPendingMergeSuggestions).toHaveBeenCalled();
    });

    expect(screen.queryByTestId('acx-identity-clusters__twin-chip')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Merge into Ada' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Not the same' })).not.toBeInTheDocument();
  });
});

describe('isPendingMergePageTruncated (S4-F4)', () => {
  it('is false for a 2-suggestion page under the twin limit', () => {
    expect(
      isPendingMergePageTruncated({
        suggestions: [pendingMerge(), pendingMerge({ id: 'merge-2' })],
      }),
    ).toBe(false);
  });

  it('is true when envelope total exceeds loaded items', () => {
    expect(
      isPendingMergePageTruncated({
        suggestions: [pendingMerge()],
        total: 2,
      }),
    ).toBe(true);
  });
});
