/**
 * WBUX-5-D-02 / B-01 / B-02 — toolbar status live region:
 * - always mounted before text arrives
 * - debounced so keystroke fetch churn does not re-announce [B-01]
 * - never carries per-correction success copy (row owns that) [B-02]
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MediaSelection } from '../MediaSelection';
import { MARK_DECORATIVE_SUCCESS_MESSAGE } from '../MediaAltSuggest';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

const STATUS_SENTENCE =
  'Showing 3 media items. 1 is marked decorative and will leave this view when the list next refreshes.';

/** Mutable statusMessage the WorkbenchMediaContext mock reads each render. */
let mockStatusMessage = STATUS_SENTENCE;
/** Mutable isStatusPending — gate for transient suppression [sr-007]. */
let mockIsStatusPending = false;

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({
    selection: {
      selection: {},
      selectedMedia: [],
      toggleRow: vi.fn(),
      toggleAll: vi.fn(),
      isPageFullySelected: () => false,
    },
    filters: {
      searchQuery: '',
      statusFilter: 'missing',
      currentPage: 1,
      perPage: 10,
      handleSearchChange: vi.fn(),
      clearSearch: vi.fn(),
      handleStatusChange: vi.fn(),
      setCurrentPage: vi.fn(),
      setPerPage: vi.fn(),
    },
    mediaQueue: {
      mediaQuery: {
        data: {
          items: [
            {
              id: 11,
              title: 'Photo',
              altText: null,
              isDecorative: false,
              status: 'missing',
              thumbnailUrl: null,
              mimeType: 'image/jpeg',
              editUrl: '#',
              updatedAt: '2026-01-01T00:00:00Z',
              dimensions: { width: 100, height: 100 },
              tags: [],
              identities: [],
            },
          ],
          total: 1,
          totalPages: 1,
        },
        isPending: false,
        isFetching: false,
        isError: false,
        isSuccess: true,
        refetch: vi.fn(),
        itemsWithIdentities: [
          {
            id: 11,
            title: 'Photo',
            altText: null,
            isDecorative: false,
            status: 'missing',
            thumbnailUrl: null,
            mimeType: 'image/jpeg',
            editUrl: '#',
            updatedAt: '2026-01-01T00:00:00Z',
            dimensions: { width: 100, height: 100 },
            tags: [],
            identities: [],
          },
        ],
        detailQuery: {
          data: undefined,
          isLoading: false,
          isError: false,
          isPending: false,
          isFetching: false,
          refetch: vi.fn(),
        },
        identitiesQuery: {
          data: { identities_by_media: {}, data_source: 'local_projection' },
          isLoading: false,
          isError: false,
          isPlaceholderData: false,
          isFetching: false,
          refetch: vi.fn(),
        },
      },
      get statusMessage() {
        return mockStatusMessage;
      },
      get isStatusPending() {
        return mockIsStatusPending;
      },
      detailTruncationNotice: null,
      hasIdentities: false,
    },
  }),
}));

vi.mock('../../../hooks/useBulkDescribe', () => ({
  useBulkDescribe: () => ({
    submit: { isPending: false, mutate: vi.fn(), error: null },
    cancel: { isPending: false, mutate: vi.fn(), error: null },
    progress: {
      status: null,
      run: null,
      isTerminal: false,
      isError: false,
      isPolling: false,
      etaSeconds: null,
      progressFraction: 0,
      retry: vi.fn(),
      error: null,
      stalledForSeconds: null,
      isFrozen: false,
    },
    runId: null,
  }),
}));

vi.mock('../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

vi.mock('../../../hooks/useRemoteActionGate', () => ({
  useRemoteActionGate: () => ({ title: undefined, 'aria-disabled': undefined }),
}));

vi.mock('../../../hooks/useRecognitionCooldown', () => ({
  useRecognitionCooldown: () => ({
    isCoolingDown: false,
    remainingSeconds: 0,
    remainingMs: 0,
  }),
}));

vi.mock('../MediaAnalyzeCta', () => ({
  MediaAnalyzeCta: () => null,
}));

vi.mock('../BulkDescribeReviewLink', () => ({
  BulkDescribeReviewLink: () => null,
}));

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({ scanRun: { isScanning: false, progress: null }, scan: vi.fn() }),
}));

vi.mock('../Panels', () => ({
  isClusteringActive: () => false,
  mediaEditUrl: (id: number) => `#edit-${id}`,
}));

const renderSelection = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MediaSelection />
    </QueryClientProvider>,
  );
};

/** Force a re-read of mockStatusMessage by re-rendering the tree. */
const rerenderSelection = (result: ReturnType<typeof renderSelection>) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  result.rerender(
    <QueryClientProvider client={client}>
      <MediaSelection />
    </QueryClientProvider>,
  );
};

