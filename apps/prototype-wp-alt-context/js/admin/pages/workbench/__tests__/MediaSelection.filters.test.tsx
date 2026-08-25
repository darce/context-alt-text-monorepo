import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { MediaSelection } from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

const { mediaQuery } = vi.hoisted(() => ({
  mediaQuery: {
    data: { items: [] as never[], total: 0, totalPages: 1 },
    isPending: false,
    isFetching: false,
    isError: false,
    isSuccess: true,
    refetch: vi.fn(),
    itemsWithIdentities: [] as never[],
    detailQuery: {
      data: { detailsByMedia: {}, limit: 100, total: 0, truncated: false },
      isPending: false,
      isLoading: false,
      isFetching: false,
      isError: false,
      refetch: vi.fn(),
    },
    identitiesQuery: {
      data: undefined,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    },
  },
}));

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
      statusFilter: 'all',
      currentPage: 1,
      perPage: 10,
      handleSearchChange: vi.fn(),
      clearSearch: vi.fn(),
      handleStatusChange: vi.fn(),
      setCurrentPage: vi.fn(),
      setPerPage: vi.fn(),
    },
    mediaQueue: {
      mediaQuery,
      statusMessage: '',
      isStatusPending: mediaQuery.isPending,
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

describe('W3-C-07 MediaSelection media-query copy', () => {
  it('shows media loading copy from mediaQuery pending', () => {
    mediaQuery.isPending = true;
    mediaQuery.isError = false;
    renderSelection();
    expect(screen.getByTestId('acx-zone-z-filters-loading')).toHaveTextContent('Loading media…');
  });

  it('shows media error copy from mediaQuery error', () => {
    mediaQuery.isPending = false;
    mediaQuery.isError = true;
    renderSelection();
    expect(screen.getByTestId('acx-zone-z-filters-error')).toHaveTextContent('Unable to load media.');
  });
});
