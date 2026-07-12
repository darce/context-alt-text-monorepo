import type { Dispatch, ReactNode, SetStateAction } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { resetConfigCache } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import type {
  BatchAnalyzeResponse,
  BatchRunStatus,
  ClusterResponse,
  JobStatusResponse,
  MediaIdentitiesResponse,
} from '../../../api/recognition';
import { createMockMutation, createMockQuery } from '../../../test-utils/mockHooks';
import type { WorkbenchMediaDetailResponse } from '../../../api/workbenchMediaApi';
import type { JobProgressStream } from '../../../hooks/useJobProgressStream';
import { WorkbenchPage } from '../../WorkbenchPage';
import { useWorkbenchMedia, type WorkbenchMediaResponse } from '../../../hooks/useWorkbenchMedia';
import { useMediaSelectionState } from '../../../hooks/useMediaSelectionState';
import { useRecognitionJobHistory } from '../../../hooks/useRecognitionJobHistory';
import { useWorkbenchFilters } from '../../../hooks/useWorkbenchFilters';
import { useJobPersistence } from '../../../hooks/useJobPersistence';
import { useJobProgressStream } from '../../../hooks/useJobProgressStream';
import { useSyncStatus } from '../../../hooks/useSyncStatus';
import { useSyncTrigger } from '../../../hooks/useSyncTrigger';
import {
  NEXT_ACTION_KIND,
  NONE_REASON,
  useWorkbenchFindings,
  type WorkbenchFindingsViewModel,
} from '../identity-clusters/useWorkbenchFindings';
import {
  useScanIdentities,
  useScanStatus,
  useCancelScanJobs,
  useClusterIdentities,
  useMultiScanStatus,
  useCombinedScanStatus,
} from '../../../hooks/useRecognitionHooks';

// Mock ResizeObserver and PointerCapture for Radix UI
window.ResizeObserver = class ResizeObserver {
  observe(): void {
    return undefined;
  }
  unobserve(): void {
    return undefined;
  }
  disconnect(): void {
    return undefined;
  }
};
window.HTMLElement.prototype.hasPointerCapture = vi.fn();
window.HTMLElement.prototype.setPointerCapture = vi.fn();
window.HTMLElement.prototype.releasePointerCapture = vi.fn();
window.HTMLElement.prototype.scrollIntoView = vi.fn();

// Mock AltContextAdmin config
(window as unknown as { AltContextAdmin: object }).AltContextAdmin = {
  nonce: 'test-nonce',
  endpoints: {
    recognition: 'http://localhost:8000',
    recognitionClusters: 'http://localhost:8000/clusters',
  },
  tenant_id: 'test-tenant',
  recognitionSource: 'service',
  effectiveTargetUrl: 'https://api.example.com',
};

// Mock EventSource for SSE
class MockEventSource {
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
  close = vi.fn();
}
(window as unknown as { EventSource: typeof MockEventSource }).EventSource = MockEventSource;

vi.mock('../../../hooks/useWorkbenchMedia', () => ({
  useWorkbenchMedia: vi.fn(),
}));

vi.mock('../../../hooks/useMediaSelectionState', () => ({
  useMediaSelectionState: vi.fn(),
}));

vi.mock('../../../hooks/useRecognitionJobHistory', () => ({
  useRecognitionJobHistory: vi.fn(),
}));

vi.mock('../../../hooks/useWorkbenchFilters', () => ({
  useWorkbenchFilters: vi.fn(),
}));

vi.mock('../../../hooks/useJobPersistence', () => ({
  useJobPersistence: vi.fn(),
}));

vi.mock('../../../hooks/useJobProgressStream', () => ({
  JOB_STATUS: {
    PENDING: 'pending',
    RUNNING: 'running',
    COMPLETED: 'completed',
    FAILED: 'failed',
    CLUSTERING: 'clustering',
  },
  useJobProgressStream: vi.fn(),
}));

vi.mock('../../../hooks/useRecognitionHooks', () => ({
  useScanIdentities: vi.fn(),
  useScanStatus: vi.fn(),
  useCancelScanJobs: vi.fn(),
  useClusterIdentities: vi.fn(),
  useMultiScanStatus: vi.fn(),
  useCombinedScanStatus: vi.fn(),
  useTrainingStage: vi.fn(() => ({
    data: null,
    isLoading: false,
    isError: false,
  })),
}));

