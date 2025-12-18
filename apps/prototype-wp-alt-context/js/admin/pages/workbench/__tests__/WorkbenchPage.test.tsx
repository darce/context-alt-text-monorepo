import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkbenchPage } from '../../WorkbenchPage';
import { useWorkbenchMedia } from '../../../hooks/useWorkbenchMedia';
import { useMediaSelectionState } from '../../../hooks/useMediaSelectionState';
import { useRecognitionJobHistory } from '../../../hooks/useRecognitionJobHistory';
import { useWorkbenchFilters } from '../../../hooks/useWorkbenchFilters';
import {
  useScanIdentities,
  useScanStatus,
  useCancelScanJobs,
  useClusterIdentities,
  useMultiScanStatus,
  useCombinedScanStatus,
} from '../../../hooks/useRecognitionHooks';

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

  const setupScanMutation = (outcome: ScanOutcome) => {
    mockUseScanIdentities.mockImplementation((options) => {
      return {
        mutate: (mediaIds: number[]) => {
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
        },
        mutateAsync: vi.fn(),
        isPending: false,
        isIdle: true,
        isSuccess: false,
        isError: false,
        reset: vi.fn(),
        status: 'idle',
        data: undefined,
        error: null,
        variables: undefined,
        context: undefined,
        failureCount: 0,
        failureReason: null,
        submittedAt: 0,
        isPaused: false,
      } as unknown as ReturnType<typeof useScanIdentities>;
    });
  };

  const renderWorkbench = (client?: QueryClient) => {
    const queryClient = client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { queryClient, ...render(<WorkbenchPage />, { wrapper }) };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    rememberJob.mockClear();
    selectJob.mockClear();
    clearHistory.mockClear();

    mockUseWorkbenchMedia.mockReturnValue({
      data: { items: [baseMediaItem], total: 1, totalPages: 1 },
      itemsWithIdentities: [baseMediaItem],
      isFetching: false,
      isError: false,
      refetch: vi.fn(),
      identityQuery: undefined,
      identitiesQuery: {
        data: { identities_by_media: {} },
        isLoading: false,
        isError: false,
        refetch: prefetchIdentities,
      },
    } as unknown as ReturnType<typeof useWorkbenchMedia>);

    mockUseMediaSelectionState.mockReturnValue({
      selection: { '11': true },
      selectedMedia: [baseMediaItem],
      toggleRow: vi.fn(),
      toggleAll: vi.fn(),
      isPageFullySelected: () => true,
      clearSelection: vi.fn(),
    });

    mockUseRecognitionJobHistory.mockReturnValue({
      jobId: 'job-initial',
      jobHistory: ['job-initial'],
      jobStatuses: { 'job-initial': 'completed' },
      rememberJob,
      selectJob,
      clearHistory,
    });

    mockUseWorkbenchFilters.mockReturnValue({
      searchQuery: '',
      normalizedSearch: '',
      currentPage: 1,
      setCurrentPage: vi.fn(),
      handleSearchChange: vi.fn(),
    });

    mockUseScanStatus.mockReturnValue({
      data: {
        id: 'job-initial',
        type: 'analyze' as const,
        status: 'completed' as const,
        progress: { completed: 1, total: 1 },
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
      },
      isFetching: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useScanStatus>);

    mockUseMultiScanStatus.mockReturnValue([]);

    mockUseCombinedScanStatus.mockReturnValue({
      scanStatusQuery: {
        data: {
          id: 'job-initial',
          type: 'analyze' as const,
          status: 'completed' as const,
          progress: { completed: 1, total: 1 },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
        },
        isFetching: false,
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof useScanStatus>,
      multiScanStatus: [],
    });

    mockUseCancelScanJobs.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useCancelScanJobs>);

    mockUseClusterIdentities.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as unknown as ReturnType<typeof useClusterIdentities>);
  });

  it('surfaces scan errors in the UI', async () => {
    setupScanMutation('error');
    const { queryClient } = renderWorkbench();

    fireEvent.click(screen.getByRole('button', { name: /Analyze selected media/i }));
    expect(await screen.findByText('Scan failed')).toBeInTheDocument();
    expect(rememberJob).not.toHaveBeenCalled();
    expect(queryClient.getQueryCache().find({ queryKey: ['media-identities'] })).toBeUndefined();
  });

  it('records successful scans and invalidates identity queries', () => {
    setupScanMutation('success');
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    renderWorkbench(queryClient);
    fireEvent.click(screen.getByRole('button', { name: /Analyze selected media/i }));

    expect(rememberJob).toHaveBeenCalledWith('job-123');
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['media-identities'] });
  });

  it('refreshes identities automatically when a job completes', () => {
    setupScanMutation('success');
    mockUseCombinedScanStatus.mockReturnValue({
      scanStatusQuery: {
        data: {
          id: 'job-initial',
          type: 'analyze' as const,
          status: 'completed' as const,
          progress: { completed: 1, total: 1 },
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
        },
        isFetching: false,
        refetch: vi.fn(),
      } as unknown as ReturnType<typeof useScanStatus>,
      multiScanStatus: [],
    });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    renderWorkbench(queryClient);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['media-identities'] });
  });
});
