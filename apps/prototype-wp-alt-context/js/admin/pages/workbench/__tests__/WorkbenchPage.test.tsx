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
  useClusterIdentities,
  useMultiScanStatus,
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
  useClusterIdentities: vi.fn(),
  useMultiScanStatus: vi.fn(),
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

  const mockUseWorkbenchMedia = useWorkbenchMedia as unknown as vi.MockedFunction<typeof useWorkbenchMedia>;
  const mockUseMediaSelectionState = useMediaSelectionState as unknown as vi.MockedFunction<
    typeof useMediaSelectionState
  >;
  const mockUseRecognitionJobHistory = useRecognitionJobHistory as unknown as vi.MockedFunction<
    typeof useRecognitionJobHistory
  >;
  const mockUseWorkbenchFilters = useWorkbenchFilters as unknown as vi.MockedFunction<typeof useWorkbenchFilters>;
  const mockUseScanIdentities = useScanIdentities as unknown as vi.MockedFunction<typeof useScanIdentities>;
  const mockUseScanStatus = useScanStatus as unknown as vi.MockedFunction<typeof useScanStatus>;
  const mockUseClusterIdentities = useClusterIdentities as unknown as vi.MockedFunction<typeof useClusterIdentities>;
  const mockUseMultiScanStatus = useMultiScanStatus as unknown as vi.MockedFunction<typeof useMultiScanStatus>;

  const setupScanMutation = (outcome: ScanOutcome) => {
    mockUseScanIdentities.mockImplementation((options) => {
      return {
        mutate: (mediaIds: number[]) => {
          options?.onMutate?.();
          if (outcome === 'success') {
            options?.onSuccess?.({ job_id: 'job-123', status: 'queued', total_media: mediaIds.length });
          } else {
            options?.onError?.(new Error('Scan failed'));
          }
        },
        isPending: false,
      };
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
    } as any);

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
      data: { status: 'pending' },
      isFetching: false,
      refetch: vi.fn(),
    } as any);

    mockUseMultiScanStatus.mockReturnValue([]);

    mockUseClusterIdentities.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as any);
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
    mockUseScanStatus.mockReturnValue({
      data: { status: 'completed' },
      isFetching: false,
      refetch: vi.fn(),
    } as any);

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    renderWorkbench(queryClient);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['media-identities'] });
  });
});
