/**
 * WBUX-5-D-02 — toolbar reconciliation/status sentence is a live status region.
 * AT users must hear mutations after operator actions (WCAG 2.1 AA 4.1.3).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MediaSelection } from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

// String literal inside vi.mock factory (hoisted) — outer consts are not closed over.
const STATUS_SENTENCE =
  'Showing 3 media items. 1 marked decorative and will leave this view when the list next refreshes.';

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
      statusMessage:
        'Showing 3 media items. 1 marked decorative and will leave this view when the list next refreshes.',
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

describe('MediaSelection toolbar status announcement [WBUX-5-D-02]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('exposes the reconciliation sentence via role=status (not a bare span)', () => {
    // Predicted RED: toolbar renders statusMessage in a class-only span with no
    // role="status", so no status region carries the sentence. Provider harness
    // data-testid cannot catch this — only the real toolbar can.
    // Note: ARIA status names from author, not contents, so we match by role +
    // text (same pattern as MediaSelection.identitiesDegraded).
    renderSelection();

    const status = screen
      .getAllByRole('status')
      .find((el) => (el.textContent ?? '').includes(STATUS_SENTENCE));
    expect(status).toBeDefined();
    expect(status).toHaveClass('acx-media-selection__status');
    expect(status).toHaveTextContent(STATUS_SENTENCE);
  });
});
