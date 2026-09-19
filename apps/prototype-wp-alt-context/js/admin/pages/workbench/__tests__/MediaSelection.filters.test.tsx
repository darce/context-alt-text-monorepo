import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { WorkbenchMediaItem } from '../../../hooks/useWorkbenchMedia';
import {
  descriptionHistoryQueuePath,
  MediaSelection,
  QUEUE_HAS_DRAFT_PARAM,
  QUEUE_HAS_DRAFT_VALUE,
  workbenchDraftQueueHref,
} from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let i = 0;
    return format.replace(/%(\d+)\$[sd]|%[sd]/g, () => String(args[i++]));
  },
}));

const flower: WorkbenchMediaItem = {
  id: 71,
  title: 'Flower',
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

const bridge: WorkbenchMediaItem = {
  ...flower,
  id: 70,
  title: 'Bridge',
};

const { mediaQuery, queueDrafts } = vi.hoisted(() => ({
  mediaQuery: {
    data: { items: [] as WorkbenchMediaItem[], total: 0, totalPages: 1 },
    isPending: false,
    isFetching: false,
    isError: false,
    isSuccess: true,
    refetch: vi.fn(),
    itemsWithIdentities: [] as WorkbenchMediaItem[],
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
  queueDrafts: {
    draftsByMediaId: {} as Record<
      number,
      {
        mediaId: number;
        draftText: string;
        existingAlt: boolean;
        runId: string | null;
        source: string;
      }
    >,
    isLoading: false,
    isError: false,
    error: null as Error | null,
    lastRunId: undefined as string | null | undefined,
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

vi.mock('../../../hooks/useQueueDrafts', () => ({
  QUEUE_DRAFT_SOURCE: {
    DESCRIBE_RUN: 'describe_run',
    DESCRIPTION_HISTORY: 'description_history',
  },
  useQueueDrafts: (_mediaIds: readonly number[], runId?: string | null) => {
    queueDrafts.lastRunId = runId;
    return {
      draftsByMediaId: queueDrafts.draftsByMediaId,
      isLoading: queueDrafts.isLoading,
      isError: queueDrafts.isError,
      error: queueDrafts.error,
    };
  },
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

const LocationProbe = (): React.JSX.Element => {
  const [params] = useSearchParams();
  return <div data-testid="queue-search">{params.toString()}</div>;
};

const seedLibrary = (): void => {
  mediaQuery.isPending = false;
  mediaQuery.isError = false;
  mediaQuery.data = { items: [flower, bridge], total: 2, totalPages: 1 };
  mediaQuery.itemsWithIdentities = [flower, bridge];
};

const seedFlowerDraft = (runId: string | null = null): void => {
  queueDrafts.isLoading = false;
  queueDrafts.isError = false;
  queueDrafts.error = null;
  queueDrafts.draftsByMediaId = {
    71: {
      mediaId: 71,
      draftText: 'A flower.',
      existingAlt: false,
      runId,
      source: runId ? 'describe_run' : 'description_history',
    },
  };
};

const renderSelection = (path = '/workbench') => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={client}>
        <MediaSelection />
        <LocationProbe />
      </QueryClientProvider>
    </MemoryRouter>,
  );
};

describe('W3-C-07 MediaSelection media-query copy', () => {
  beforeEach(() => {
    mediaQuery.isPending = false;
    mediaQuery.isError = false;
    mediaQuery.data = { items: [], total: 0, totalPages: 1 };
    mediaQuery.itemsWithIdentities = [];
    queueDrafts.draftsByMediaId = {};
    queueDrafts.isLoading = false;
    queueDrafts.isError = false;
    queueDrafts.error = null;
    queueDrafts.lastRunId = undefined;
  });

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

describe('U2b MediaSelection draft queue filters', () => {
  beforeEach(() => {
    mediaQuery.isPending = false;
    mediaQuery.isError = false;
    mediaQuery.data = { items: [], total: 0, totalPages: 1 };
    mediaQuery.itemsWithIdentities = [];
    queueDrafts.draftsByMediaId = {};
    queueDrafts.isLoading = false;
    queueDrafts.isError = false;
    queueDrafts.error = null;
    queueDrafts.lastRunId = undefined;
  });

  it('maps /description-history and ?run= onto the workbench Has-draft filter [NAV-07]', () => {
    expect(descriptionHistoryQueuePath('')).toBe(
      `/workbench?${QUEUE_HAS_DRAFT_PARAM}=${QUEUE_HAS_DRAFT_VALUE}`,
    );
    expect(descriptionHistoryQueuePath('run=run-abc')).toBe(
      `/workbench?${QUEUE_HAS_DRAFT_PARAM}=${QUEUE_HAS_DRAFT_VALUE}&run=run-abc`,
    );
    expect(workbenchDraftQueueHref('run-abc')).toBe(
      `#/workbench?${QUEUE_HAS_DRAFT_PARAM}=${QUEUE_HAS_DRAFT_VALUE}&run=run-abc`,
    );
  });

  it('exposes a Has draft filter in the queue chrome [NAV-05][NAV-06]', () => {
    seedLibrary();
    renderSelection();
    expect(screen.getByRole('checkbox', { name: 'Has draft' })).toBeInTheDocument();
  });

  it('writes hasDraft=1 into the URL when Has draft is checked [NAV-07]', async () => {
    seedLibrary();
    const user = userEvent.setup();
    renderSelection();

    await user.click(screen.getByRole('checkbox', { name: 'Has draft' }));

    expect(screen.getByTestId('queue-search')).toHaveTextContent(
      `${QUEUE_HAS_DRAFT_PARAM}=${QUEUE_HAS_DRAFT_VALUE}`,
    );
  });

  it('renders QueueDraftCell inline and keeps undrafted rows until Has draft is on', () => {
    seedLibrary();
    seedFlowerDraft();
    renderSelection();

    expect(screen.getByText('Flower')).toBeInTheDocument();
    expect(screen.getByText('Bridge')).toBeInTheDocument();
    expect(screen.getByText('A flower.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept draft for Flower' })).toBeInTheDocument();
  });

  it('filters the queue to drafted rows when hasDraft=1 is in the URL', () => {
    seedLibrary();
    seedFlowerDraft();
    renderSelection(`/workbench?${QUEUE_HAS_DRAFT_PARAM}=${QUEUE_HAS_DRAFT_VALUE}`);

    expect(screen.getByRole('checkbox', { name: 'Has draft' })).toBeChecked();
    expect(screen.getByText('Flower')).toBeInTheDocument();
    expect(screen.getByText('A flower.')).toBeInTheDocument();
    expect(screen.queryByText('Bridge')).not.toBeInTheDocument();
  });

  it('scopes drafts to ?run= and offers a labelled return [NAV-07]', async () => {
    seedLibrary();
    seedFlowerDraft('run-abc');
    const user = userEvent.setup();
    renderSelection('/workbench?run=run-abc');

    expect(queueDrafts.lastRunId).toBe('run-abc');
    expect(screen.getByText('Showing drafts from run run-abc')).toBeInTheDocument();
    expect(screen.getByText('Flower')).toBeInTheDocument();
    expect(screen.queryByText('Bridge')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept draft for Flower' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear run filter' }));

    expect(screen.getByTestId('queue-search')).toHaveTextContent('');
    const table = screen.getByRole('table');
    expect(within(table).getByText('Flower')).toBeInTheDocument();
    expect(within(table).getByText('Bridge')).toBeInTheDocument();
  });
});
