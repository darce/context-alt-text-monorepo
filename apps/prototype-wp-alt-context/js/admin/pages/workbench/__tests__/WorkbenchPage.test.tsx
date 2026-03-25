import type { Dispatch, ReactNode, SetStateAction } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';

import { resetConfigCache } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import type {
  AnalyzeResponse,
  ClusterResponse,
  JobStatusResponse,
  MediaIdentitiesResponse,
} from '../../../api/recognition';
import { createMockMutation, createMockQuery } from '../../../test-utils/mockHooks';
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
  useJobProgressStream: vi.fn(),
}));

vi.mock('../../../hooks/useRecognitionHooks', () => ({
  useScanIdentities: vi.fn(),
  useScanStatus: vi.fn(),
  useCancelScanJobs: vi.fn(),
  useClusterIdentities: vi.fn(),
  useMultiScanStatus: vi.fn(),
  useCombinedScanStatus: vi.fn(),
  useAcknowledgeProjection: vi.fn(() => ({
    mutateAsync: vi.fn(),
  })),
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

type ScanOutcome = 'success' | 'error';

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
  let setCurrentPage: Dispatch<SetStateAction<number>>;
  let setPerPage: Mock<(nextPerPage: number) => void>;

  const setupScanMutation = (outcome: ScanOutcome) => {
    mockUseScanIdentities.mockImplementation((options) => {
      const mutate = (mediaIds: number[]) => {
        // React Query 5.90+ callbacks have additional context arguments
        const mockContext = {} as never;
        options?.onMutate?.(mediaIds, mockContext);
        if (outcome === 'success') {
          options?.onSuccess?.(
            [
              {
                id: 'job-123',
                type: 'analyze' as const,
                status: 'pending' as const,
                progress: { completed: 0, total: mediaIds.length },
                started_at: new Date().toISOString(),
                finished_at: null,
              },
            ],
            mediaIds,
            undefined,
            mockContext,
          );
        } else {
          options?.onError?.(new Error('Scan failed'), mediaIds, undefined, mockContext);
        }
      };

      return createMockMutation<AnalyzeResponse[], Error, number[]>({
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
    });
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
      rememberJob,
      selectJob,
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

  it('shows a warning when recognition URL fallback is active', () => {
    setupScanMutation('success');
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      endpoints: {
        recognition: 'http://localhost:8000',
        recognitionClusters: 'http://localhost:8000/clusters',
      },
      tenant_id: 'test-tenant',
      recognitionUrlFallback: true,
    };
    resetConfigCache();

    renderWorkbench();

    expect(
      screen.getByText(
        'Alt Context is using the local recognition URL fallback (http://localhost:8000). Configure acx_recognition_url or ACX_RECOGNITION_URL for this environment.',
      ),
    ).toBeInTheDocument();
  });

  it('surfaces scan errors in the UI', async () => {
    setupScanMutation('error');
    const { queryClient } = renderWorkbench();

    fireEvent.click(screen.getByRole('button', { name: /Analyze selected media/i }));
    expect(await screen.findByText('Scan failed')).toBeInTheDocument();
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

  it('refreshes identities automatically when a job completes', () => {
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
    });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    renderWorkbench(queryClient);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
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

  it('renders pagination controls above and below the media table', () => {
    renderWorkbench();

    expect(screen.getAllByRole('navigation', { name: 'Media pagination' })).toHaveLength(2);
    expect(screen.getAllByLabelText('Images per page')).toHaveLength(2);
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

  it('renders the conflict inbox overlay from the panel query param', () => {
    renderWorkbench(undefined, ['/workbench?tab=confirm&panel=conflicts']);

    expect(screen.getByRole('heading', { name: 'Conflict Inbox' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Conflict inbox' })).toBeInTheDocument();
  });

  it('closes the overlay when the dismiss action is used', async () => {
    const user = userEvent.setup();
    renderWorkbench(undefined, ['/workbench?tab=scan&panel=dead-letter']);

    expect(screen.getByRole('heading', { name: 'Dead-Letter Queue' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close' }));

    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: 'Dead-Letter Queue' })).not.toBeInTheDocument();
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
    });

    renderWorkbench();

    expect(screen.getByText('Processed 75/150 identities')).toBeInTheDocument();
    expect(screen.queryByText(/Processed.*images/i)).not.toBeInTheDocument();
  });
});
