import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  acceptMergeSuggestion,
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
import { CommitHoldRegion, ReviewQueue, type ReviewQueueHandle } from '../ReviewQueue';
import { REVIEW_QUEUE_DRAIN_MESSAGE } from '../reviewQueueDriver';
import { HOLD_STATUS_COPY, UNDO_HOLD_MS } from '../useSuggestionReviewMutations';

/**
 * Click an accept/reject control under fake setTimeout so the Slice-2 hold can
 * expire deterministically without 5s wall-clock waits (promises stay real).
 */
const clickAndCommitHold = async (button: HTMLElement): Promise<void> => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  try {
    act(() => {
      button.click();
    });
    // Hold should be open (Saving…); expire the window.
    await act(async () => {
      vi.advanceTimersByTime(UNDO_HOLD_MS);
      await Promise.resolve();
      await Promise.resolve();
    });
  } finally {
    vi.useRealTimers();
  }
};

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
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
  queueRef?: React.RefObject<ReviewQueueHandle>;
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
    // Live list: refetch after accept must return the remaining item only.
    let pendingRows = [
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
    ];
    vi.mocked(fetchPendingSuggestions).mockImplementation(() =>
      Promise.resolve({
        suggestions: pendingRows.map((row) => ({ ...row })),
        limit: 10,
        offset: 0,
      }),
    );
    vi.mocked(acceptSuggestion).mockImplementation((id: string) => {
      pendingRows = pendingRows.filter((row) => row.id !== id);
      return Promise.resolve({
        suggestion_id: id,
        resolution: 'accepted' as const,
        identity_id: 'identity-1',
        cluster_id: 'cluster-1',
        message: 'ok',
      });
    });

    const user = userEvent.setup();
    renderQueue();

    await screen.findByText(/Is this/);
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    // Face label + question both render the name — assert via card textContent.
    expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Alex/);

    await user.click(screen.getByRole('button', { name: 'Next review item' }));
    await waitFor(() => {
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Jordan/);
    });
    expect(screen.getByText('2 of 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Previous review item' }));
    await waitFor(() => {
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Alex/);
    });
    expect(screen.getByText('1 of 2')).toBeInTheDocument();

    await clickAndCommitHold(screen.getByRole('button', { name: 'Yes' }));
    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalledWith('sugg-1');
    });
    // BR-08: index stays at head; next card occupies the slot after removal.
    await waitFor(() => {
      expect(screen.getByText('1 of 1')).toBeInTheDocument();
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Jordan/);
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
    vi.mocked(acceptSuggestion).mockImplementation((id: string) =>
      // Simulate optimistic removal by resolving; mutation onMutate removes from cache.
      Promise.resolve({
        suggestion_id: id,
        resolution: 'accepted' as const,
        identity_id: 'identity-1',
        cluster_id: 'cluster-1',
        message: 'ok',
      }),
    );

    renderQueue();

    const yes = await screen.findByRole('button', { name: 'Yes' });
    yes.focus();
    expect(yes).toHaveFocus();

    await clickAndCommitHold(yes);

    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalled();
    });

    // Bare toHaveFocus — never tabUntilFocused for this assert.
    await waitFor(() => {
      const nextPrimary = screen.getByRole('button', { name: 'Yes' });
      expect(nextPrimary).toHaveFocus();
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

    await clickAndCommitHold(await screen.findByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(anchorRef.current).toHaveFocus();
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
    // BR-14: two KIND chips only — no third "All" button.
    expect(screen.queryByRole('button', { name: 'All' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Possible duplicates' }));
    expect(await screen.findByText('Are these the same person?')).toBeInTheDocument();
    expect(screen.getAllByTestId('acx-review-card')).toHaveLength(1);
    expect(screen.getByText('1 of 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Possible duplicates' })).toHaveAttribute('aria-pressed', 'true');

    // Toggle active chip → unfiltered/all.
    await user.click(screen.getByRole('button', { name: 'Possible duplicates' }));
    await waitFor(() => {
      expect(screen.getByText('1 of 2')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Possible duplicates' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Close matches' })).toHaveAttribute('aria-pressed', 'false');
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

    await clickAndCommitHold(await screen.findByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalledWith('sugg-1');
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.projection.all });
    });
  });

  it('fires reject mutation after hold window', async () => {
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

    renderQueue();

    await clickAndCommitHold(await screen.findByRole('button', { name: 'No' }));

    await waitFor(() => {
      expect(rejectSuggestion).toHaveBeenCalledWith('sugg-1');
    });
  });

  it('BR-16: undo before navigate yields 0 POSTs', async () => {
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

    renderQueue();
    await screen.findByRole('button', { name: 'Yes' });

    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      act(() => {
        screen.getByRole('button', { name: 'Yes' }).click();
      });
      expect(screen.getByText('Saving… — Undo')).toBeInTheDocument();
      act(() => {
        screen.getByRole('button', { name: 'Undo' }).click();
      });
      act(() => {
        screen.getByRole('button', { name: 'Next review item' }).click();
      });
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(acceptSuggestion).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('BR-16: navigate during hold flushes exactly 1 POST and announces', async () => {
    let pendingRows = [
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
    ];
    vi.mocked(fetchPendingSuggestions).mockImplementation(() =>
      Promise.resolve({
        suggestions: pendingRows.map((row) => ({ ...row })),
        limit: 10,
        offset: 0,
      }),
    );
    vi.mocked(acceptSuggestion).mockImplementation((id: string) => {
      pendingRows = pendingRows.filter((row) => row.id !== id);
      return Promise.resolve({
        suggestion_id: id,
        resolution: 'accepted' as const,
        identity_id: 'identity-1',
        cluster_id: 'cluster-1',
        message: 'ok',
      });
    });

    renderQueue();
    await screen.findByRole('button', { name: 'Yes' });
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      act(() => {
        screen.getByRole('button', { name: 'Yes' }).click();
      });
      expect(screen.getByText('Saving… — Undo')).toBeInTheDocument();

      await act(async () => {
        screen.getByRole('button', { name: 'Next review item' }).click();
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(acceptSuggestion).toHaveBeenCalledTimes(1);
      expect(acceptSuggestion).toHaveBeenCalledWith('sugg-1');
      expect(screen.getByText('Saved. Moving to next review item.')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('BR-15: accept A, next to B (flush), accept B → 2 POSTs order preserved; held card disabled only', async () => {
    const order: string[] = [];
    let pendingRows = [
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
    ];
    vi.mocked(fetchPendingSuggestions).mockImplementation(() =>
      Promise.resolve({
        suggestions: pendingRows.map((row) => ({ ...row })),
        limit: 10,
        offset: 0,
      }),
    );
    vi.mocked(acceptSuggestion).mockImplementation((id: string) => {
      order.push(id);
      pendingRows = pendingRows.filter((row) => row.id !== id);
      return Promise.resolve({
        suggestion_id: id,
        resolution: 'accepted' as const,
        identity_id: `identity-${id}`,
        cluster_id: 'cluster-1',
        message: 'ok',
      });
    });

    renderQueue();
    const yes = await screen.findByRole('button', { name: 'Yes' });

    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    act(() => {
      yes.click();
    });
    // Held card accept disabled; Next remains enabled (not global hold-disable).
    expect(screen.getByRole('button', { name: 'Yes' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next review item' })).not.toBeDisabled();

    act(() => {
      screen.getByRole('button', { name: 'Next review item' }).click();
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalledTimes(1);
      expect(acceptSuggestion).toHaveBeenCalledWith('sugg-1');
    });

    await waitFor(() => {
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Jordan/);
    });

    await clickAndCommitHold(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalledTimes(2);
    });
    expect(order).toEqual(['sugg-1', 'sugg-2']);
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
    expect(screen.getByRole('button', { name: 'Yes' })).toHaveFocus();
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

    await waitFor(() => {
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Jordan/);
    });
    expect(screen.getByText('2 of 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'toggle-panel' }));
    expect(screen.getByText('panel-mode')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'toggle-panel' }));
    await waitFor(() => {
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Jordan/);
    });
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

    await waitFor(() => {
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Alex/);
    });
    await user.click(screen.getByRole('button', { name: 'Next review item' }));
    await waitFor(() => {
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Jordan/);
    });

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

  it('preserves restored index across staggered query resolution (BR-06 reload gate)', async () => {
    // assignment+merge resolve first (1 assignment only) while name/cluster stay
    // pending. Old gate treated findings as settled → clamped index 3 → 0 permanently.
    let resolveName!: (value: Awaited<ReturnType<typeof fetchPendingNameSuggestions>>) => void;
    let resolveClusters!: (value: Awaited<ReturnType<typeof fetchTopUnlabeledClusters>>) => void;

    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-0',
          identity_id: 'identity-0',
          suggested_cluster_id: 'cluster-0',
          representative_similarity: 0.95,
          avg_member_similarity: 0.9,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingNameSuggestions).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveName = resolve;
        }),
    );
    vi.mocked(fetchTopUnlabeledClusters).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveClusters = resolve;
        }),
    );

    // Seeded like rq=…all.3 — controlled index 3 owned by parent (ScanTabContent).
    const Parent = (): React.JSX.Element => {
      const [index, setIndex] = React.useState(3);
      const [kind, setKind] = React.useState<ReviewQueueKindParam>('all');
      return (
        <div>
          <span data-testid="parent-index">{index}</span>
          <ReviewQueue index={index} onIndexChange={setIndex} kind={kind} onKindChange={setKind} />
        </div>
      );
    };

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, retryDelay: 0 } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <Parent />
      </QueryClientProvider>,
    );

    // Partial settle: assignment+merge done, name/cluster still in flight.
    await waitFor(() => {
      expect(fetchPendingSuggestions).toHaveBeenCalled();
      expect(fetchPendingMergeSuggestions).toHaveBeenCalled();
      // Queue shell may render the partial assignment card, but must NOT clamp.
      expect(screen.getByTestId('parent-index')).toHaveTextContent('3');
    });

    act(() => {
      resolveName({ suggestions: [], limit: 25, offset: 0 });
      resolveClusters({
        clusters: [
          {
            id: 'cluster-c1',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            identity_count: 5,
            user_confirmed: false,
            representatives: [],
          },
          {
            id: 'cluster-c2',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            identity_count: 4,
            user_confirmed: false,
            representatives: [],
          },
          {
            id: 'cluster-c3',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            identity_count: 3,
            user_confirmed: false,
            representatives: [],
          },
          {
            id: 'cluster-c4',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            identity_count: 2,
            user_confirmed: false,
            representatives: [],
          },
        ],
        limit: 20,
        total: 4,
        truncated: false,
        singleton_count: 0,
        data_source: DATA_SOURCE.LOCAL_PROJECTION,
      });
    });

    // Full queue: [Alex, c1, c2, c3, c4] — index 3 is cluster-c3.
    await waitFor(() => {
      expect(screen.getByTestId('parent-index')).toHaveTextContent('3');
      expect(screen.getByText('4 of 5')).toBeInTheDocument();
      expect(screen.getByTestId('acx-review-card')).toHaveAttribute('data-review-kind', 'cluster');
    });
  });

  it('does not move focus on Next after a failed accept (BR-13)', async () => {
    // Use merge accept (no optimistic remove) so a failure leaves the card in place
    // with a stale pending-focus ref — the bug the clear-on-error fix targets.
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
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
        {
          id: 'merge-2',
          cluster_a_id: 'c',
          cluster_b_id: 'd',
          similarity: 0.8,
          status: 'pending',
          cluster_a_label: 'Casey',
          cluster_b_label: 'Drew',
        },
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(acceptMergeSuggestion).mockRejectedValue(new Error('merge accept failed'));

    const user = userEvent.setup();
    renderQueue();

    const yes = await screen.findByRole('button', { name: 'Yes' });
    yes.focus();
    await clickAndCommitHold(yes);

    await waitFor(() => {
      expect(acceptMergeSuggestion).toHaveBeenCalled();
    });
    // Still on first merge card (failure leaves item at head).
    expect(screen.getByText('Are these the same person?')).toBeInTheDocument();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    // Persistent failure alert.
    expect(screen.getByRole('alert')).toBeInTheDocument();

    // Blur so a later surprise-focus is unambiguous.
    (document.activeElement as HTMLElement | null)?.blur();

    await user.click(screen.getByRole('button', { name: 'Next review item' }));
    await waitFor(() => {
      expect(screen.getByText('2 of 2')).toBeInTheDocument();
    });
    // Stale pending-focus must not auto-focus the primary after Next.
    expect(screen.getByRole('button', { name: 'Yes' })).not.toHaveFocus();
  });

  it('uses the shared drain message for empty state and drain announcement', async () => {
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

    renderQueue();

    await clickAndCommitHold(await screen.findByRole('button', { name: 'Yes' }));
    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalled();
    });
    await waitFor(() => {
      const statuses = screen.getAllByRole('status');
      expect(statuses.some((node) => within(node).queryByText(REVIEW_QUEUE_DRAIN_MESSAGE))).toBe(true);
      expect(screen.getByText(REVIEW_QUEUE_DRAIN_MESSAGE)).toBeInTheDocument();
    });
  });
});

