/**
 * UXPNET2-BR-08 — MediaSelection auth-expired wiring.
 * Reuses the mounting/mocking harness from MediaSelection.identitiesDegraded.test.tsx.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthExpiredError } from '../../../utils/http';
import type { DetectedIdentity } from '../../../api/recognition';
import type { WorkbenchMediaItem } from '../../../hooks/useWorkbenchMedia';
import { MediaSelection } from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

const refetchIdentities = vi.fn();
const refetchDetail = vi.fn();

const baseItem: WorkbenchMediaItem = {
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
};

type QuerySurface = {
  data?: { identities_by_media: Record<string, DetectedIdentity[]>; data_source?: string } | undefined;
  isLoading: boolean;
  isError: boolean;
  isPlaceholderData?: boolean;
  isFetching?: boolean;
  isPending?: boolean;
  error?: unknown;
  refetch: () => void;
};

let identitiesSurface: QuerySurface;
let detailSurface: QuerySurface;
let itemsWithIdentities: WorkbenchMediaItem[];

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
      mediaQuery: {
        data: { items: [baseItem], total: 1, totalPages: 1 },
        isPending: false,
        isFetching: false,
        isError: false,
        isSuccess: true,
        refetch: vi.fn(),
        itemsWithIdentities,
        detailQuery: detailSurface,
        identitiesQuery: identitiesSurface,
      },
      statusMessage: 'Showing 1 media item.',
      isStatusPending: false,
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

describe('MediaSelection auth-expired wiring (UXPNET2-BR-08)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    refetchIdentities.mockReset();
    refetchDetail.mockReset();
    itemsWithIdentities = [{ ...baseItem, identities: [] }];
    detailSurface = {
      data: { detailsByMedia: {}, limit: 100, total: 1, truncated: false } as unknown as QuerySurface['data'],
      isLoading: false,
      isPending: false,
      isFetching: false,
      isError: false,
      refetch: refetchDetail,
    };
    identitiesSurface = {
      data: undefined,
      isLoading: false,
      isError: false,
      isPlaceholderData: false,
      isFetching: false,
      refetch: refetchIdentities,
    };
  });

  it('Case A: AuthExpiredError on identities/detail renders session-expired copy, not generic copy', () => {
    identitiesSurface = {
      ...identitiesSurface,
      isError: true,
      error: new AuthExpiredError({ endpoint: '/acx/v1/identities', status: 401 }),
    };
    detailSurface = {
      ...detailSurface,
      isError: true,
      error: new AuthExpiredError({ endpoint: '/acx/v1/details', status: 401 }),
    };

    renderSelection();

    const authNotices = screen.getAllByTestId('acx-user-facing-error');
    expect(authNotices.length).toBeGreaterThan(0);
    authNotices.forEach((notice) => {
      expect(notice).toHaveAttribute('data-error-kind', 'auth-expired');
    });

    expect(
      screen.getAllByText('Your session expired — reload the page and sign in again.').length,
    ).toBeGreaterThan(0);

    // The generic fallback copy must NOT be shown alongside the auth-expired notice.
    expect(screen.queryByText('Unable to load media details.')).not.toBeInTheDocument();
    expect(screen.queryByText('Unable to load identity data.')).not.toBeInTheDocument();
  });

  it('Case B: generic Error renders generic fallback copy, hides raw message, no session-expired copy', () => {
    identitiesSurface = {
      ...identitiesSurface,
      isError: true,
      error: new Error('Request to /x failed (500): raw'),
    };

    renderSelection();

    expect(screen.getByText('Unable to load identity data.')).toBeInTheDocument();
    expect(screen.queryByText(/\/x failed/)).not.toBeInTheDocument();
    expect(
      screen.queryByText('Your session expired — reload the page and sign in again.'),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId('acx-user-facing-error')).not.toBeInTheDocument();
  });
});
