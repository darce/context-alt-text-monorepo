import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  acceptMergeSuggestion,
  acceptSuggestion,
  bulkAcceptSuggestions,
  fetchClusterMembers,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  fetchTopUnlabeledClusters,
  rejectSuggestion,
  updateClusterLabel,
  type PendingSuggestionsResponse,
} from '../../../../api/recognition';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import { resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import {
  commitClusterToRosterEntry,
  listRosterEntries,
  type RosterClusterCommitResponse,
} from '../../../../api/rosterApi';
import type {
  ReviewQueueBandParam,
  ReviewQueueKindParam,
} from '../../../../hooks/workbenchQueueUrl';
import {
  MODEL_OUTPUT_DISCLOSURE,
  PERSON_COMMIT_COMBOBOX_ARIA,
  PERSON_COMMIT_CONFIRM_COPY,
  VIEW_IN_ROSTER_COPY,
  viewInRosterHref,
} from '../personCommitCopy';
import { MergeSurvivorProvider } from '../MergeSurvivorContext';
import { CommitHoldRegion, ReviewQueue, type ReviewQueueHandle } from '../ReviewQueue';
import { ReviewCardGroupShell } from '../reviewCardGroupAccname';
import { REVIEW_QUEUE_DRAIN_MESSAGE } from '../reviewQueueDriver';
import * as useAriaAnnounceMod from '../useAriaAnnounce';
import {
  HOLD_COMMITTING_STATUS_COPY,
  HOLD_STATUS_COPY,
  UNDO_HOLD_MS,
} from '../useSuggestionReviewMutations';
import { LIVE_TARGET_CLOSE_ANNOUNCE } from '../useLiveReviewTarget';
import { HTTPError } from '../../../../utils/http';

const rosterCommitFixture = (
  overrides: Partial<RosterClusterCommitResponse> = {},
): RosterClusterCommitResponse => ({
  cluster_id: 'cluster-1',
  person_id: 7,
  person_uuid: 'person-uuid-7',
  person_name: 'Alex',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
});

/**
 * UXW2-3 single-gesture naming: type into the inline NameFaceControl and commit
 * with Enter. Waits for the roster typeahead so exact names resolve to rosterEntryId.
 */
const typePersonName = async (
  user: ReturnType<typeof userEvent.setup>,
  name: string,
): Promise<void> => {
  const commit = await screen.findByTestId('acx-person-commit');
  await within(commit).findByText(name);
  const input = within(commit).getByRole('combobox', { name: PERSON_COMMIT_COMBOBOX_ARIA });
  await user.type(input, `${name}{Enter}`);
};

/** Whole-content of a hold live region — jest-dom string matchers are substring. */
const wholeHoldText = (el: HTMLElement): string =>
  (el.textContent ?? '').replace(/\s+/g, ' ').trim();

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
    fetchClusterMembers: vi.fn().mockResolvedValue({
      members: [],
      limit: 25,
      total: 0,
      truncated: false,
    }),
    fetchTopUnlabeledClusters: vi.fn(),
    dismissCluster: vi.fn().mockResolvedValue(undefined),
    mergeCluster: vi.fn().mockResolvedValue(undefined),
    updateClusterLabel: vi.fn().mockResolvedValue(undefined),
  };
});

vi.mock('../../../../api/rosterApi', () => ({
  commitClusterToRosterEntry: vi.fn().mockResolvedValue({
    cluster_id: 'cluster-1',
    person_id: 7,
    person_uuid: 'person-uuid-7',
    person_name: 'Alex',
    updated_at: '2026-01-01T00:00:00Z',
  }),
  listRosterEntries: vi.fn().mockResolvedValue([
    {
      id: 7,
      person_uuid: 'person-uuid-7',
      name: 'Alex',
      tags: [],
      cluster_count: 0,
      clusters: [],
      queue_memberships: [],
      updated_at: '2026-01-01T00:00:00Z',
      source_version: 1,
      projection_status: 'current',
      projection_refreshed_at: null,
    },
  ]),
}));

interface HarnessProps {
  initialIndex?: number;
  initialKind?: ReviewQueueKindParam;
  initialBand?: ReviewQueueBandParam;
  emptyStateAnchorRef?: React.RefObject<HTMLElement | null>;
  queueRef?: React.RefObject<ReviewQueueHandle>;
  onReview?: (clusterId: string) => void;
  onLabel?: (clusterId: string) => void;
  /** Expose selection for M2 asserts (optional). */
  selectionRef?: React.MutableRefObject<Set<string>>;
}

const ReviewQueueHarness = ({
  initialIndex = 0,
  initialKind = 'all',
  initialBand = 'all',
  emptyStateAnchorRef,
  queueRef,
  onReview,
  onLabel,
  selectionRef,
}: HarnessProps): React.JSX.Element => {
  const [index, setIndex] = React.useState(initialIndex);
  const [kind, setKind] = React.useState<ReviewQueueKindParam>(initialKind);
  const [band, setBand] = React.useState<ReviewQueueBandParam>(initialBand);
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
  if (selectionRef) {
    selectionRef.current = selectedIds;
  }
  return (
    <ReviewQueue
      ref={queueRef}
      index={index}
      onIndexChange={setIndex}
      kind={kind}
      onKindChange={setKind}
      band={band}
      onBandChange={setBand}
      selectedIds={selectedIds}
      onSelectedIdsChange={setSelectedIds}
      emptyStateAnchorRef={emptyStateAnchorRef}
      onReview={onReview}
      onLabel={onLabel}
    />
  );
};

const withQueueProviders = (queryClient: QueryClient, children: React.ReactNode) => (
  <QueryClientProvider client={queryClient}>
    <MergeSurvivorProvider>{children}</MergeSurvivorProvider>
  </QueryClientProvider>
);

const renderQueue = (props: HarnessProps = {}) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, retryDelay: 0 },
    },
  });

  const utils = render(withQueueProviders(queryClient, <ReviewQueueHarness {...props} />));

  return { queryClient, ...utils };
};