describe('CommitHoldRegion (shipped hold chrome — BR-19)', () => {
  it('renders role=status with HOLD_STATUS_COPY, pause-on-focus/hover, resume-on-leave, Undo tab order', async () => {
    const onPausedChange = vi.fn();
    const onUndo = vi.fn();
    const user = userEvent.setup();

    render(
      <div>
        <button type="button">Yes</button>
        <CommitHoldRegion
          phase="holding"
          errorMessage={null}
          onUndo={onUndo}
          onRetry={() => undefined}
          onPausedChange={onPausedChange}
        />
      </div>,
    );

    const status = screen.getByRole('status');
    expect(status).toHaveTextContent(HOLD_STATUS_COPY);
    const undo = screen.getByRole('button', { name: 'Undo' });

    // Undo follows the actioned control in tab order.
    const yes = screen.getByRole('button', { name: 'Yes' });
    yes.focus();
    await user.tab();
    expect(undo).toHaveFocus();
    expect(onPausedChange).toHaveBeenCalledWith(true);
    onPausedChange.mockClear();

    await user.hover(status);
    expect(onPausedChange).toHaveBeenCalledWith(true);
    onPausedChange.mockClear();

    await user.unhover(status);
    expect(onPausedChange).toHaveBeenCalledWith(false);
  });

  it('failed phase renders persistent role=alert; Retry disabled while retryPending (BR-17)', () => {
    const { rerender } = render(
      <CommitHoldRegion
        phase="failed"
        errorMessage="Accept failed."
        onUndo={() => undefined}
        onRetry={() => undefined}
        onPausedChange={() => undefined}
        retryPending={false}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Accept failed.');
    expect(screen.getByRole('button', { name: 'Retry' })).not.toBeDisabled();

    rerender(
      <CommitHoldRegion
        phase="failed"
        errorMessage="Accept failed."
        onUndo={() => undefined}
        onRetry={() => undefined}
        onPausedChange={() => undefined}
        retryPending
      />,
    );
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDisabled();
  });
});