vi.mock('../../../hooks/useSyncStatus', () => ({
  useSyncStatus: vi.fn(),
}));

vi.mock('../../../hooks/useSyncTrigger', () => ({
  useSyncTrigger: vi.fn(),
}));

vi.mock('../identity-clusters/useWorkbenchFindings', async () => {
  const actual = await vi.importActual<typeof import('../identity-clusters/useWorkbenchFindings')>(
    '../identity-clusters/useWorkbenchFindings',
  );
  return {
    ...actual,
    useWorkbenchFindings: vi.fn(),
  };
});

type ScanOutcome = 'success' | 'error';

const makeFindingsViewModel = (overrides: Partial<WorkbenchFindingsViewModel> = {}): WorkbenchFindingsViewModel => ({
  counts: { assignments: 0, merges: 0, names: 0, unlabeledClusters: 0, total: 0 },
  previews: [],
  hasFindings: false,
  isLoading: false,
  isError: false,
  isUnavailable: false,
  isReadOnly: false,
  nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY },
  ...overrides,
});

describe('WorkbenchPage', () => {
  const baseMediaItem = {
    id: 11,
    title: 'Photo Name',
    altText: null,
    status: 'missing' as const,
    thumbnailUrl: null,
    mimeType: 'image/jpeg',
    editUrl: '#',
    updatedAt: '2025-01-01T00:00:00Z',
    dimensions: { width: 800, height: 600 },
    xmpPersistence: null,
    tags: [] as string[],
    identities: [],
  };

  const rememberJob = vi.fn();
  const selectJob = vi.fn();
  const clearHistory = vi.fn();
  const prefetchIdentities = vi.fn();

  const mockUseWorkbenchMedia = vi.mocked(useWorkbenchMedia);
  const mockUseMediaSelectionState = vi.mocked(useMediaSelectionState);
  const mockUseRecognitionJobHistory = vi.mocked(useRecognitionJobHistory);
  const mockUseWorkbenchFilters = vi.mocked(useWorkbenchFilters);
  const mockUseScanIdentities = vi.mocked(useScanIdentities);
  const mockUseScanStatus = vi.mocked(useScanStatus);
  const mockUseCancelScanJobs = vi.mocked(useCancelScanJobs);
  const mockUseClusterIdentities = vi.mocked(useClusterIdentities);
  const mockUseMultiScanStatus = vi.mocked(useMultiScanStatus);
  const mockUseCombinedScanStatus = vi.mocked(useCombinedScanStatus);
  const mockUseJobPersistence = vi.mocked(useJobPersistence);
  const mockUseJobProgressStream = vi.mocked(useJobProgressStream);
  const mockUseSyncStatus = vi.mocked(useSyncStatus);
  const mockUseSyncTrigger = vi.mocked(useSyncTrigger);
  const mockUseWorkbenchFindings = vi.mocked(useWorkbenchFindings);
  let setCurrentPage: Dispatch<SetStateAction<number>>;
  let setPerPage: Mock<(nextPerPage: number) => void>;

  const createBatchRunStatusQuery = (data?: BatchRunStatus) =>
    createMockQuery<BatchRunStatus>({
      data,
      refetch: vi.fn(),
    });

  const setupScanMutation = (outcome: ScanOutcome) => {
    mockUseScanIdentities.mockImplementation((options) => {
      const mutate = (mediaIds: number[]) => {
        // React Query 5.90+ callbacks have additional context arguments
        const mockContext = {} as never;
        options?.onMutate?.(mediaIds, mockContext);
        if (outcome === 'success') {
          options?.onSuccess?.(
            {
              batchRunId: 'batch-run-123',
              jobs: [
                {
                  id: 'job-123',
                  type: 'analyze' as const,
                  status: 'pending' as const,
                  progress: { completed: 0, total: mediaIds.length },
                  started_at: new Date().toISOString(),
                  finished_at: null,
                },
              ],
            },
            mediaIds,
            undefined,
            mockContext,
          );
        } else {
          options?.onError?.(new Error('Scan failed'), mediaIds, undefined, mockContext);
        }
      };

      return createMockMutation<BatchAnalyzeResponse, Error, number[]>({
        mutate,
      });
    });
  };

  const renderWorkbench = (client?: QueryClient, initialEntries: string[] = ['/']) => {
    const queryClient = client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
    return { queryClient, ...render(<WorkbenchPage />, { wrapper }) };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    resetConfigCache();
    rememberJob.mockClear();
    selectJob.mockClear();
    clearHistory.mockClear();
    setCurrentPage = vi.fn() as Dispatch<SetStateAction<number>>;
    setPerPage = vi.fn<(nextPerPage: number) => void>();

    const mediaQuery = createMockQuery<WorkbenchMediaResponse>({
      data: { items: [baseMediaItem], total: 1, totalPages: 1 },
      isFetching: false,
      isError: false,
      refetch: vi.fn(),
    });

    mockUseWorkbenchMedia.mockReturnValue({
      ...mediaQuery,
      itemsWithIdentities: [baseMediaItem],
      detailQuery: createMockQuery<WorkbenchMediaDetailResponse>({
        data: { detailsByMedia: {}, limit: 100, total: 1, truncated: false },
      }),
      identitiesQuery: createMockQuery<MediaIdentitiesResponse>({
        data: { identities_by_media: {} },
        refetch: prefetchIdentities,
      }),
    });

    mockUseJobPersistence.mockReturnValue({
      activeJobs: [],
      addJob: vi.fn(),
      removeJob: vi.fn(),
    });

    mockUseJobProgressStream.mockReturnValue({
      progress: null,
      status: 'pending',
      isOnline: true,
      etaSeconds: null,
      isPrimary: true,
      lastEventAt: null,
      stalledForSeconds: null,
      retry: vi.fn(),
    } satisfies JobProgressStream);
    mockUseSyncStatus.mockReturnValue(
      createMockQuery({
        data: {
          last_snapshot_version: 1,
          last_synced_at: '2026-03-10T10:00:00Z',
          is_stale: false,
          sync_health: 'healthy',
          last_sync_result: 'ok',
        },
      }),
    );
    mockUseSyncTrigger.mockReturnValue(
      createMockMutation({
        mutate: vi.fn(),
        isPending: false,
      }),
    );
    mockUseWorkbenchFindings.mockReturnValue(makeFindingsViewModel());

    mockUseMediaSelectionState.mockReturnValue({
      selection: { '11': true },
      selectedMedia: [baseMediaItem],
      toggleRow: vi.fn(),
      toggleAll: vi.fn(),
      isPageFullySelected: () => true,
    });

    mockUseRecognitionJobHistory.mockReturnValue({
      jobId: 'job-initial',
      jobHistory: ['job-initial'],
      jobStatuses: { 'job-initial': 'completed' },
      jobDetails: {},
      recentActivity: [],
      historySource: 'durable',
      rememberJob,
      selectJob,
      forgetJob: vi.fn(),
      clearHistory,
    });

    mockUseWorkbenchFilters.mockReturnValue({
      searchQuery: '',
      normalizedSearch: '',
      currentPage: 1,
      perPage: 10,
      statusFilter: 'all',
      setCurrentPage,
      setPerPage,
      handleSearchChange: vi.fn(),
      handleStatusChange: vi.fn(),
    });

    mockUseScanStatus.mockReturnValue(
      createMockQuery<JobStatusResponse>({
        data: {
          id: 'job-initial',
          type: 'analyze' as const,
          status: 'completed' as const,
          progress: { completed: 1, total: 1 },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
        },
        refetch: vi.fn(),
      }),
    );

    mockUseMultiScanStatus.mockReturnValue([]);

    mockUseCombinedScanStatus.mockReturnValue({
      scanStatusQuery: createMockQuery<JobStatusResponse>({
        data: {
          id: 'job-initial',
          type: 'analyze' as const,
          status: 'completed' as const,
          progress: { completed: 1, total: 1 },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
        },
        refetch: vi.fn(),
      }),
      multiScanStatus: [],
      batchRunStatusQuery: createBatchRunStatusQuery(),
    });

    mockUseCancelScanJobs.mockReturnValue(
      createMockMutation<JobStatusResponse[], Error, string[]>({
        mutate: vi.fn(),
        isPending: false,
      }),
    );

    mockUseClusterIdentities.mockReturnValue(
      createMockMutation<ClusterResponse, Error, void>({
        mutate: vi.fn(),
        isPending: false,
      }),
    );
  });

  it('shows a local-mode notice when recognition source is local', () => {
    setupScanMutation('success');
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      endpoints: {
        recognition: 'http://localhost:8000',
        recognitionClusters: 'http://localhost:8000/clusters',
      },
      tenant_id: 'test-tenant',
      recognitionSource: 'local',
      effectiveTargetUrl: 'http://localhost:8001',
    };
    resetConfigCache();

    renderWorkbench();

    expect(
      screen.getByText('Alt Context is targeting the local recognition service at http://localhost:8001.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Use Settings to switch back to the hosted recognition service.')).toBeInTheDocument();
    expect(screen.queryByText(/local recognition URL fallback/i)).not.toBeInTheDocument();
  });

  it('shows a workbench notice when media detail responses are truncated', () => {
    const mediaQuery = createMockQuery<WorkbenchMediaResponse>({
      data: { items: [baseMediaItem], total: 1, totalPages: 1 },
      isFetching: false,
      isError: false,
      refetch: vi.fn(),
    });

    mockUseWorkbenchMedia.mockReturnValue({
      ...mediaQuery,
      itemsWithIdentities: [baseMediaItem],
      detailQuery: createMockQuery<WorkbenchMediaDetailResponse>({
        data: { detailsByMedia: {}, limit: 100, total: 101, truncated: true },
      }),
      identitiesQuery: createMockQuery<MediaIdentitiesResponse>({
        data: { identities_by_media: {} },
        refetch: prefetchIdentities,
      }),
    });

    renderWorkbench();

    expect(
      screen.getByText(
        'Showing detail metadata for the first 100 of 101 requested media items. Narrow the page size to inspect the rest.',
      ),
    ).toBeInTheDocument();
  });

  it('surfaces scan errors in the UI', async () => {
    setupScanMutation('error');
    const { queryClient } = renderWorkbench();

    fireEvent.click(screen.getByRole('button', { name: /Analyze selected media/i }));
    // E15-30 BR-11 sanitizes scan errors: a non-JSON error message ('Scan failed') is replaced by
    // the localized fallback. Assert the sanitized text surfaces and the raw message does NOT leak.
    expect(await screen.findByText('Recognition job failed. Please try again.')).toBeInTheDocument();
    expect(screen.queryByText('Scan failed')).not.toBeInTheDocument();
    expect(rememberJob).not.toHaveBeenCalled();
    expect(queryClient.getQueryCache().findAll({ queryKey: queryKeys.media.identities() })).toHaveLength(0);
  });

  it('records successful scans and invalidates identity queries', () => {
    setupScanMutation('success');
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    renderWorkbench(queryClient);
    fireEvent.click(screen.getByRole('button', { name: /Analyze selected media/i }));

    expect(rememberJob).toHaveBeenCalledWith('job-123');
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
  });

  it('refreshes dependent recognition queries automatically when a job completes', () => {
    setupScanMutation('success');
    mockUseCombinedScanStatus.mockReturnValue({
      scanStatusQuery: createMockQuery<JobStatusResponse>({
        data: {
          id: 'job-initial',
          type: 'analyze' as const,
          status: 'completed' as const,
          progress: { completed: 1, total: 1 },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
        },
        refetch: vi.fn(),
      }),
      multiScanStatus: [],
      batchRunStatusQuery: createBatchRunStatusQuery(),
    });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    renderWorkbench(queryClient);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.all });
  });

  it('uses backend job messages when available', () => {
    mockUseCombinedScanStatus.mockReturnValue({
      scanStatusQuery: createMockQuery<JobStatusResponse>({
        data: {
          id: 'job-initial',
          type: 'analyze' as const,
          status: 'pending' as const,
          progress: { completed: 0, total: 2 },
          started_at: new Date().toISOString(),
          finished_at: null,
          message: 'Queueing 0/2 items',
        },
        refetch: vi.fn(),
      }),
      multiScanStatus: [],
      batchRunStatusQuery: createBatchRunStatusQuery(),
    });

    renderWorkbench();

    expect(screen.getByText(/Queueing 0\/2 items/)).toBeInTheDocument();
  });

  it('hydrates media page size from the workbench URL filters', () => {
    mockUseWorkbenchFilters.mockReturnValue({
      searchQuery: '',
      normalizedSearch: '',
      currentPage: 1,
      perPage: 50,
      statusFilter: 'all',
      setCurrentPage,
      setPerPage,
      handleSearchChange: vi.fn(),
      handleStatusChange: vi.fn(),
    });

    renderWorkbench();

    const select = screen.getAllByLabelText('Images per page')[0];
    expect(select).toHaveTextContent('50');

    expect(mockUseWorkbenchMedia).toHaveBeenCalledWith(
      expect.objectContaining({
        perPage: 50,
      }),
    );
  });

  it('renders one media-region footer with pagination and analyze CTA', () => {
    const { container } = renderWorkbench();

    const mediaRegion = container.querySelector('.acx-media-selection');
    expect(mediaRegion).not.toBeNull();
    expect(screen.getAllByRole('navigation', { name: 'Media pagination' })).toHaveLength(1);
    expect(screen.getAllByLabelText('Images per page')).toHaveLength(1);
    expect(mediaRegion).toContainElement(screen.getByRole('button', { name: 'Analyze selected media' }));
  });

  it('collapses the media region to a summary bar while findings are active', () => {
    mockUseWorkbenchFindings.mockReturnValue(
      makeFindingsViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        hasFindings: true,
      }),
    );

    renderWorkbench();

    expect(screen.getByText('1 media item')).toBeInTheDocument();
    expect(screen.getByText('1 selected')).toBeInTheDocument();
    expect(screen.getByText('All media')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show media table' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Media pagination' })).not.toBeInTheDocument();
  });

  it('expands the collapsed media region and preserves selection state', async () => {
    mockUseWorkbenchFindings.mockReturnValue(
      makeFindingsViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        hasFindings: true,
      }),
    );

    renderWorkbench();
    await userEvent.click(screen.getByRole('button', { name: 'Show media table' }));

    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Media pagination' })).toBeInTheDocument();
    expect(screen.getByText('Ready to analyze 1 media item.')).toBeInTheDocument();
  });

  it.each([
    ['loading', { isLoading: true }],
    ['error', { isError: true }],
    ['unavailable', { isUnavailable: true }],
  ])('keeps the media table expanded while findings are %s', (_state, overrides) => {
    mockUseWorkbenchFindings.mockReturnValue(
      makeFindingsViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        hasFindings: true,
        ...overrides,
      }),
    );

    renderWorkbench();

    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Show media table' })).not.toBeInTheDocument();
  });

  it('clamps current page when total pages shrink', async () => {
    setupScanMutation('success');
    mockUseWorkbenchFilters.mockReturnValue({
      searchQuery: '',
      normalizedSearch: '',
      currentPage: 2,
      perPage: 10,
      statusFilter: 'all',
      setCurrentPage,
      setPerPage,
      handleSearchChange: vi.fn(),
      handleStatusChange: vi.fn(),
    });

    mockUseWorkbenchMedia.mockReturnValue({
      ...createMockQuery<WorkbenchMediaResponse>({
        data: { items: [baseMediaItem], total: 1, totalPages: 1 },
        isFetching: false,
        isError: false,
        refetch: vi.fn(),
      }),
      itemsWithIdentities: [baseMediaItem],
      detailQuery: createMockQuery<WorkbenchMediaDetailResponse>({
        data: { detailsByMedia: {}, limit: 100, total: 1, truncated: false },
      }),
      identitiesQuery: createMockQuery<MediaIdentitiesResponse>({
        data: { identities_by_media: {} },
        refetch: prefetchIdentities,
      }),
    });

    renderWorkbench();

    await waitFor(() => {
      expect(setCurrentPage).toHaveBeenCalledWith(1);
    });
  });

  it('updates media page size through URL-backed filters', async () => {
    setupScanMutation('success');
    mockUseWorkbenchFilters.mockReturnValue({
      searchQuery: '',
      normalizedSearch: '',
      currentPage: 2,
      perPage: 10,
      statusFilter: 'all',
      setCurrentPage,
      setPerPage,
      handleSearchChange: vi.fn(),
      handleStatusChange: vi.fn(),
    });

    renderWorkbench();

    const select = screen.getAllByLabelText('Images per page')[0];
    const user = userEvent.setup();

    // Open the select dropdown and use keyboard to navigate
    await user.click(select);

    // Use keyboard to select "100" (arrow down twice from "10" -> "50" -> "100", then Enter)
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');

    await waitFor(() => {
      expect(setPerPage).toHaveBeenCalledWith(100);
    });
  });

  it('renders skeleton rows while the shell query is pending', () => {
    mockUseWorkbenchMedia.mockReturnValue({
      ...createMockQuery<WorkbenchMediaResponse>({
        data: undefined,
        isPending: true,
        isFetching: true,
      }),
      itemsWithIdentities: undefined,
      detailQuery: createMockQuery<WorkbenchMediaDetailResponse>({
        data: undefined,
        isPending: true,
        isFetching: true,
      }),
      identitiesQuery: createMockQuery<MediaIdentitiesResponse>({
        data: undefined,
        isPending: true,
        isFetching: true,
      }),
    });

    const { container } = renderWorkbench();

    expect(container.querySelectorAll('.acx-media-selection__skeleton-row')).toHaveLength(5);
  });

  it('renders the conflict inbox overlay from the panel query param', () => {
    renderWorkbench(undefined, ['/workbench?tab=confirm&panel=conflicts']);

    expect(screen.getByRole('heading', { name: 'Conflict Inbox' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Conflict inbox' })).toBeInTheDocument();
  });

  it('closes the overlay when the dismiss action is used', async () => {
    const user = userEvent.setup();
    renderWorkbench(undefined, ['/workbench?tab=scan&panel=dead-letter']);

    expect(screen.getByRole('heading', { name: 'Failed Sync Queue' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close' }));

    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: 'Failed Sync Queue' })).not.toBeInTheDocument();
    });
  });

  it('falls back to the scan tab when the removed batch tab is requested', () => {
    renderWorkbench(undefined, ['/workbench?tab=batch']);

    expect(screen.getByRole('heading', { name: 'Scan Media Queue' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Batch' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Scan Media Queue' })).toHaveAttribute('data-state', 'active');
  });

  it('shows "Clustering identities…" button text when backend-driven clustering is active', () => {
    mockUseCombinedScanStatus.mockReturnValue({
      scanStatusQuery: createMockQuery({
        data: {
          id: 'analyze-1',
          type: 'clustering' as const,
          status: 'running' as const,
          progress: { completed: 50, total: 150, phase: 'clustering' },
          started_at: new Date().toISOString(),
          finished_at: null,
        },
        refetch: vi.fn(),
      }),
      multiScanStatus: [],
      batchRunStatusQuery: createBatchRunStatusQuery(),
    });

    renderWorkbench();

    expect(screen.getByRole('button', { name: 'Clustering identities…' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clustering identities…' })).toBeDisabled();
  });

  it('shows identity-based progress label during backend-driven clustering', () => {
    mockUseCombinedScanStatus.mockReturnValue({
      scanStatusQuery: createMockQuery({
        data: {
          id: 'analyze-1',
          type: 'clustering' as const,
          status: 'running' as const,
          progress: { completed: 75, total: 150, phase: 'clustering' },
          started_at: new Date().toISOString(),
          finished_at: null,
        },
        refetch: vi.fn(),
      }),
      multiScanStatus: [],
      batchRunStatusQuery: createBatchRunStatusQuery(),
    });

    renderWorkbench();

    expect(screen.getByText('Processed 75/150 identities')).toBeInTheDocument();
    expect(screen.queryByText(/Processed.*images/i)).not.toBeInTheDocument();
  });
});