describe('ReviewQueue', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
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
    vi.mocked(fetchClusterMembers).mockResolvedValue({
      members: [],
      limit: 25,
      total: 0,
      truncated: false,
    });
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
    vi.mocked(listRosterEntries).mockResolvedValue([
      {
        id: 7,
        person_uuid: 'person-uuid-7',
        name: 'Alex',
        tags: [],
        cluster_count: 0,
        clusters: [],
        queue_memberships: [],
        updated_at: '2026-01-01T00:00:00Z',
        source_version: 1,
        projection_status: 'current',
        projection_refreshed_at: null,
      },
    ]);
    vi.mocked(commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());
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
        <MergeSurvivorProvider>
          <div ref={anchorRef} className="acx-findings-detail-anchor" tabIndex={-1}>
            <ReviewQueueHarness emptyStateAnchorRef={anchorRef} />
          </div>
        </MergeSurvivorProvider>
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
      const [band, setBand] = React.useState<ReviewQueueBandParam>('all');
      const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
      const [mounted, setMounted] = React.useState(true);
      return (
        <div>
          <button type="button" onClick={() => setMounted((v) => !v)}>
            toggle-panel
          </button>
          {mounted ? (
            <ReviewQueue
              index={index}
              onIndexChange={setIndex}
              kind={kind}
              onKindChange={setKind}
              band={band}
              onBandChange={setBand}
              selectedIds={selectedIds}
              onSelectedIdsChange={setSelectedIds}
            />
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
        <MergeSurvivorProvider>
          <Parent />
        </MergeSurvivorProvider>
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

  // E21-20-REV1-03 / TEST-15: chained assignment.then(merge) skips merge on reject.
  it('REV1-03: unavailable Retry still refetches merge and top-unlabeled when assignment rejects', async () => {
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

    const mergeCallsBefore = vi.mocked(fetchPendingMergeSuggestions).mock.calls.length;
    const topCallsBefore = vi.mocked(fetchTopUnlabeledClusters).mock.calls.length;
    vi.mocked(fetchPendingSuggestions).mockRejectedValueOnce(new Error('assignment refetch failed'));

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(vi.mocked(fetchPendingMergeSuggestions).mock.calls.length).toBeGreaterThan(mergeCallsBefore);
      expect(vi.mocked(fetchTopUnlabeledClusters).mock.calls.length).toBeGreaterThan(topCallsBefore);
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
      const [band, setBand] = React.useState<ReviewQueueBandParam>('all');
      const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
      return (
        <div>
          <span data-testid="parent-index">{index}</span>
          <ReviewQueue
            index={index}
            onIndexChange={setIndex}
            kind={kind}
            onKindChange={setKind}
            band={band}
            onBandChange={setBand}
            selectedIds={selectedIds}
            onSelectedIdsChange={setSelectedIds}
          />
        </div>
      );
    };

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, retryDelay: 0 } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MergeSurvivorProvider>
          <Parent />
        </MergeSurvivorProvider>
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
            representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
          },
          {
            id: 'cluster-c2',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            identity_count: 4,
            user_confirmed: false,
            representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
          },
          {
            id: 'cluster-c3',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            identity_count: 3,
            user_confirmed: false,
            representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
          },
          {
            id: 'cluster-c4',
            tenant_id: 'test-tenant-id',
            label: null,
            is_labeled: false,
            is_auto_label: false,
            identity_count: 2,
            user_confirmed: false,
            representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
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

  it('re-announces identical live copy via seq-keyed region (HARM-02 / BR-68)', async () => {
    // Capture announce so we can fire the SAME string twice consecutively —
    // plain useState would Object.is-bail; useAriaAnnounce must bump seq.
    const original = useAriaAnnounceMod.useAriaAnnounce;
    let latestAnnounce: ((message: string) => void) | null = null;
    const spy = vi.spyOn(useAriaAnnounceMod, 'useAriaAnnounce').mockImplementation(() => {
      const result = original();
      latestAnnounce = result.announce;
      return result;
    });

    try {
      vi.mocked(fetchPendingSuggestions).mockResolvedValue({
        suggestions: [
          {
            id: 'sugg-1',
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

      renderQueue();
      await screen.findByRole('button', { name: 'Yes' });
      await waitFor(() => {
        expect(latestAnnounce).not.toBeNull();
      });

      const repeatCopy = LIVE_TARGET_CLOSE_ANNOUNCE;
      act(() => {
        latestAnnounce?.(repeatCopy);
      });
      const live1 = document.querySelector('.acx-review-queue__live');
      expect(live1).toHaveTextContent(repeatCopy);
      const seq1 = live1?.getAttribute('data-announce-seq');
      expect(seq1).toBeTruthy();

      act(() => {
        latestAnnounce?.(repeatCopy);
      });
      await waitFor(() => {
        const live2 = document.querySelector('.acx-review-queue__live');
        expect(live2).toHaveTextContent(repeatCopy);
        expect(live2?.getAttribute('data-announce-seq')).not.toBe(seq1);
      });
    } finally {
      spy.mockRestore();
    }
  });

  it('shows filtered-empty escape hatch when filters hide pending work (S1-01 / COG-03)', async () => {
    // Assignments only in the unfiltered queue; merge KIND filter → empty view.
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'assign-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 2,
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

    const onKindChange = vi.fn();
    const onBandChange = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, retryDelay: 0 } },
    });

    const FilteredEmptyHarness = (): React.JSX.Element => {
      const [index, setIndex] = React.useState(0);
      const [kind, setKind] = React.useState<ReviewQueueKindParam>('merge');
      const [band, setBand] = React.useState<ReviewQueueBandParam>('all');
      const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
      return (
        <ReviewQueue
          index={index}
          onIndexChange={setIndex}
          kind={kind}
          onKindChange={(next) => {
            onKindChange(next);
            setKind(next);
          }}
          band={band}
          onBandChange={(next) => {
            onBandChange(next);
            setBand(next);
          }}
          selectedIds={selectedIds}
          onSelectedIdsChange={setSelectedIds}
        />
      );
    };

    const user = userEvent.setup();
    render(withQueueProviders(queryClient, <FilteredEmptyHarness />));

    await waitFor(() => {
      expect(screen.getByText('No items match the current filters.')).toBeInTheDocument();
    });
    expect(screen.queryByText(REVIEW_QUEUE_DRAIN_MESSAGE)).not.toBeInTheDocument();
    const clearBtn = screen.getByRole('button', { name: 'Clear filters' });
    expect(clearBtn).toBeInTheDocument();

    await user.click(clearBtn);
    expect(onKindChange).toHaveBeenCalledWith('all');
    expect(onBandChange).toHaveBeenCalledWith('all');
    await waitFor(() => {
      expect(screen.getByTestId('acx-review-card')).toBeInTheDocument();
    });
  });

  it('shows true drain copy when unfiltered queue is empty', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });

    renderQueue();

    await waitFor(() => {
      expect(screen.getByText(REVIEW_QUEUE_DRAIN_MESSAGE)).toBeInTheDocument();
    });
    expect(screen.queryByText('No items match the current filters.')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument();
  });

  // --- Slice 3: person-commit on the card ---

  it('shows person-commit + HAI-05 disclosure on ASSIGNMENT when clusterId present', async () => {
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

    renderQueue();

    await screen.findByRole('button', { name: 'Yes' });
    expect(screen.getByTestId('acx-person-commit')).toBeInTheDocument();
    expect(screen.getByText(MODEL_OUTPUT_DISCLOSURE)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: PERSON_COMMIT_CONFIRM_COPY })).toBeInTheDocument();
  });

  it('hides person-commit on MERGE cards', async () => {
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
      ],
      limit: 10,
      offset: 0,
    });

    renderQueue();

    await screen.findByText('Are these the same person?');
    expect(screen.queryByTestId('acx-person-commit')).not.toBeInTheDocument();
  });

  // BR-35: CurrentCard pipes queue chrome position into MERGE card ordinal props.
  it('BR-35: MERGE card receives queue ordinal from position chrome', async () => {
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
          similarity: 0.9,
          status: 'pending',
          cluster_a_label: 'Sam',
          cluster_b_label: 'Riley',
        },
      ],
      limit: 10,
      offset: 0,
    });

    renderQueue();

    await screen.findByText('Are these the same person?');
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    const card = screen.getByTestId('acx-review-card');
    expect(card).toHaveAccessibleName(/Merge suggestion 1 of 2/);
    expect(card).toHaveAccessibleName(/Are these the same person\?/);
    expect(document.getElementById('acx-merge-pos-merge-1')).toHaveTextContent(
      'Merge suggestion 1 of 2',
    );
  });

  // BR-41: CurrentCard pipes queue chrome ordinal into ASSIGNMENT / NAME / CLUSTER group accnames.
  it('BR-41: ASSIGNMENT card receives queue ordinal from position chrome', async () => {
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
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    const card = screen.getByTestId('acx-review-card');
    expect(card).toHaveAccessibleName(/Face suggestion 1 of 2/);
  });

  it('BR-41: NAME card receives queue ordinal from position chrome', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'name-1',
          cluster_id: 'cluster-name-1',
          suggested_name: 'Morgan',
          confidence_score: 0.91,
          source: 'test',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
        {
          id: 'name-2',
          cluster_id: 'cluster-name-2',
          suggested_name: 'Riley',
          confidence_score: 0.88,
          source: 'test',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
      ],
      limit: 25,
      offset: 0,
    });

    renderQueue();

    await screen.findByText(/Suggested name:/);
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    const card = screen.getByTestId('acx-review-card');
    expect(card).toHaveAccessibleName(/Name suggestion 1 of 2/);
  });

  it('BR-41: CLUSTER card receives queue ordinal from position chrome', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [
        {
          id: 'cluster-top-1',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 4,
          user_confirmed: false,
          suggested_label: null,
          suggested_target_cluster_id: null,
          representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
        },
        {
          id: 'cluster-top-2',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 3,
          user_confirmed: false,
          suggested_label: null,
          suggested_target_cluster_id: null,
          representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
        },
      ],
      limit: 20,
      total: 2,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    renderQueue();

    await screen.findByTestId('acx-review-card');
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    const card = screen.getByTestId('acx-review-card');
    expect(card).toHaveAccessibleName(/Face group review 1 of 2/);
  });

  // BR-41: NAME invalid/no-ordinal fallbacks (inline CurrentCard root uses ReviewCardGroupShell).
  it.each([
    { label: '1 of 2', queuePosition: 1, queueTotal: 2 },
    { label: '3 of 3', queuePosition: 3, queueTotal: 3 },
    { label: '1 of 1', queuePosition: 1, queueTotal: 1 },
  ])(
    'BR-41: NAME valid ordinal pair keeps Name suggestion $label',
    ({ queuePosition, queueTotal }) => {
      render(
        <ReviewCardGroupShell
          kind="name"
          labelId={`acx-name-pos-${queuePosition}-${queueTotal}`}
          queuePosition={queuePosition}
          queueTotal={queueTotal}
          className="acx-suggestion-card acx-name-suggestion-card"
          data-testid="acx-review-card"
          data-review-kind="name"
        />,
      );

      const card = screen.getByTestId('acx-review-card');
      expect(card).toHaveAccessibleName(
        new RegExp(`Name suggestion ${queuePosition} of ${queueTotal}`),
      );
    },
  );

  it.each([
    { label: 'total=0', queuePosition: 1, queueTotal: 0 },
    { label: 'position=NaN', queuePosition: Number.NaN, queueTotal: 2 },
    { label: 'total=Infinity', queuePosition: 1, queueTotal: Number.POSITIVE_INFINITY },
    { label: 'position=float', queuePosition: 1.5, queueTotal: 2 },
    { label: 'position>total', queuePosition: 4, queueTotal: 3 },
  ])(
    'BR-41: NAME invalid queue ordinals fall back to kind-only Name suggestion — $label',
    ({ label, queuePosition, queueTotal }) => {
      render(
        <ReviewCardGroupShell
          kind="name"
          labelId={`acx-name-pos-${label}`}
          queuePosition={queuePosition}
          queueTotal={queueTotal}
          className="acx-suggestion-card acx-name-suggestion-card"
          data-testid="acx-review-card"
          data-review-kind="name"
        />,
      );

      const card = screen.getByTestId('acx-review-card');
      expect(card, label).toHaveAccessibleName('Name suggestion');
      expect(card, label).not.toHaveAccessibleName(/of 0|NaN|Infinity|1\.5|4 of 3/i);
    },
  );

  it('BR-41: NAME without queue ordinal has kind-only Name suggestion (never empty)', () => {
    render(
      <ReviewCardGroupShell
        kind="name"
        labelId="acx-name-pos-none"
        className="acx-suggestion-card acx-name-suggestion-card"
        data-testid="acx-review-card"
        data-review-kind="name"
      />,
    );

    const card = screen.getByTestId('acx-review-card');
    expect(card).toHaveAccessibleName('Name suggestion');
    expect(screen.queryByText(/Name suggestion \d+ of \d+/)).toBeNull();
  });

  it('curate control on a name card reports the cluster id upward (UXW2-3-R3-01)', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'name-1',
          cluster_id: 'cluster-name-1',
          suggested_name: 'Morgan',
          confidence_score: 0.91,
          source: 'test',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
      ],
      limit: 25,
      offset: 0,
    });

    const onLabel = vi.fn();
    renderQueue({ onLabel });

    await screen.findByText(/Suggested name:/);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Merge or split this group' }));
    expect(onLabel).toHaveBeenCalledWith('cluster-name-1');
  });

  it('shows person-commit as primary on NAME cards with disclosure', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'name-1',
          cluster_id: 'cluster-name-1',
          suggested_name: 'Morgan',
          confidence_score: 0.91,
          source: 'test',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
      ],
      limit: 25,
      offset: 0,
    });

    renderQueue();

    await screen.findByText(/Suggested name:/);
    const commit = screen.getByTestId('acx-person-commit');
    expect(commit).toHaveAttribute('data-person-commit-primary', 'true');
    expect(screen.getByText(MODEL_OUTPUT_DISCLOSURE)).toBeInTheDocument();
  });

  it('shows person-commit as primary on CLUSTER cards', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [
        {
          id: 'cluster-top-1',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 4,
          user_confirmed: false,
          suggested_label: null,
          suggested_target_cluster_id: null,
          representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
        },
      ],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    renderQueue();

    await screen.findByTestId('acx-review-card');
    expect(screen.getByTestId('acx-person-commit')).toHaveAttribute('data-person-commit-primary', 'true');
  });

  it('person-commit confirm calls commitClusterToRosterEntry not updateClusterLabel', async () => {
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

    const user = userEvent.setup();
    renderQueue();

    await screen.findByTestId('acx-person-commit');
    // Type the existing roster name and commit with Enter (single gesture).
    await typePersonName(user, 'Alex');

    await waitFor(() => {
      expect(commitClusterToRosterEntry).toHaveBeenCalledWith({
        clusterId: 'cluster-1',
        rosterEntryId: 7,
        newEntryName: undefined,
      });
    });
    expect(updateClusterLabel).not.toHaveBeenCalled();
  });

  it('person-commit success renders View in roster → link to #/roster', async () => {
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
    vi.mocked(commitClusterToRosterEntry).mockResolvedValue(rosterCommitFixture());

    const user = userEvent.setup();
    renderQueue();

    await screen.findByTestId('acx-person-commit');
    await typePersonName(user, 'Alex');

    const link = await screen.findByRole('link', { name: VIEW_IN_ROSTER_COPY });
    expect(link).toHaveAttribute('href', viewInRosterHref('person-uuid-7'));
  });

  it('person-commit failure shows persistent role=alert with retry', async () => {
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
    vi.mocked(commitClusterToRosterEntry).mockRejectedValue(new Error('fail'));

    const user = userEvent.setup();
    renderQueue();

    await screen.findByTestId('acx-person-commit');
    await typePersonName(user, 'Alex');

    const alert = await screen.findByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(within(alert).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('no just-label tertiary control renders on the queue card (UXW2-3)', async () => {
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

    renderQueue();

    await screen.findByTestId('acx-person-commit');
    // Naming always creates/binds a roster person — the misleading tertiary path is retired.
    expect(screen.queryByRole('button', { name: /just label/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/don't add to roster/i)).not.toBeInTheDocument();
  });

  it('person-commit while accept hold is open flushes held accept first', async () => {
    const order: string[] = [];
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
    vi.mocked(acceptSuggestion).mockImplementation((id: string) => {
      order.push(`accept:${id}`);
      return Promise.resolve({
        suggestion_id: id,
        resolution: 'accepted' as const,
        identity_id: 'identity-1',
        cluster_id: 'cluster-1',
        message: 'ok',
      });
    });
    vi.mocked(commitClusterToRosterEntry).mockImplementation(() => {
      order.push('person-commit');
      return Promise.resolve(rosterCommitFixture());
    });

    const user = userEvent.setup();
    renderQueue();

    const yes = await screen.findByRole('button', { name: 'Yes' });
    // Open hold without expiring it.
    await user.click(yes);
    expect(screen.getByText(HOLD_STATUS_COPY)).toBeInTheDocument();
    expect(acceptSuggestion).not.toHaveBeenCalled();

    await typePersonName(user, 'Alex');

    await waitFor(() => {
      expect(commitClusterToRosterEntry).toHaveBeenCalled();
    });
    expect(order[0]).toBe('accept:sugg-1');
    expect(order).toContain('person-commit');
    expect(order.indexOf('accept:sugg-1')).toBeLessThan(order.indexOf('person-commit'));
  });

  it('BR-27: focus on NAME card lands on person-commit combobox/confirm (not demoted Accept)', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'name-1',
          cluster_id: 'cluster-name-1',
          suggested_name: 'Morgan',
          confidence_score: 0.91,
          source: 'test',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
      ],
      limit: 25,
      offset: 0,
    });

    const queueRef = React.createRef<ReviewQueueHandle>();
    renderQueue({ queueRef });

    await screen.findByTestId('acx-review-card');
    expect(screen.getByTestId('acx-review-card')).toHaveAttribute('data-review-kind', 'name');

    act(() => {
      queueRef.current?.focusCurrentCard();
    });

    const focused = document.activeElement as HTMLElement | null;
    expect(focused).not.toBe(document.body);
    expect(focused?.closest('[data-testid="acx-person-commit"]')).not.toBeNull();
    // Demoted Accept suggestion must not steal primacy.
    expect(focused?.classList.contains('acx-suggestion-card__accept')).toBe(false);
    // R6-02: prefilled Save must not be the first stop — operator lands in the name field.
    expect(focused).toBe(screen.getByRole('combobox', { name: PERSON_COMMIT_COMBOBOX_ARIA }));
  });

  it('BR-27: focus on CLUSTER with nothing selected lands on enabled person-commit control', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [
        {
          id: 'cluster-top-1',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 4,
          user_confirmed: false,
          suggested_label: null,
          suggested_target_cluster_id: null,
          representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
        },
      ],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const queueRef = React.createRef<ReviewQueueHandle>();
    renderQueue({ queueRef });

    await screen.findByTestId('acx-review-card');
    expect(screen.getByTestId('acx-review-card')).toHaveAttribute('data-review-kind', 'cluster');

    act(() => {
      queueRef.current?.focusCurrentCard();
    });

    const focused = document.activeElement as HTMLElement | null;
    expect(focused).not.toBe(document.body);
    expect(focused?.closest('[data-testid="acx-person-commit"]')).not.toBeNull();
    expect((focused as HTMLButtonElement | null)?.disabled).not.toBe(true);
  });

  it('BR-30: person-commit failure after accept advances shows queue-level alert; retry fires 1 POST', async () => {
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

    let rejectPerson!: (reason?: unknown) => void;
    const personGate = new Promise<RosterClusterCommitResponse>((_resolve, reject) => {
      rejectPerson = reject;
    });
    // First call hangs until we reject (after accept advanced).
    vi.mocked(commitClusterToRosterEntry)
      .mockImplementationOnce(() => personGate)
      .mockResolvedValueOnce(rosterCommitFixture());
    // Prevent invalidate refetch from restoring the accepted row while person-commit is open.
    vi.mocked(acceptSuggestion).mockImplementation((id: string) => {
      vi.mocked(fetchPendingSuggestions).mockResolvedValue({
        suggestions: [
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

    const yes = await screen.findByRole('button', { name: 'Yes' });
    // Hold accept open, then person-commit flushes it.
    await user.click(yes);
    expect(screen.getByText(HOLD_STATUS_COPY)).toBeInTheDocument();

    await typePersonName(user, 'Alex');

    // Accept flushed → card advanced to sugg-2 before person-commit settles.
    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalledWith('sugg-1');
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Jordan/);
    });

    await act(async () => {
      rejectPerson(new Error('network'));
      await Promise.resolve();
      await Promise.resolve();
    });

    const fallback = await screen.findByTestId('acx-person-commit-queue-fallback');
    expect(fallback).toHaveAttribute('role', 'alert');
    const retry = within(fallback).getByRole('button', { name: 'Retry' });
    await user.click(retry);

    await waitFor(() => {
      expect(commitClusterToRosterEntry).toHaveBeenCalledTimes(2);
    });
  });

  it('E21-14-BR-16: top-unlabeled 500 shows error+retry, not drain or retired copy', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        bodyPreview: 'acx_projection_query_failed',
        message: 'projection query failed',
      }),
    );

    renderQueue();

    const error = await screen.findByTestId('acx-review-queue-top-unlabeled-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(error).toHaveTextContent('Unable to load unlabeled faces.');
    expect(within(error).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByText(REVIEW_QUEUE_DRAIN_MESSAGE)).not.toBeInTheDocument();
    expect(screen.queryByText('These faces are no longer available.')).not.toBeInTheDocument();
  });

  // UI-05: Retry must re-invoke the top-unlabeled query (not a decorative button).
  it('UI-05: top-unlabeled error Retry re-invokes fetchTopUnlabeledClusters', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    const topMock = vi.mocked(fetchTopUnlabeledClusters);
    topMock.mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        bodyPreview: 'acx_projection_query_failed',
        message: 'projection query failed',
      }),
    );

    renderQueue();

    const error = await screen.findByTestId('acx-review-queue-top-unlabeled-error');
    const callsBefore = topMock.mock.calls.length;

    await userEvent.click(within(error).getByRole('button', { name: 'Retry' }));

    await waitFor(() => {
      expect(topMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  // UI-04: draining the queue while top-unlabeled is in error must not announce "all caught up".
  it('UI-04: drain announcement uses error copy when top-unlabeled failed', async () => {
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
    // After the only assignment is accepted, top-unlabeled stays failed so the
    // drain path must announce the failure rather than "all caught up".
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        bodyPreview: 'acx_projection_query_failed',
        message: 'projection query failed',
      }),
    );

    renderQueue();

    await clickAndCommitHold(await screen.findByRole('button', { name: 'Yes' }));
    await waitFor(() => {
      expect(acceptSuggestion).toHaveBeenCalled();
    });
    await waitFor(() => {
      const statuses = screen.getAllByRole('status');
      expect(
        statuses.some((node) => within(node).queryByText('Unable to load unlabeled faces.')),
      ).toBe(true);
    });
    expect(screen.queryByText(REVIEW_QUEUE_DRAIN_MESSAGE)).not.toBeInTheDocument();
  });

  // UI-06: position chrome must not claim a measured "0 of 0" while top-unlabeled failed.
  it('UI-06: empty queue position is indeterminate when top-unlabeled failed', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        bodyPreview: 'acx_projection_query_failed',
        message: 'projection query failed',
      }),
    );

    renderQueue();

    await screen.findByTestId('acx-review-queue-top-unlabeled-error');
    expect(screen.queryByText('0 of 0')).not.toBeInTheDocument();
    // A bare em dash announces as punctuation in the aria-live position span;
    // AT must hear an explicit phrase instead.
    const position = document.querySelector('.acx-review-queue__position');
    expect(position).toHaveTextContent('Position unavailable');
    expect(position?.textContent).not.toBe('—');
  });

  // [rg-003] a top-unlabeled 500 must not remove the Clear-filters escape hatch
  // while filters are hiding real pending work.
  it('E21-14: top-unlabeled 500 keeps the Clear filters escape hatch and announces both states', async () => {
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
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        bodyPreview: 'acx_projection_query_failed',
        message: 'projection query failed',
      }),
    );

    const user = userEvent.setup();
    renderQueue();

    // Real pending work exists (one assignment) before the filter is applied.
    await screen.findByText(/Is this/);

    // Filter to a kind with no items → filtered-empty-with-work under the outage.
    await user.click(screen.getByRole('button', { name: 'Possible duplicates' }));

    const error = await screen.findByTestId('acx-review-queue-top-unlabeled-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(screen.getByText('No items match the current filters.')).toBeInTheDocument();
    const clearBtn = screen.getByRole('button', { name: 'Clear filters' });
    expect(clearBtn).toBeInTheDocument();
    expect(screen.queryByText(REVIEW_QUEUE_DRAIN_MESSAGE)).not.toBeInTheDocument();

    // The live region must announce the outage AND the filtered-empty hint.
    await waitFor(() => {
      const live = document.querySelector('.acx-review-queue__live');
      expect(live).toHaveTextContent('Unable to load unlabeled faces.');
      expect(live).toHaveTextContent('No items match the current filters.');
    });

    // The escape hatch still works: clearing filters brings the work back.
    await user.click(clearBtn);
    await waitFor(() => {
      expect(screen.getByTestId('acx-review-card')).toBeInTheDocument();
    });
  });

  it('E21-14-BR-16: topUnlabeledQuery sets retry:false (no automatic 500 reattempts)', async () => {
    // Client defaults intentionally omit retry:false so the per-query option is the only guard.
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retryDelay: 0 },
      },
    });
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        bodyPreview: 'acx_projection_query_failed',
        message: 'projection query failed',
      }),
    );

    render(withQueueProviders(queryClient, <ReviewQueueHarness />));

    await screen.findByTestId('acx-review-queue-top-unlabeled-error');
    // Without per-query retry:false, React Query would re-fire ~3 times (4 total).
    expect(fetchTopUnlabeledClusters).toHaveBeenCalledTimes(1);
  });

  it('E21-14-BR-16: top-unlabeled failure keeps assignment cards and surfaces retry', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-keep-1',
          identity_id: 'identity-keep-1',
          suggested_cluster_id: 'cluster-keep-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        bodyPreview: 'acx_projection_query_failed',
        message: 'projection query failed',
      }),
    );

    renderQueue();

    await screen.findByTestId('acx-review-card');
    expect(await screen.findByTestId('acx-review-queue-top-unlabeled-error')).toBeInTheDocument();
    expect(screen.queryByText('Failed to load suggestions.')).not.toBeInTheDocument();
  });

  // E21-20-REV1-02 / TEST-15: S2-gated zeros leave the queue empty while work exists.
  it('REV1-02: empty queue with zero-evidence clusters shows repair copy, not drain', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [
        {
          id: 'zero-1',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 0,
          user_confirmed: false,
          suggested_label: null,
          suggested_target_cluster_id: null,
          representatives: [{ id: 'rep-zero', media_id: 1, is_pinned: false }],
        },
        {
          id: 'zero-2',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 4,
          user_confirmed: false,
          suggested_label: null,
          suggested_target_cluster_id: null,
          representatives: [],
        },
      ],
      limit: 20,
      total: 2,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    renderQueue();

    expect(await screen.findByText('2 groups missing face data')).toBeInTheDocument();
    expect(screen.getByText(REVIEW_QUEUE_DRAIN_MESSAGE)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Resync' })).toBeInTheDocument();
    expect(screen.queryByTestId('acx-review-card')).not.toBeInTheDocument();
  });

  // REV2-09 / TEST-15: repair copy without Resync is a dead end. Dropping
  // refetchTopUnlabeled (or omitting the button) leaves this call count at 1.
  it('REV2-09: empty-queue Resync refetches top-unlabeled and keeps the drain confirmation', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    const topMock = vi.mocked(fetchTopUnlabeledClusters);
    topMock.mockResolvedValue({
      clusters: [
        {
          id: 'zero-1',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 0,
          user_confirmed: false,
          suggested_label: null,
          suggested_target_cluster_id: null,
          representatives: [{ id: 'rep-zero', media_id: 1, is_pinned: false }],
        },
      ],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    renderQueue();

    expect(await screen.findByText(REVIEW_QUEUE_DRAIN_MESSAGE)).toBeInTheDocument();
    expect(screen.getByText('1 group missing face data')).toBeInTheDocument();
    const resync = screen.getByRole('button', { name: 'Resync' });
    expect(resync.closest('[role="status"]')).toBeNull();
    expect(resync).toHaveAttribute('aria-describedby', 'acx-review-queue-repair-copy');
    const callsBefore = topMock.mock.calls.length;

    await userEvent.click(resync);

    await waitFor(() => {
      expect(topMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
    expect(screen.getByText(REVIEW_QUEUE_DRAIN_MESSAGE)).toBeInTheDocument();
  });

  // REV2-08 / TEST-15: queue Retry must refetch name suggestions too.
  // Omitting data.refetchName() leaves this call count at the initial 1.
  it('REV2-08: error Retry refetches name suggestions with the other findings queries', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.ENDPOINT_ERROR,
    });

    renderQueue();

    const retry = await screen.findByRole('button', { name: 'Retry' });
    expect(fetchPendingNameSuggestions).toHaveBeenCalledTimes(1);

    await userEvent.click(retry);

    await waitFor(() => {
      expect(fetchPendingNameSuggestions).toHaveBeenCalledTimes(2);
      expect(fetchPendingSuggestions).toHaveBeenCalledTimes(2);
      expect(fetchPendingMergeSuggestions).toHaveBeenCalledTimes(2);
      expect(fetchTopUnlabeledClusters).toHaveBeenCalledTimes(2);
    });
  });

  // REV4-02 / TEST-15: RQ v5 refetch() resolves on query error and isLoading
  // stays false while an already-errored query refetches. Queue Retry must
  // announce in-flight busy, then inspect settled isError for distinct copy.
  it('REV4-02: queue Retry announces in-flight busy then distinct retry-failed copy', async () => {
    vi.mocked(fetchPendingSuggestions).mockRejectedValue(new Error('assignment down'));
    vi.mocked(fetchPendingMergeSuggestions).mockRejectedValue(new Error('merge down'));
    vi.mocked(fetchPendingNameSuggestions).mockRejectedValue(new Error('name down'));
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(new Error('top down'));

    renderQueue();

    const retry = await screen.findByRole('button', { name: 'Retry' });
    expect(screen.getByText('Failed to load suggestions.')).toBeInTheDocument();

    let rejectAssignment!: (reason?: unknown) => void;
    const assignmentGate = new Promise<PendingSuggestionsResponse>((_resolve, reject) => {
      rejectAssignment = reject;
    });
    vi.mocked(fetchPendingSuggestions).mockImplementation(() => assignmentGate);

    await userEvent.click(retry);

    expect(screen.getByText('Retrying suggestions…')).toBeInTheDocument();
    expect(retry).toHaveAttribute('aria-busy', 'true');

    await act(async () => {
      rejectAssignment(new Error('still down'));
      await assignmentGate.catch(() => undefined);
    });

    await waitFor(() => {
      expect(screen.getByText('Retry failed. Could not load suggestions.')).toBeInTheDocument();
    });
    expect(screen.queryByText('Retrying suggestions…')).not.toBeInTheDocument();
    expect(screen.queryByText('Failed to load suggestions.')).not.toBeInTheDocument();
  });

  // REV5-02 / TEST-15: isErrorBranch used to include `retrying`, so pressing
  // the unavailable EmptyStateWarning Retry unmounted it and dropped focus
  // to <body>. Keep that surface mounted and do not swap in the generic
  // "Retrying suggestions…" sentence.
  it('REV5-02: unavailable Retry keeps focus off body and configured-service copy', async () => {
    const unavailable: PendingSuggestionsResponse = {
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.UNAVAILABLE,
    };
    vi.mocked(fetchPendingSuggestions).mockResolvedValue(unavailable);
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.UNAVAILABLE,
    });

    renderQueue();

    const retry = await screen.findByRole('button', { name: 'Retry' });
    expect(screen.getByText('Suggestion service not configured')).toBeInTheDocument();

    let resolveAssignment!: (value: PendingSuggestionsResponse) => void;
    const assignmentGate = new Promise<PendingSuggestionsResponse>((resolve) => {
      resolveAssignment = resolve;
    });
    vi.mocked(fetchPendingSuggestions).mockImplementation(() => assignmentGate);

    retry.focus();
    await userEvent.click(retry);

    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Retry' }));
    expect(screen.getByText('Suggestion service not configured')).toBeInTheDocument();
    expect(screen.queryByText('Retrying suggestions…')).not.toBeInTheDocument();

    await act(async () => {
      resolveAssignment(unavailable);
      await assignmentGate;
    });
  });

  // REV5-03 / TEST-15: QueryRetryButton's in-flight status unmounts when
  // retrying flips false. Settled retry-failed copy must be queryable via
  // the same role=status / aria-live wrapper the findings panel uses.
  it('REV5-03: settled retry-failed copy is announced via a live region', async () => {
    vi.mocked(fetchPendingSuggestions).mockRejectedValue(new Error('assignment down'));
    vi.mocked(fetchPendingMergeSuggestions).mockRejectedValue(new Error('merge down'));
    vi.mocked(fetchPendingNameSuggestions).mockRejectedValue(new Error('name down'));
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(new Error('top down'));

    renderQueue();

    const retry = await screen.findByRole('button', { name: 'Retry' });
    await userEvent.click(retry);

    await waitFor(() => {
      expect(screen.getByText('Retry failed. Could not load suggestions.')).toBeInTheDocument();
    });

    const live = screen.getByRole('status');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(within(live).getByText('Retry failed. Could not load suggestions.')).toBeInTheDocument();
  });

  // REV6-01 / TEST-15: queue Retry latches retryFailed while the unavailable
  // EmptyStateWarning still masks isErrorBranch. A later sibling panel Retry
  // refetches the same four queries to success. Without a reset keyed on
  // data.isError && findings.isError, retryFailed stays true and the queue
  // swaps to "Retry failed. Could not load suggestions." over live counts.
  it('REV6-01: sibling recovery after a masked unavailable Retry does not keep retry-failed copy', async () => {
    const unavailable: PendingSuggestionsResponse = {
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.UNAVAILABLE,
    };
    vi.mocked(fetchPendingSuggestions).mockResolvedValue(unavailable);
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.UNAVAILABLE,
    });

    const { queryClient } = renderQueue();

    const retry = await screen.findByRole('button', { name: 'Retry' });
    expect(screen.getByText('Suggestion service not configured')).toBeInTheDocument();

    vi.mocked(fetchPendingSuggestions).mockRejectedValue(new Error('assignment still down'));
    vi.mocked(fetchPendingMergeSuggestions).mockRejectedValue(new Error('merge still down'));
    vi.mocked(fetchPendingNameSuggestions).mockRejectedValue(new Error('name still down'));
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(new Error('top still down'));

    await userEvent.click(retry);

    await waitFor(() => {
      expect(vi.mocked(fetchPendingSuggestions).mock.calls.length).toBeGreaterThan(1);
    });
    expect(screen.getByText('Suggestion service not configured')).toBeInTheDocument();
    expect(screen.queryByText('Retry failed. Could not load suggestions.')).not.toBeInTheDocument();

    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-recovered',
          identity_id: 'identity-recovered',
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
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    // Panel Retry refetches the same queries without calling retrySuggestionQueries.
    await act(async () => {
      await queryClient.refetchQueries();
    });

    await waitFor(() => {
      expect(screen.queryByText('Retry failed. Could not load suggestions.')).not.toBeInTheDocument();
    });
    expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Is this\s*Alex/);
  });

  it('BR-31: CLUSTER card renders Review members affordance and drives onReview', async () => {
    const onReview = vi.fn();
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [
        {
          id: 'cluster-top-1',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 4,
          user_confirmed: false,
          suggested_label: null,
          suggested_target_cluster_id: null,
          representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false }],
        },
      ],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, retryDelay: 0 } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MergeSurvivorProvider>
          <ReviewQueueHarness onReview={onReview} />
        </MergeSurvivorProvider>
      </QueryClientProvider>,
    );

    await screen.findByTestId('acx-review-card');
    const reviewBtn = screen.getByRole('button', { name: 'Review' });
    await user.click(reviewBtn);
    expect(onReview).toHaveBeenCalledWith('cluster-top-1');
  });

  it('BR-34: null-clusterId assignment item renders no person-commit chrome', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-null',
          identity_id: 'identity-null',
          // Runtime null — matrix hides person-commit; item.clusterId is authoritative (no fallback).
          suggested_cluster_id: null as unknown as string,
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    });

    renderQueue();
    await screen.findByRole('button', { name: 'Yes' });
    expect(screen.queryByTestId('acx-person-commit')).not.toBeInTheDocument();
  });

  it('BR-35/UXW2-3: a substring of an existing name still creates a new person in one gesture', async () => {
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

    const user = userEvent.setup();
    renderQueue();
    const commit = await screen.findByTestId('acx-person-commit');

    // Type a substring of existing "Alex" — not an exact match, so Enter creates.
    const input = within(commit).getByRole('combobox', { name: PERSON_COMMIT_COMBOBOX_ARIA });
    await user.type(input, 'Al{Enter}');

    await waitFor(() => {
      expect(commitClusterToRosterEntry).toHaveBeenCalledWith({
        clusterId: 'cluster-1',
        rosterEntryId: undefined,
        newEntryName: 'Al',
      });
    });
  });

  describe('Slice 5 multi-select bulk + matrix M1 surface', () => {
    const seedMariaGroup = () => {
      vi.mocked(fetchPendingSuggestions).mockResolvedValue({
        suggestions: [
          {
            id: 'sugg-m1',
            identity_id: 'identity-m1',
            suggested_cluster_id: 'cluster-maria',
            representative_similarity: 0.95,
            avg_member_similarity: 0.9,
            cluster_label: 'Maria',
            cluster_identity_count: 5,
          },
          {
            id: 'sugg-m2',
            identity_id: 'identity-m2',
            suggested_cluster_id: 'cluster-maria',
            representative_similarity: 0.9,
            avg_member_similarity: 0.85,
            cluster_label: 'Maria',
            cluster_identity_count: 5,
          },
        ],
        limit: 10,
        offset: 0,
      });
    };

    it('default-empty selection tray; Select toggles; PR-38 Accept N for label; zero bulk-accept', async () => {
      seedMariaGroup();
      vi.mocked(acceptSuggestion).mockImplementation((id: string) =>
        Promise.resolve({
          suggestion_id: id,
          resolution: 'accepted' as const,
          identity_id: `identity-${id}`,
          cluster_id: 'cluster-maria',
          message: 'ok',
        }),
      );
      vi.mocked(fetchClusterMembers).mockResolvedValue({
        members: [],
        limit: 25,
        total: 2,
        truncated: false,
      });

      const user = userEvent.setup();
      renderQueue();

      await screen.findByRole('button', { name: 'Yes' });
      expect(screen.getByTestId('acx-review-selection-tray')).toHaveTextContent('0 selected');
      expect(screen.getAllByTestId('acx-review-card')).toHaveLength(1);

      await user.click(screen.getByTestId('acx-review-select'));
      expect(screen.getByTestId('acx-review-selection-tray')).toHaveTextContent('1 selected');

      await user.click(screen.getByRole('button', { name: 'Next review item' }));
      await waitFor(() => {
        expect(screen.getByTestId('acx-review-select')).toBeInTheDocument();
      });
      await user.click(screen.getByTestId('acx-review-select'));
      expect(screen.getByTestId('acx-review-selection-tray')).toHaveTextContent('2 selected');

      await user.click(screen.getByRole('button', { name: 'Review selection' }));
      expect(screen.getByTestId('acx-review-selection-panel')).toBeInTheDocument();
      expect(screen.getByTestId('acx-bulk-commit')).toHaveTextContent('Accept 2 for Maria');

      // Wait for truncation prefetch to settle (commit is disabled while loading).
      await waitFor(() => {
        expect(screen.getByTestId('acx-bulk-commit')).not.toBeDisabled();
      });

      // Arm hold under fake timers so UNDO_HOLD_MS advance is deterministic.
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      try {
        await act(async () => {
          screen.getByTestId('acx-bulk-commit').click();
          await Promise.resolve();
        });
        expect(screen.getByTestId('acx-bulk-hold')).toHaveTextContent('Saving 2… — Undo');
        expect(acceptSuggestion).not.toHaveBeenCalled();
        expect(bulkAcceptSuggestions).not.toHaveBeenCalled();

        await act(async () => {
          vi.advanceTimersByTime(UNDO_HOLD_MS);
          await Promise.resolve();
          await Promise.resolve();
          await Promise.resolve();
        });
      } finally {
        vi.useRealTimers();
      }

      await waitFor(() => {
        expect(acceptSuggestion).toHaveBeenCalled();
      });
      const mutated = vi.mocked(acceptSuggestion).mock.calls.map((c) => c[0]);
      expect(mutated).toEqual(['sugg-m1', 'sugg-m2']);
      expect(bulkAcceptSuggestions).not.toHaveBeenCalled();
    });

    it('BR-47: selected card disables single Accept/Reject with deselect reason; deselect re-enables', async () => {
      seedMariaGroup();
      const user = userEvent.setup();
      renderQueue();

      const yes = await screen.findByRole('button', { name: 'Yes' });
      const no = screen.getByRole('button', { name: 'No' });
      expect(yes).not.toBeDisabled();
      expect(no).not.toBeDisabled();

      await user.click(screen.getByTestId('acx-review-select'));
      expect(yes).toBeDisabled();
      expect(no).toBeDisabled();
      expect(yes).toHaveAttribute(
        'title',
        'Deselect this item to accept or reject it individually.',
      );
      expect(no).toHaveAttribute(
        'title',
        'Deselect this item to accept or reject it individually.',
      );

      await user.click(screen.getByTestId('acx-review-select'));
      expect(yes).not.toBeDisabled();
      expect(no).not.toBeDisabled();
    });

    it('BR-54: tray count changes announced via polite live region on select/deselect', async () => {
      seedMariaGroup();
      const user = userEvent.setup();
      const { container } = renderQueue();

      await screen.findByRole('button', { name: 'Yes' });
      // HARM-02: the live region is now seq-keyed (useAriaAnnounce), so it REMOUNTS
      // on each announce — re-query the current node inside waitFor rather than
      // holding a stale reference to the mount-time node.
      const liveRegion = container.querySelector('.acx-review-queue__live');
      expect(liveRegion).not.toBeNull();
      expect(liveRegion).toHaveAttribute('aria-live', 'polite');

      await user.click(screen.getByTestId('acx-review-select'));
      await waitFor(() => {
        expect(container.querySelector('.acx-review-queue__live')).toHaveTextContent('1 selected');
      });

      await user.click(screen.getByTestId('acx-review-select'));
      await waitFor(() => {
        expect(container.querySelector('.acx-review-queue__live')).toHaveTextContent('0 selected');
      });
    });

    it('bulk undo during hold = 0 POSTs', async () => {
      seedMariaGroup();
      vi.mocked(acceptSuggestion).mockClear();
      vi.mocked(fetchClusterMembers).mockResolvedValue({
        members: [],
        limit: 25,
        total: 2,
        truncated: false,
      });
      const user = userEvent.setup();
      renderQueue();
      await screen.findByRole('button', { name: 'Yes' });
      await user.click(screen.getByTestId('acx-review-select'));
      await user.click(screen.getByRole('button', { name: 'Review selection' }));
      await waitFor(() => {
        expect(screen.getByTestId('acx-bulk-commit')).not.toBeDisabled();
      });

      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      try {
        await act(async () => {
          screen.getByTestId('acx-bulk-commit').click();
          await Promise.resolve();
        });
        expect(screen.getByTestId('acx-bulk-hold')).toBeInTheDocument();
        act(() => {
          screen.getByRole('button', { name: 'Undo' }).click();
        });
        await act(async () => {
          vi.advanceTimersByTime(UNDO_HOLD_MS);
          await Promise.resolve();
        });
      } finally {
        vi.useRealTimers();
      }
      expect(acceptSuggestion).not.toHaveBeenCalled();
      expect(bulkAcceptSuggestions).not.toHaveBeenCalled();
    });

    it('truncation gate: truncated target disables commit until total-N confirm', async () => {
      seedMariaGroup();
      vi.mocked(fetchClusterMembers).mockResolvedValue({
        members: [
          {
            identity_id: 'i1',
            media_id: 1,
            similarity: 0.9,
            confidence: 0.9,
            bbox: { x: 0, y: 0, width: 1, height: 1 },
          },
        ],
        limit: 1,
        total: 12,
        truncated: true,
      });

      const user = userEvent.setup();
      renderQueue();
      await screen.findByRole('button', { name: 'Yes' });
      await user.click(screen.getByTestId('acx-review-select'));
      await user.click(screen.getByRole('button', { name: 'Review selection' }));

      await waitFor(() => {
        expect(screen.getByTestId('acx-bulk-commit')).toBeDisabled();
      });
      expect(screen.getByTestId('acx-review-selection-panel')).toHaveTextContent(/12 total/);

      await user.click(screen.getByRole('button', { name: /Confirm 12 total/i }));
      expect(screen.getByTestId('acx-bulk-commit')).not.toBeDisabled();
    });

    it('selection survives panel round-trip (lifted selectedIds)', async () => {
      seedMariaGroup();
      const user = userEvent.setup();

      const Parent = (): React.JSX.Element => {
        const [index, setIndex] = React.useState(0);
        const [kind, setKind] = React.useState<ReviewQueueKindParam>('all');
        const [band, setBand] = React.useState<ReviewQueueBandParam>('all');
        const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
        const [mounted, setMounted] = React.useState(true);
        return (
          <div>
            <button type="button" onClick={() => setMounted((v) => !v)}>
              toggle-panel
            </button>
            <span data-testid="selection-size">{selectedIds.size}</span>
            {mounted ? (
              <ReviewQueue
                index={index}
                onIndexChange={setIndex}
                kind={kind}
                onKindChange={setKind}
                band={band}
                onBandChange={setBand}
                selectedIds={selectedIds}
                onSelectedIdsChange={setSelectedIds}
              />
            ) : (
              <p>panel-mode</p>
            )}
          </div>
        );
      };

      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, retryDelay: 0 } },
      });
      render(
        <QueryClientProvider client={queryClient}>
          <MergeSurvivorProvider>
            <Parent />
          </MergeSurvivorProvider>
        </QueryClientProvider>,
      );

      await screen.findByRole('button', { name: 'Yes' });
      await user.click(screen.getByTestId('acx-review-select'));
      expect(screen.getByTestId('selection-size')).toHaveTextContent('1');

      await user.click(screen.getByRole('button', { name: 'toggle-panel' }));
      expect(screen.getByText('panel-mode')).toBeInTheDocument();
      expect(screen.getByTestId('selection-size')).toHaveTextContent('1');

      await user.click(screen.getByRole('button', { name: 'toggle-panel' }));
      await screen.findByRole('button', { name: 'Yes' });
      expect(screen.getByTestId('acx-review-selection-tray')).toHaveTextContent('1 selected');
      expect(screen.getByTestId('acx-review-select')).toHaveAttribute('aria-pressed', 'true');
    });
  });

  describe('Slice 6 band chips (④) + matrix M2 surface', () => {
    it('band chips filter queue by similarity post-eligibility; compose with KIND; merge excluded (BR-60)', async () => {
      vi.mocked(fetchPendingSuggestions).mockResolvedValue({
        suggestions: [
          {
            id: 'strong-1',
            identity_id: 'id-1',
            suggested_cluster_id: 'c-strong',
            representative_similarity: 0.5,
            cluster_label: 'Maria',
            cluster_identity_count: 3,
          },
          {
            id: 'weak-1',
            identity_id: 'id-2',
            suggested_cluster_id: 'c-weak',
            representative_similarity: 0.4,
            cluster_label: 'Alex',
            cluster_identity_count: 2,
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
          },
        ],
        limit: 10,
        offset: 0,
      });

      const user = userEvent.setup();
      renderQueue();

      await screen.findByText(/Is this/);
      // 2 assignments + 1 merge
      expect(screen.getByText('1 of 3')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Strong matches' })).toHaveAttribute(
        'aria-pressed',
        'false',
      );

      await user.click(screen.getByRole('button', { name: 'Strong matches' }));
      await waitFor(() => {
        // strong-1 (0.50) only — merge-1 excluded from bands (BR-60); weak-1 dropped
        expect(screen.getByText('1 of 1')).toBeInTheDocument();
      });
      expect(screen.getByRole('button', { name: 'Strong matches' })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Maria/);

      // KIND ∩ band: Close matches ∩ Strong → still only strong-1
      await user.click(screen.getByRole('button', { name: 'Close matches' }));
      await waitFor(() => {
        expect(screen.getByText('1 of 1')).toBeInTheDocument();
      });
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/Maria/);

      // Toggle band active → all (band clears; KIND still assignment)
      await user.click(screen.getByRole('button', { name: 'Strong matches' }));
      await waitFor(() => {
        // assignment only: strong + weak
        expect(screen.getByText('1 of 2')).toBeInTheDocument();
      });

      // Merge stays reachable under band=all via its KIND chip.
      await user.click(screen.getByRole('button', { name: 'Close matches' }));
      await user.click(screen.getByRole('button', { name: 'Possible duplicates' }));
      await waitFor(() => {
        expect(screen.getByText('1 of 1')).toBeInTheDocument();
      });
      // Merge ∩ strong band → empty (merge similarity is a different domain).
      await user.click(screen.getByRole('button', { name: 'Strong matches' }));
      await waitFor(() => {
        expect(screen.getByText('0 of 0')).toBeInTheDocument();
      });
    });

    it('matrix M2 surface: bulk preview/commit label uses selection ∩ band ∩ kind; fired ids = intersection (BR-61); split tray copy (BR-63)', async () => {
      vi.mocked(fetchPendingSuggestions).mockResolvedValue({
        suggestions: [
          {
            id: 's-strong',
            identity_id: 'id-1',
            suggested_cluster_id: 'c1',
            representative_similarity: 0.5,
            cluster_label: 'Maria',
            cluster_identity_count: 2,
          },
          {
            id: 's-weak',
            identity_id: 'id-2',
            suggested_cluster_id: 'c2',
            representative_similarity: 0.4,
            cluster_label: 'Alex',
            cluster_identity_count: 2,
          },
        ],
        limit: 10,
        offset: 0,
      });
      vi.mocked(fetchClusterMembers).mockResolvedValue({
        members: [],
        limit: 25,
        total: 2,
        truncated: false,
      });
      vi.mocked(acceptSuggestion).mockImplementation((id: string) =>
        Promise.resolve({
          suggestion_id: id,
          resolution: 'accepted' as const,
          identity_id: `identity-${id}`,
          cluster_id: 'c1',
          message: 'ok',
        }),
      );

      // Seed selection after settle (avoid prune-on-empty-queue wiping ids).
      const Parent = (): React.JSX.Element => {
        const [index, setIndex] = React.useState(0);
        const [kind, setKind] = React.useState<ReviewQueueKindParam>('all');
        const [band, setBand] = React.useState<ReviewQueueBandParam>('all');
        const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
        return (
          <div>
            <button
              type="button"
              data-testid="seed-selection"
              onClick={() => setSelectedIds(new Set(['s-strong', 's-weak']))}
            >
              seed
            </button>
            <button
              type="button"
              data-testid="apply-strong-band"
              onClick={() => {
                setBand('strong');
                setIndex(0);
              }}
            >
              strong-band
            </button>
            <ReviewQueue
              index={index}
              onIndexChange={setIndex}
              kind={kind}
              onKindChange={setKind}
              band={band}
              onBandChange={setBand}
              selectedIds={selectedIds}
              onSelectedIdsChange={setSelectedIds}
            />
          </div>
        );
      };

      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, retryDelay: 0 } },
      });
      const user = userEvent.setup();
      render(
        <QueryClientProvider client={queryClient}>
          <MergeSurvivorProvider>
            <Parent />
          </MergeSurvivorProvider>
        </QueryClientProvider>,
      );

      await waitFor(() => {
        expect(screen.getByText('1 of 2')).toBeInTheDocument();
      });
      await user.click(screen.getByTestId('seed-selection'));
      expect(screen.getByTestId('acx-review-selection-tray')).toHaveTextContent('2 selected');

      // Activate strong band → queue shows only s-strong; selection still 2.
      await user.click(screen.getByTestId('apply-strong-band'));
      await waitFor(() => {
        expect(screen.getByText('1 of 1')).toBeInTheDocument();
      });
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent('Maria');
      // BR-63: split copy — selection extends beyond the active filter view.
      expect(screen.getByTestId('acx-review-selection-tray')).toHaveTextContent(
        '2 selected — 1 in current filter',
      );

      await user.click(screen.getByRole('button', { name: 'Review selection' }));

      // Commit label + preview count only the filter-visible selection (M2 exact-id).
      await waitFor(() => {
        expect(screen.getByTestId('acx-bulk-commit')).toHaveTextContent('Accept 1 for Maria');
      });
      const preview = screen.getByTestId('acx-review-selection-panel');
      expect(within(preview).getAllByRole('listitem')).toHaveLength(1);

      // BR-61 (TEST-08): fire the bulk hold under the active band×kind — the
      // exact acceptSuggestion id set equals the selection ∩ filters intersection.
      await waitFor(() => {
        expect(screen.getByTestId('acx-bulk-commit')).not.toBeDisabled();
      });
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      try {
        await act(async () => {
          screen.getByTestId('acx-bulk-commit').click();
          await Promise.resolve();
        });
        expect(screen.getByTestId('acx-bulk-hold')).toHaveTextContent('Saving 1… — Undo');
        await act(async () => {
          vi.advanceTimersByTime(UNDO_HOLD_MS);
          await Promise.resolve();
          await Promise.resolve();
          await Promise.resolve();
        });
      } finally {
        vi.useRealTimers();
      }

      await waitFor(() => {
        expect(acceptSuggestion).toHaveBeenCalled();
      });
      const mutated = vi.mocked(acceptSuggestion).mock.calls.map((c) => c[0]);
      expect(mutated).toEqual(['s-strong']);
      expect(mutated).not.toContain('s-weak');
      expect(bulkAcceptSuggestions).not.toHaveBeenCalled();
    });

    it('BR-59: truncation gate keys off the filter-intersected selection only', async () => {
      // s-strong targets c-ok (not truncated); s-weak targets c-trunc (truncated).
      vi.mocked(fetchPendingSuggestions).mockResolvedValue({
        suggestions: [
          {
            id: 's-strong',
            identity_id: 'id-1',
            suggested_cluster_id: 'c-ok',
            representative_similarity: 0.5,
            cluster_label: 'Maria',
            cluster_identity_count: 2,
          },
          {
            id: 's-weak',
            identity_id: 'id-2',
            suggested_cluster_id: 'c-trunc',
            representative_similarity: 0.4,
            cluster_label: 'Alex',
            cluster_identity_count: 12,
          },
        ],
        limit: 10,
        offset: 0,
      });
      vi.mocked(fetchClusterMembers).mockImplementation((clusterId: string) =>
        clusterId === 'c-trunc'
          ? Promise.resolve({
              members: [
                {
                  identity_id: 'i1',
                  media_id: 1,
                  similarity: 0.9,
                  confidence: 0.9,
                  bbox: { x: 0, y: 0, width: 1, height: 1 },
                },
              ],
              limit: 1,
              total: 12,
              truncated: true,
            })
          : Promise.resolve({
              members: [],
              limit: 25,
              total: 2,
              truncated: false,
            }),
      );

      const Parent = (): React.JSX.Element => {
        const [index, setIndex] = React.useState(0);
        const [kind, setKind] = React.useState<ReviewQueueKindParam>('all');
        const [band, setBand] = React.useState<ReviewQueueBandParam>('all');
        const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
        return (
          <div>
            <button
              type="button"
              data-testid="seed-selection"
              onClick={() => setSelectedIds(new Set(['s-strong', 's-weak']))}
            >
              seed
            </button>
            <button
              type="button"
              data-testid="apply-strong-band"
              onClick={() => {
                setBand('strong');
                setIndex(0);
              }}
            >
              strong-band
            </button>
            <button
              type="button"
              data-testid="apply-all-band"
              onClick={() => {
                setBand('all');
                setIndex(0);
              }}
            >
              all-band
            </button>
            <ReviewQueue
              index={index}
              onIndexChange={setIndex}
              kind={kind}
              onKindChange={setKind}
              band={band}
              onBandChange={setBand}
              selectedIds={selectedIds}
              onSelectedIdsChange={setSelectedIds}
            />
          </div>
        );
      };

      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, retryDelay: 0 } },
      });
      const user = userEvent.setup();
      render(
        <QueryClientProvider client={queryClient}>
          <MergeSurvivorProvider>
            <Parent />
          </MergeSurvivorProvider>
        </QueryClientProvider>,
      );

      await waitFor(() => {
        expect(screen.getByText('1 of 2')).toBeInTheDocument();
      });
      await user.click(screen.getByTestId('seed-selection'));

      // Strong band: truncated c-trunc is filtered OUT of the commit set → not blocked.
      await user.click(screen.getByTestId('apply-strong-band'));
      await user.click(screen.getByRole('button', { name: 'Review selection' }));
      await waitFor(() => {
        expect(screen.getByTestId('acx-bulk-commit')).not.toBeDisabled();
      });
      expect(screen.queryByRole('button', { name: /Confirm 12 total/i })).not.toBeInTheDocument();

      // band=all: truncated target back in the commit set → gate blocks as before.
      await user.click(screen.getByTestId('apply-all-band'));
      await waitFor(() => {
        expect(screen.getByTestId('acx-bulk-commit')).toBeDisabled();
      });
      expect(screen.getByRole('button', { name: /Confirm 12 total/i })).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: /Confirm 12 total/i }));
      await waitFor(() => {
        expect(screen.getByTestId('acx-bulk-commit')).not.toBeDisabled();
      });
    });

    it('rq= band initial state filters on mount (round-trip seed)', async () => {
      vi.mocked(fetchPendingSuggestions).mockResolvedValue({
        suggestions: [
          {
            id: 's-strong',
            identity_id: 'id-1',
            suggested_cluster_id: 'c1',
            representative_similarity: 0.5,
            cluster_label: 'StrongPerson',
            cluster_identity_count: 1,
          },
          {
            id: 's-weak',
            identity_id: 'id-2',
            suggested_cluster_id: 'c2',
            representative_similarity: 0.4,
            cluster_label: 'WeakPerson',
            cluster_identity_count: 1,
          },
        ],
        limit: 10,
        offset: 0,
      });

      renderQueue({ initialBand: 'weaker' });
      await waitFor(() => {
        expect(screen.getByText('1 of 1')).toBeInTheDocument();
      });
      expect(screen.getByTestId('acx-review-card')).toHaveTextContent(/WeakPerson/);
      expect(screen.getByRole('button', { name: 'Weaker matches' })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
    });
  });

  describe('open-target lifecycle (E21-5 Slice 7 / FBT-1 criterion 4)', () => {
    it('announces retirement and suppresses head card when head cluster 404s', async () => {
      vi.mocked(fetchPendingSuggestions).mockResolvedValue({
        suggestions: [
          {
            id: 'assign-live-1',
            identity_id: 'id-1',
            suggested_cluster_id: 'cluster-head',
            representative_similarity: 0.95,
            avg_member_similarity: 0.9,
            cluster_label: 'Alex',
            cluster_identity_count: 2,
          },
        ],
        limit: 50,
        offset: 0,
        data_source: DATA_SOURCE.LOCAL_PROJECTION,
      });
      vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
        suggestions: [],
        limit: 10,
        offset: 0,
      });
      vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
        suggestions: [],
        limit: 10,
        offset: 0,
      });
      vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
        clusters: [],
        limit: 20,
        total: 0,
        truncated: false,
        singleton_count: 0,
        data_source: DATA_SOURCE.LOCAL_PROJECTION,
      });
      vi.mocked(fetchClusterMembers).mockRejectedValue(
        new HTTPError({
          status: 404,
          retryAfterSeconds: undefined,
          endpoint: '/clusters/cluster-head/members',
          bodyPreview: 'cluster_not_found',
          message: 'not found',
        }),
      );

      renderQueue();

      await waitFor(() => {
        expect(screen.getByTestId('acx-review-queue-retired-head')).toBeInTheDocument();
      });
      expect(screen.getByRole('status')).toHaveTextContent(LIVE_TARGET_CLOSE_ANNOUNCE);
      // Criterion 4: no stale card body for the retired head cluster.
      expect(screen.queryByTestId('acx-review-card')).not.toBeInTheDocument();
    });
  });

  it('R6-03: deferred accept POST renders COMMITTING through the ReviewQueue passthrough', async () => {
    vi.mocked(fetchClusterMembers).mockResolvedValue({
      members: [],
      limit: 25,
      total: 0,
      truncated: false,
    });
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

    let resolveAccept: ((value: {
      suggestion_id: string;
      resolution: 'accepted';
      identity_id: string;
      cluster_id: string;
      message: string;
    }) => void) | null = null;
    vi.mocked(acceptSuggestion).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveAccept = resolve;
        }),
    );

    renderQueue();
    const yes = await screen.findByRole('button', { name: 'Yes' });

    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      act(() => {
        yes.click();
      });
      const holding = document.querySelector('.acx-review-queue__hold');
      expect(holding).toBeInstanceOf(HTMLElement);
      expect(holding).toHaveTextContent(HOLD_STATUS_COPY);
      expect(within(holding as HTMLElement).getByRole('button', { name: 'Undo' })).toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(UNDO_HOLD_MS);
        await Promise.resolve();
        await Promise.resolve();
      });

      const committing = document.querySelector('.acx-review-queue__hold');
      expect(committing).toBeInstanceOf(HTMLElement);
      expect(wholeHoldText(committing as HTMLElement)).toBe(HOLD_COMMITTING_STATUS_COPY);
      expect(wholeHoldText(committing as HTMLElement)).toBe('Saving…');
      expect(committing).not.toHaveTextContent('Undo');
      expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
      // R6-07: phase change remounts the polite live region so AT re-reads it.
      expect(committing).not.toBe(holding);

      await act(async () => {
        resolveAccept?.({
          suggestion_id: 'sugg-1',
          resolution: 'accepted',
          identity_id: 'identity-1',
          cluster_id: 'cluster-1',
          message: 'ok',
        });
        await Promise.resolve();
        await Promise.resolve();
      });
    } finally {
      vi.useRealTimers();
    }
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

  it('renders committing-phase role=status with HOLD_COMMITTING_STATUS_COPY and no Undo', () => {
    render(
      <div>
        <button type="button">Yes</button>
        <CommitHoldRegion
          phase="committing"
          errorMessage={null}
          onUndo={() => undefined}
          onRetry={() => undefined}
          onPausedChange={() => undefined}
        />
      </div>,
    );

    const status = screen.getByRole('status');
    // Whole-content pin: 'Saving…' is a prefix of the HOLDING copy, so
    // toHaveTextContent(string) cannot distinguish the phases (UXW2-3-R6-01).
    expect(wholeHoldText(status)).toBe(HOLD_COMMITTING_STATUS_COPY);
    expect(wholeHoldText(status)).toBe('Saving…');
    expect(status).not.toHaveTextContent('Undo');
  });

  it('CommitHoldRegion consumes HOLD_*_STATUS_COPY as SSOT (UXW2-3-R6-01)', () => {
    const source = readFileSync(
      path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../ReviewQueue.tsx'),
      'utf8',
    );
    expect(source).toMatch(/\bHOLD_STATUS_COPY\b/);
    expect(source).toMatch(/\bHOLD_COMMITTING_STATUS_COPY\b/);
    expect(source).not.toMatch(/__\(\s*'Saving…/);
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
