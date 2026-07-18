import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  acceptSuggestion,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  fetchTopUnlabeledClusters,
  rejectSuggestion,
} from '../../../../api/recognition';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import { resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import type { ReviewQueueKindParam } from '../../../../hooks/workbenchQueueUrl';
import { ReviewQueue, type ReviewQueueHandle } from '../ReviewQueue';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (format: string, ...args: Array<string | number>) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('@radix-ui/react-avatar', async () => {
  const ReactMod = await import('react');
  return {
    Root: ReactMod.forwardRef(function MockRoot({ children, ...props }: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: ReactMod.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return ReactMod.createElement('img', { ...props, ref } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: ReactMod.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    acceptSuggestion: vi.fn(),
    acceptMergeSuggestion: vi.fn(),
    acceptNameSuggestion: vi.fn(),
    rejectSuggestion: vi.fn(),
    rejectMergeSuggestion: vi.fn(),
    rejectNameSuggestion: vi.fn(),
    bulkAcceptSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
    dismissCluster: vi.fn().mockResolvedValue(undefined),
    mergeCluster: vi.fn().mockResolvedValue(undefined),
    updateClusterLabel: vi.fn().mockResolvedValue(undefined),
  };
});

interface HarnessProps {
  initialIndex?: number;
  initialKind?: ReviewQueueKindParam;
  emptyStateAnchorRef?: React.RefObject<HTMLElement | null>;
  queueRef?: React.RefObject<ReviewQueueHandle | null>;
}

const ReviewQueueHarness = ({
  initialIndex = 0,
  initialKind = 'all',
  emptyStateAnchorRef,
  queueRef,
}: HarnessProps): React.JSX.Element => {
  const [index, setIndex] = React.useState(initialIndex);
  const [kind, setKind] = React.useState<ReviewQueueKindParam>(initialKind);
  return (
    <ReviewQueue
      ref={queueRef}
      index={index}
      onIndexChange={setIndex}
      kind={kind}
      onKindChange={setKind}
      emptyStateAnchorRef={emptyStateAnchorRef}
    />
  );
};

const renderQueue = (props: HarnessProps = {}) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, retryDelay: 0 },
    },
  });

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <ReviewQueueHarness {...props} />
    </QueryClientProvider>,
  );

  return { queryClient, ...utils };
};

