import type { Dispatch, JSX, ReactNode, SetStateAction } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
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
import { CLUSTERING_DISCLOSURE_SUMMARY } from '../confirmTabCopy';

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
  ajaxUrl: '/wp-admin/admin-ajax.php',
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
  zeroEvidenceClusterCount: 0,
  hasFindings: false,
  isLoading: false,
  isError: false,
  isTopUnlabeledError: false,
  isUnavailable: false,
  isReadOnly: false,
  queueSettled: true,
  nextAction: { kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY },
  queue: [],
  ...overrides,
});

describe('WorkbenchPage', () => {
  const baseMediaItem = {
    id: 11,
    title: 'Photo Name',
    altText: null,
    isDecorative: false,
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

  const filtersMock = (overrides: Record<string, unknown> = {}) => ({
    searchQuery: '',
    normalizedSearch: '',
    currentPage: 1,
    perPage: 10,
    statusFilter: 'all' as const,
    setCurrentPage,
    setPerPage,
    handleSearchChange: vi.fn(),
    handleStatusChange: vi.fn(),
    queueState: { kind: 'all' as const, band: 'all' as const, index: 0 },
    getQueueState: () => ({ kind: 'all' as const, band: 'all' as const, index: 0 }),
    setQueueState: vi.fn(),
    ...overrides,
  });

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

    mockUseWorkbenchFilters.mockReturnValue(filtersMock());

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
      ajaxUrl: '/wp-admin/admin-ajax.php',
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
      screen.getByText(
        'Alt Context is targeting the local recognition service at http://localhost:8001 via the developer hatch.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Remove the ACX_RECOGNITION_SOURCE developer constant to use the hosted recognition service.'),
    ).toBeInTheDocument();
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
    mockUseWorkbenchFilters.mockReturnValue(filtersMock({ perPage: 50 }));

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

  it('keeps the media table rendered while findings are active', () => {
    mockUseWorkbenchFindings.mockReturnValue(
      makeFindingsViewModel({
        counts: { assignments: 1, merges: 0, names: 0, unlabeledClusters: 0, total: 1 },
        hasFindings: true,
      }),
    );

    renderWorkbench();

    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Media pagination' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Show media table' })).not.toBeInTheDocument();
  });



  it('clamps current page when total pages shrink', async () => {
    setupScanMutation('success');
    mockUseWorkbenchFilters.mockReturnValue(filtersMock({ currentPage: 2 }));

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
    mockUseWorkbenchFilters.mockReturnValue(filtersMock({ currentPage: 2 }));

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
    renderWorkbench(undefined, ['/workbench?tab=scan&panel=conflicts']);

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

  // WBUX-5 S1c-2: the single-tab Tabs shell is gone. A legacy ?tab=batch deep-link is inert —
  // no tablist, no crash, scan content still renders in the left control host.
  it('ignores the removed batch tab param and renders the two-pane scan workbench', () => {
    setupScanMutation('success');
    renderWorkbench(undefined, ['/workbench?tab=batch']);

    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    const control = screen.getByTestId('workbench-two-pane-control');
    expect(within(control).getByRole('heading', { name: 'Scan Media Queue' })).toBeInTheDocument();
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

  // E21-3 regression guard, ported to the WBUX-5 S1c-2 two-pane shell: there is no workbench
  // tablist at all now, so the confirm tab is trivially absent. Advanced stays workbench-level
  // chrome (a drawer, never a tab). Would fail on the old two-tab UI (tablist present).
  it('exposes no workbench tablist and no confirm tab in the two-pane shell', () => {
    setupScanMutation('success');
    renderWorkbench();

    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Advanced: jobs & recovery' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });

  // E21-10 Slice 4 regression guard, ported to WBUX-5 S1c-2: the tab=confirm shim stays deleted.
  // Under the two-pane shell a legacy ?tab=confirm is fully inert — no advanced auto-open, no tab
  // UI, no URL rewrite — while ?panel=conflicts opens the overlay independently (NAV-11).
  it('does not shim legacy ?tab=confirm (inert param, overlay stays independent)', async () => {
    setupScanMutation('success');
    const LocationProbe = (): JSX.Element => {
      const location = useLocation();
      return <output data-testid="location-search">{location.search}</output>;
    };

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/workbench?tab=confirm&panel=conflicts']}>
          <WorkbenchPage />
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // Two-pane workbench renders (scan control host); ?panel=conflicts opens the overlay.
    expect(screen.getByRole('heading', { name: 'Scan Media Queue' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Conflict Inbox' })).toBeInTheDocument();
    // Discriminating: shim is GONE — advanced stays closed, no tab UI exists.
    expect(screen.getByRole('button', { name: 'Advanced: jobs & recovery' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(screen.queryByRole('region', { name: 'Advanced: jobs & recovery' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();

    await waitFor(() => {
      const search = screen.getByTestId('location-search').textContent ?? '';
      expect(search).toContain('tab=confirm');
      expect(search).not.toContain('advanced=open');
      expect(search).not.toContain('tab=scan');
      expect(search).toContain('panel=conflicts');
    });
  });

  it('LEGACY_CONFIRM_TAB is fully retired from the workbench nav module', async () => {
    const nav = await import('../WorkbenchNavContext');
    expect('LEGACY_CONFIRM_TAB' in nav).toBe(false);
    const ctx = await import('../WorkbenchContext');
    expect('LEGACY_CONFIRM_TAB' in ctx).toBe(false);
  });

  it('opens the advanced drawer, moves focus inside, and restores focus on Escape', async () => {
    const user = userEvent.setup();
    renderWorkbench();

    const trigger = screen.getByRole('button', { name: 'Advanced: jobs & recovery' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await user.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const panel = screen.getByRole('region', { name: 'Advanced: jobs & recovery' });
    expect(panel).toBeInTheDocument();
    // UXP-4 Slice 4: disclosure summary is "What does clustering do?" (not the old help-card title).
    expect(screen.getByText(CLUSTERING_DISCLOSURE_SUMMARY)).toBeInTheDocument();

    await waitFor(() => {
      expect(panel.contains(document.activeElement)).toBe(true);
    });

    await user.keyboard('{Escape}');

    await waitFor(() => {
      expect(screen.queryByRole('region', { name: 'Advanced: jobs & recovery' })).not.toBeInTheDocument();
    });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveFocus();
  });

  // WBUX-5 Slice 1 (S1c-2): atomic swap of the vestigial single-tab Tabs shell for the
  // two-pane control|library layout. Scan content rehomes into the left control host; the
  // media table rehomes into the right library host (with its accordion intact — no
  // behavior loss). Collapse is driven by ?panes=, independent of the ?panel= overlay.
  describe('two-pane shell (WBUX-5 S1c-2)', () => {
    it('renders a control host (left) and library host (right) with a splitter and no tablist', () => {
      setupScanMutation('success');
      const { container } = renderWorkbench();

      // Atomic Tabs→two-pane swap: the single-tab tablist shell is gone.
      expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
      expect(screen.queryByRole('tab')).not.toBeInTheDocument();

      // Both hosts render from zero state (rg-003: primary controls reachable from zero selection).
      const control = screen.getByTestId('workbench-two-pane-control');
      const library = screen.getByTestId('workbench-two-pane-library');
      expect(control).toBeInTheDocument();
      expect(library).toBeInTheDocument();

      // Resizable/collapsible splitter between the panes [A11Y-08].
      expect(screen.getByRole('separator')).toBeInTheDocument();

      // Scan content lives left; the media library lives right — MediaSelection appears
      // exactly once, inside the library host (rehomed, not duplicated).
      expect(within(control).getByRole('heading', { name: 'Scan Media Queue' })).toBeInTheDocument();
      const mediaRegions = container.querySelectorAll('.acx-media-selection');
      expect(mediaRegions).toHaveLength(1);
      expect(library).toContainElement(mediaRegions[0] as HTMLElement);
    });

    it('does not put aria-live on the control panel host [L2V-01]', () => {
      setupScanMutation('success');
      renderWorkbench();

      const panelHost = document.querySelector('.acx-workbench__panel');
      expect(panelHost).not.toBeNull();
      // Nested narrow live regions may exist; the panel host itself must not re-announce.
      expect(panelHost).not.toHaveAttribute('aria-live');
    });

    it('restores ?panes=library-collapsed independently of the ?panel= overlay [NAV-11]', () => {
      setupScanMutation('success');
      renderWorkbench(undefined, ['/workbench?panes=library-collapsed&panel=conflicts']);

      // Pane collapse restored from ?panes= …
      expect(screen.getByTestId('workbench-two-pane-library')).toHaveAttribute('data-collapsed', 'true');
      expect(screen.getByTestId('workbench-two-pane-control')).toHaveAttribute('data-collapsed', 'false');

      // … while ?panel=conflicts independently opens the overlay (both restore together, NAV-11).
      expect(screen.getByRole('heading', { name: 'Conflict Inbox' })).toBeInTheDocument();
    });

  });
});
