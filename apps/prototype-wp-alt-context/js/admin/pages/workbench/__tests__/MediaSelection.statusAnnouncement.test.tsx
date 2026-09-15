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

import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import type { DescribeRunResponse, DescribeRunTiming } from '../../../api/describeApi';
import { BulkDescribeProgress, MediaSelection } from '../MediaSelection';
import { MARK_DECORATIVE_SUCCESS_MESSAGE } from '../MediaAltSuggest';
import gpuflowBulkTiming from './fixtures/gpuflow-bulk-timing.json';

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

const TERMINAL_STATUSES = new Set(['completed', 'completed_with_errors', 'failed', 'cancelled']);

const progressFromRun = (
  run: DescribeRunResponse,
  overrides: Partial<DescribeRunProgress> = {},
): DescribeRunProgress => ({
  run,
  status: run.status,
  progressFraction: run.total > 0 ? (run.completed + run.failed + run.skipped) / run.total : 0,
  etaSeconds: run.eta_seconds,
  gpuState: typeof run.gpu_state === 'string' ? (run.gpu_state as DescribeRunProgress['gpuState']) : null,
  isTerminal: TERMINAL_STATUSES.has(run.status),
  stalledForSeconds: null,
  isPolling: !TERMINAL_STATUSES.has(run.status),
  isFrozen: false,
  isError: false,
  error: null,
  retry: vi.fn(),
  timing: run.timing ?? null,
  startupId: run.startup_id ?? null,
  isWarming: false,
  ...overrides,
});

describe('MediaSelection bulk-describe timing announcement [GPUFLOW-1 B2]', () => {
  it('announces measured elapsed time on a terminal run without fabricating startup', () => {
    const run = gpuflowBulkTiming.run as DescribeRunResponse;
    render(<BulkDescribeProgress progress={progressFromRun(run)} onRetry={vi.fn()} />);

    const live = screen.getByRole('status');
    expect(live).toHaveTextContent('1 described, 1 failed in 0.04 s');
    expect(live).not.toHaveTextContent('GPU startup');
    expect(screen.getAllByRole('status')).toHaveLength(1);
    const visual = document.querySelector('.acx-media-selection__bulk-describe-status--success');
    expect(visual).toHaveAttribute('aria-hidden', 'true');
    expect(visual).toHaveTextContent('✔ 1 draft ready to review · 1 failed');
  });

  it('appends GPU startup seconds only when startup_ms is non-null', () => {
    const run = gpuflowBulkTiming.run as DescribeRunResponse;
    const timing: DescribeRunTiming = { ...run.timing!, startup_ms: 2500 };
    render(
      <BulkDescribeProgress
        progress={progressFromRun({ ...run, timing }, { timing })}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('1 described, 1 failed in 0.04 s (GPU startup 2.5 s)');
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it('keeps the legacy complete announcement when timing is absent', () => {
    expect(gpuflowBulkTiming.run_no_timing).not.toHaveProperty('timing');
    const run = gpuflowBulkTiming.run_no_timing as DescribeRunResponse;
    render(<BulkDescribeProgress progress={progressFromRun(run, { timing: null })} onRetry={vi.fn()} />);

    expect(screen.getByRole('status')).toHaveTextContent('✔ 1 draft ready to review · 1 failed');
    expect(screen.queryByText(/described,/)).toBeNull();
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it('announces Description service is starting once while isWarming, with no fabricated ETA', () => {
    const run = gpuflowBulkTiming.run_warming as DescribeRunResponse;
    const warming = progressFromRun(run, { isWarming: true, isTerminal: false, isPolling: true });
    const { rerender } = render(<BulkDescribeProgress progress={warming} onRetry={vi.fn()} />);

    const live = screen.getByRole('status');
    expect(live).toHaveTextContent('Description service is starting');
    expect(live).not.toHaveTextContent('2 min');
    expect(live).not.toHaveTextContent('remaining');
    expect(live).not.toHaveTextContent('calculating');
    expect(screen.queryByRole('progressbar')).toBeNull();
    expect(screen.getAllByRole('status')).toHaveLength(1);

    rerender(<BulkDescribeProgress progress={warming} onRetry={vi.fn()} />);
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.getByRole('status')).toHaveTextContent('Description service is starting');
  });
});