describe('ReviewQueue', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      endpoints: {
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
        recognitionMergeSuggestions: 'http://localhost/recognition/suggestions/merge',
        recognitionNameSuggestions: 'http://localhost/recognition/suggestions/name',
        recognitionBulkAcceptSuggestions: 'http://localhost/recognition/suggestions/bulk-accept',
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    };

    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    resetConfigCache();
  });

  it('renders exactly one review card at a time (one-card invariant)', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
        {
          id: 'sugg-2',
          identity_id: 'identity-2',
          suggested_cluster_id: 'cluster-2',
          representative_similarity: 0.8,
          avg_member_similarity: 0.75,
          cluster_label: 'Jordan',
          cluster_identity_count: 2,
        },
      ],
      limit: 10,
      offset: 0,
    });

    renderQueue();

    await screen.findByRole('button', { name: 'Yes' });
    expect(screen.getAllByTestId('acx-review-card')).toHaveLength(1);
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
  });

  it('navigates with prev/next without changing index on accept (PR-54 live-queue semantics)', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.95,
          avg_member_similarity: 0.9,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
        {
          id: 'sugg-2',
          identity_id: 'identity-2',
          suggested_cluster_id: 'cluster-2',
          representative_similarity: 0.7,
          avg_member_similarity: 0.65,
          cluster_label: 'Jordan',
          cluster_identity_count: 2,
        },
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-1',
      resolution: 'accepted',
      identity_id: 'identity-1',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const user = userEvent.setup();
    renderQueue();

    await screen.findByText(/Is this/);
    expect(screen.getByText('Alex')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Jordan')).toBeInTheDocument();
    expect(screen.getByText('2 of 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Previous' }));
    expect(await screen.findByText('Alex')).toBeInTheDocument();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Yes' }));
    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalledWith('sugg-1', expect.anything());
    });
  });

  it('focuses next card primary action after accept (authoritative advance-focus gate)', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.95,
          avg_member_similarity: 0.9,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
        {
          id: 'sugg-2',
          identity_id: 'identity-2',
          suggested_cluster_id: 'cluster-2',
          representative_similarity: 0.7,
          avg_member_similarity: 0.65,
          cluster_label: 'Jordan',
          cluster_identity_count: 2,
        },
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(acceptSuggestion).mockImplementation(async (id: string) => {
      // Simulate optimistic removal by resolving; mutation onMutate removes from cache.
      return {
        suggestion_id: id,
        resolution: 'accepted' as const,
        identity_id: 'identity-1',
        cluster_id: 'cluster-1',
        message: 'ok',
      };
    });

    const user = userEvent.setup();
    renderQueue();

    const yes = await screen.findByRole('button', { name: 'Yes' });
    yes.focus();
    expect(yes).toBeFocused();

    await user.click(yes);

    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalled();
    });

    // Bare toBeFocused — never tabUntilFocused for this assert.
    await waitFor(() => {
      const nextPrimary = screen.getByRole('button', { name: 'Yes' });
      expect(nextPrimary).toBeFocused();
    });
  });

  it('focuses empty-state anchor when the queue drains', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-only',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 1,
        },
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-only',
      resolution: 'accepted',
      identity_id: 'identity-1',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const anchorRef = React.createRef<HTMLDivElement>();
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, retryDelay: 0 } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <div ref={anchorRef} className="acx-findings-detail-anchor" tabIndex={-1}>
          <ReviewQueueHarness emptyStateAnchorRef={anchorRef} />
        </div>
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(anchorRef.current).toBeFocused();
    });
  });

  it('filters with kind chips and shows one card for the filtered set', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'merge-1',
          cluster_a_id: 'a',
          cluster_b_id: 'b',
          similarity: 0.88,
          status: 'pending',
          cluster_a_label: 'Alex',
          cluster_b_label: 'Jordan',
        },
      ],
      limit: 10,
      offset: 0,
    });

    const user = userEvent.setup();
    renderQueue();

    await screen.findByText(/Is this/);
    expect(screen.getByText('1 of 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Possible duplicates' }));
    expect(await screen.findByText('Are these the same person?')).toBeInTheDocument();
    expect(screen.getAllByTestId('acx-review-card')).toHaveLength(1);
    expect(screen.getByText('1 of 1')).toBeInTheDocument();
  });

  it('fires existing accept mutation and invalidates projection keys', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-1',
      resolution: 'accepted',
      identity_id: 'identity-1',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { queryClient } = renderQueue();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalledWith('sugg-1', expect.anything());
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.projection.all });
    });
  });

  it('fires reject mutation unchanged', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(rejectSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-1',
      resolution: 'rejected',
      identity_id: 'identity-1',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const user = userEvent.setup();
    renderQueue();

    await user.click(await screen.findByRole('button', { name: 'No' }));

    await waitFor(() => {
      expect(rejectSuggestion).toHaveBeenCalledWith('sugg-1', expect.anything());
    });
  });

  it('exposes focusCurrentCard imperative handle', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    });

    const queueRef = React.createRef<ReviewQueueHandle>();
    renderQueue({ queueRef });

    await screen.findByRole('button', { name: 'Yes' });
    act(() => {
      queueRef.current?.focusCurrentCard();
    });
    expect(screen.getByRole('button', { name: 'Yes' })).toBeFocused();
  });

  it('preserves controlled index across unmount/remount (panel round-trip)', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.95,
          avg_member_similarity: 0.9,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
        {
          id: 'sugg-2',
          identity_id: 'identity-2',
          suggested_cluster_id: 'cluster-2',
          representative_similarity: 0.7,
          avg_member_similarity: 0.65,
          cluster_label: 'Jordan',
          cluster_identity_count: 2,
        },
      ],
      limit: 10,
      offset: 0,
    });

    const Parent = (): React.JSX.Element => {
      const [index, setIndex] = React.useState(1);
      const [kind, setKind] = React.useState<ReviewQueueKindParam>('all');
      const [mounted, setMounted] = React.useState(true);
      return (
        <div>
          <button type="button" onClick={() => setMounted((v) => !v)}>
            toggle-panel
          </button>
          {mounted ? (
            <ReviewQueue index={index} onIndexChange={setIndex} kind={kind} onKindChange={setKind} />
          ) : (
            <p>panel-mode</p>
          )}
        </div>
      );
    };

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, retryDelay: 0 } },
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <Parent />
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Jordan')).toBeInTheDocument();
    expect(screen.getByText('2 of 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'toggle-panel' }));
    expect(screen.getByText('panel-mode')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'toggle-panel' }));
    expect(await screen.findByText('Jordan')).toBeInTheDocument();
    expect(screen.getByText('2 of 2')).toBeInTheDocument();
  });

  it('announces card transitions via role=status live region', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.95,
          avg_member_similarity: 0.9,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
        {
          id: 'sugg-2',
          identity_id: 'identity-2',
          suggested_cluster_id: 'cluster-2',
          representative_similarity: 0.7,
          avg_member_similarity: 0.65,
          cluster_label: 'Jordan',
          cluster_identity_count: 2,
        },
      ],
      limit: 10,
      offset: 0,
    });

    const user = userEvent.setup();
    renderQueue();

    await screen.findByText('Alex');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Jordan');

    const statuses = screen.getAllByRole('status');
    expect(statuses.some((node) => within(node).queryByText(/Review item/i))).toBe(true);
  });

  it('renders unavailable guidance instead of a false empty state', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.UNAVAILABLE,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.UNAVAILABLE,
    });

    renderQueue();

    await waitFor(() => {
      expect(screen.getByText('Suggestion service not configured')).toBeInTheDocument();
    });
  });

  it('does not render bulk-accept or grouped Yes-all chrome', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-group-1',
          identity_id: 'identity-group-1',
          suggested_cluster_id: 'cluster-maria',
          representative_similarity: 0.68,
          avg_member_similarity: 0.6,
          cluster_label: 'Maria',
          cluster_identity_count: 13,
        },
        {
          id: 'sugg-group-2',
          identity_id: 'identity-group-2',
          suggested_cluster_id: 'cluster-maria',
          representative_similarity: 0.63,
          avg_member_similarity: 0.57,
          cluster_label: 'Maria',
          cluster_identity_count: 13,
        },
      ],
      limit: 10,
      offset: 0,
    });

    renderQueue();

    await screen.findByRole('button', { name: 'Yes' });
    expect(screen.queryByRole('button', { name: 'Yes all' })).not.toBeInTheDocument();
    expect(screen.queryByText('Bulk accept')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('acx-review-card')).toHaveLength(1);
  });
});