describe('MediaSelection toolbar status announcement [WBUX-5-D-02][B-01][B-02]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    mockStatusMessage = STATUS_SENTENCE;
    mockIsStatusPending = false;
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('exposes settled status via an always-mounted role=status live region', () => {
    renderSelection();

    const live = screen.getByTestId('media-selection-toolbar-live-status');
    expect(live).toHaveAttribute('role', 'status');
    // Mounted before debounce fires — empty initially so the region exists first.
    expect(live.textContent).toBe('');

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(live.textContent).toBe(STATUS_SENTENCE);
    // Visual status (aria-hidden) still shows the message immediately.
    const visual = document.querySelector('.acx-media-selection__status [aria-hidden="true"]');
    expect(visual).toHaveTextContent(STATUS_SENTENCE);
  });

  it('does not churn the live region on rapid successive status changes [B-01]', () => {
    const view = renderSelection();
    const live = screen.getByTestId('media-selection-toolbar-live-status');
    // Snapshot the live region's text after every intermediate tick so a
    // pass-through (no debounce) mutation is observable — final-state-only
    // checks stay green under both implementations [TEST-15].
    const snapshots: string[] = [];

    // Rapid keystroke-driven message storm (pending interleaved with settled).
    // Pending flag (not message copy) drives suppression [sr-007].
    const rapid: { msg: string; pending: boolean }[] = [
      { msg: 'Updating media queue…', pending: true },
      { msg: 'Showing 1 media item.', pending: false },
      { msg: 'Updating media queue…', pending: true },
      { msg: 'Showing 2 media items.', pending: false },
      { msg: 'Updating media queue…', pending: true },
      { msg: 'Showing 3 media items.', pending: false },
    ];
    for (const { msg, pending } of rapid) {
      mockStatusMessage = msg;
      mockIsStatusPending = pending;
      rerenderSelection(view);
      act(() => {
        vi.advanceTimersByTime(200);
      });
      snapshots.push(live.textContent ?? '');
    }

    // Intermediate settled strings must not have been announced during the storm.
    expect(snapshots).not.toContain('Showing 1 media item.');
    expect(snapshots).not.toContain('Showing 2 media items.');
    // "Updating…" is never announced at any snapshot.
    expect(snapshots.some((s) => s.includes('Updating media queue'))).toBe(false);
    // Debounce still pending for the final settled candidate.
    expect(live.textContent).not.toBe('Showing 3 media items.');

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    // Only the final settled message lands after the quiet period.
    expect(live.textContent).toBe('Showing 3 media items.');
  });

  it('never announces the transient Updating media queue… message [B-01]', () => {
    mockStatusMessage = 'Updating media queue…';
    mockIsStatusPending = true;
    renderSelection();
    const live = screen.getByTestId('media-selection-toolbar-live-status');

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(live.textContent).toBe('');
    // Visual still shows the transient copy.
    const visual = document.querySelector('.acx-media-selection__status [aria-hidden="true"]');
    expect(visual?.textContent).toBe('Updating media queue…');
  });

  /**
   * Discriminator for "gate on isStatusPending" vs "string-equal English copy".
   * A copy edit in WorkbenchMediaContext must not silently re-enable thrash;
   * the boolean is the contract [sr-007][TEST-17].
   */
  it('suppresses announcement when isStatusPending even if message copy differs [CO-02]', () => {
    // Deliberately NOT the English "Updating media queue…" literal — if the
    // toolbar still compared display strings, this case would announce.
    mockStatusMessage = 'Queue is refreshing — please wait.';
    mockIsStatusPending = true;
    renderSelection();
    const live = screen.getByTestId('media-selection-toolbar-live-status');

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(live.textContent).toBe('');
    // Visual still shows whatever copy the context emitted.
    const visual = document.querySelector('.acx-media-selection__status [aria-hidden="true"]');
    expect(visual?.textContent).toBe('Queue is refreshing — please wait.');
  });

  it('row owns per-correction success; toolbar live region does not carry it [B-02]', () => {
    // Toolbar status is list-level reconciliation, never "Alt text saved." /
    // MARK_DECORATIVE_SUCCESS_MESSAGE — those belong on the row polite region.
    mockStatusMessage = STATUS_SENTENCE;
    renderSelection();
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    const live = screen.getByTestId('media-selection-toolbar-live-status');
    expect(live.textContent).not.toContain('Alt text saved.');
    expect(live.textContent).not.toContain(MARK_DECORATIVE_SUCCESS_MESSAGE);

    // Simulate a row correction success region coexisting in the document.
    const rowStatus = document.createElement('div');
    rowStatus.setAttribute('role', 'status');
    rowStatus.setAttribute('data-testid', 'media-selection-row-status');
    rowStatus.textContent = 'Alt text saved.';
    document.body.appendChild(rowStatus);

    const correctionCarriers = screen
      .getAllByRole('status')
      .filter((el) => (el.textContent ?? '').includes('Alt text saved.'));
    expect(correctionCarriers).toHaveLength(1);
    expect(correctionCarriers[0]).toHaveAttribute('data-testid', 'media-selection-row-status');

    rowStatus.remove();
  });
});
