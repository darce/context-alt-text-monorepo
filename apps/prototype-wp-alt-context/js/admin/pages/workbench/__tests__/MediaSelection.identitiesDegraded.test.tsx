/**
 * Slice 3 — MediaSelection wiring of honest degraded identity state.
 * S3-T1 error-affordance, S3-T2 branch-copy matrix (via dataSource threading),
 * S3-T3 cached-persistence presentation, S3-T6 a11y on the unavailable affordance.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DATA_SOURCE } from '../../../api/recognition/types';
import type { DetectedIdentity } from '../../../api/recognition';
import type { WorkbenchMediaItem } from '../../../hooks/useWorkbenchMedia';
import { MediaSelection } from '../MediaSelection';
import { deriveIdentitiesPresentationSource } from '../deriveIdentitiesPresentationSource';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

const refetchIdentities = vi.fn();

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

const labeledIdentity: DetectedIdentity = {
  identity_id: 'face-1',
  media_id: 11,
  cluster_id: 'cluster-1',
  cluster_label: 'Riley',
  is_auto_label: false,
  bbox: { x: 0, y: 0, width: 10, height: 10 },
  confidence: 0.9,
  similarity: 0.85,
};

interface IdentitiesSurface {
  data?: { identities_by_media: Record<string, DetectedIdentity[]>; data_source?: string };
  isLoading: boolean;
  isError: boolean;
  isPlaceholderData?: boolean;
  isFetching?: boolean;
  refetch: () => void;
}

let identitiesSurface: IdentitiesSurface;
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
        detailQuery: {
          data: { detailsByMedia: {}, limit: 100, total: 1, truncated: false },
          isPending: false,
          isLoading: false,
          isFetching: false,
          isError: false,
          refetch: vi.fn(),
        },
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

describe('MediaSelection Slice 3 — honest degraded identity state', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    refetchIdentities.mockReset();
    itemsWithIdentities = [{ ...baseItem, identities: [] }];
    identitiesSurface = {
      data: undefined,
      isLoading: false,
      isError: true,
      isPlaceholderData: false,
      isFetching: false,
      refetch: refetchIdentities,
    };
  });

  it('S3-T1: identities fetch error (no envelope) renders unavailable affordance with retry, not genuine-empty', async () => {
    renderSelection();

    expect(screen.getByText(/Identity data unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/could not load identities for this media item right now/i)).toBeInTheDocument();
    expect(screen.queryByText(/No identities detected yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/No identities synced for this item yet/i)).not.toBeInTheDocument();

    const user = userEvent.setup();
    // Prefer the row-level EmptyStateWarning Retry (status live region), not the footer
    // status bar and not MediaAltSuggest's always-mounted empty polite region (BR-32).
    // role=status has no accessible name from text content in testing-library, so bare
    // getByRole('status') is ambiguous once MediaAltSuggest always-mounts its region.
    const affordance = screen
      .getAllByRole('status')
      .find((el) => /Identity data unavailable/i.test(el.textContent ?? ''));
    if (!affordance) {
      throw new Error('expected EmptyStateWarning status region');
    }
    const retry = within(affordance).getByRole('button', { name: 'Retry' });
    await user.click(retry);
    expect(refetchIdentities).toHaveBeenCalled();
  });

  it('S3-T2: branch-distinguishing empty copies for success envelopes', () => {
    // local_projection empty
    identitiesSurface = {
      data: { identities_by_media: { '11': [] }, data_source: DATA_SOURCE.LOCAL_PROJECTION },
      isLoading: false,
      isError: false,
      refetch: refetchIdentities,
    };
    const { unmount } = renderSelection();
    expect(screen.getByText(/No identities synced for this item yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/No identities detected yet/i)).not.toBeInTheDocument();
    unmount();

    // backend_proxy empty
    identitiesSurface = {
      data: { identities_by_media: { '11': [] }, data_source: DATA_SOURCE.BACKEND_PROXY },
      isLoading: false,
      isError: false,
      refetch: refetchIdentities,
    };
    const second = renderSelection();
    expect(screen.getByText(/No identities detected yet/i)).toBeInTheDocument();
    second.unmount();

    // endpoint_error empty
    identitiesSurface = {
      data: { identities_by_media: { '11': [] }, data_source: DATA_SOURCE.ENDPOINT_ERROR },
      isLoading: false,
      isError: false,
      refetch: refetchIdentities,
    };
    renderSelection();
    expect(screen.getByText(/Recognition is reachable but returned an error/i)).toBeInTheDocument();
    expect(screen.queryByText(/could not load identities for this media item right now/i)).not.toBeInTheDocument();
  });

  it('S3-T3: failed refetch with same-key cache keeps labels; no unavailable override', () => {
    itemsWithIdentities = [{ ...baseItem, identities: [labeledIdentity] }];
    identitiesSurface = {
      data: {
        identities_by_media: { '11': [labeledIdentity] },
        data_source: DATA_SOURCE.LOCAL_PROJECTION,
      },
      isLoading: false,
      isError: true,
      isPlaceholderData: false,
      isFetching: false,
      refetch: refetchIdentities,
    };

    renderSelection();

    expect(screen.getByText('Riley')).toBeInTheDocument();
    expect(screen.queryByText(/Identity data unavailable/i)).not.toBeInTheDocument();
    // Presentation derivation must keep local_projection when cache is retained
    expect(
      deriveIdentitiesPresentationSource(true, {
        data_source: DATA_SOURCE.LOCAL_PROJECTION,
      }),
    ).toBe(DATA_SOURCE.LOCAL_PROJECTION);
  });

  it('S3-T6: unavailable affordance has role=status aria-live=polite and keyboard-reachable Retry', async () => {
    renderSelection();

    // MediaAltSuggest always-mounts an empty role=status on the same row (BR-32).
    // Bare getByRole('status') is ambiguous (observed: multiple matches).
    const status = screen.getAllByRole('status').find((el) => /Identity data unavailable/i.test(el.textContent ?? ''));
    if (!status) {
      throw new Error('expected EmptyStateWarning status region');
    }
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toHaveTextContent(/Identity data unavailable/i);

    const retry = within(status).getByRole('button', { name: 'Retry' });
    expect(retry.tagName).toBe('BUTTON');

    const user = userEvent.setup();
    retry.focus();
    expect(retry).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(refetchIdentities).toHaveBeenCalled();
  });
});
