/**
 * WBUX-6 L2b — describe-start orchestration (RES-03 fail-fast, RLSE-04 identifying).
 * Primary click chains analyze→describe when recognition is on; skips analyze when off.
 * Contract: useJobPipeline().scanAndWait(ids) resolves when the recognition batch reaches its terminal
 * state and rejects with an Error whose message is already user-safe (resolveScanErrorMessage).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchSettings } from '../../../api/settingsApi';
import type { WorkbenchMediaItem } from '../../../hooks/useWorkbenchMedia';
import { MediaSelection } from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

const { scan, describeMutate, settingsState, cancelScan } = vi.hoisted(() => {
  let resolveScan: (value?: unknown) => void = () => undefined;
  let rejectScan: (reason?: unknown) => void = () => undefined;
  const scanFn = vi.fn(() => {
    return new Promise<unknown>((resolve, reject) => {
      resolveScan = resolve;
      rejectScan = reject;
    });
  });
  return {
    scan: Object.assign(scanFn, {
      resolve: (value?: unknown) => resolveScan(value),
      reject: (reason?: unknown) => rejectScan(reason),
    }),
    describeMutate: vi.fn(),
    settingsState: { recognitionEnabled: true },
    cancelScan: vi.fn(),
  };
});

const baseItem = (id: number): WorkbenchMediaItem => ({
  id,
  title: `Photo ${id}`,
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
});

const items = [baseItem(11), baseItem(12)];

vi.mock('../../../api/settingsApi', () => ({
  fetchSettings: vi.fn(() => Promise.resolve({ recognition_enabled: settingsState.recognitionEnabled })),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({
    selection: {
      selection: { '11': true, '12': true },
      selectedMedia: items,
      toggleRow: vi.fn(),
      toggleAll: vi.fn(),
      isPageFullySelected: () => true,
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
        data: { items, total: 2, totalPages: 1 },
        isPending: false,
        isFetching: false,
        isError: false,
        isSuccess: true,
        refetch: vi.fn(),
        itemsWithIdentities: items,
        detailQuery: {
          data: { detailsByMedia: {}, limit: 100, total: 2, truncated: false },
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
      statusMessage: 'Showing 2 media items.',
      isStatusPending: false,
      detailTruncationNotice: null,
      hasIdentities: false,
    },
  }),
}));

vi.mock('../../../hooks/useBulkDescribe', () => ({
  useBulkDescribe: () => ({
    submit: { isPending: false, mutate: describeMutate, error: null },
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
    errorMessage: null,
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
  useJobPipeline: () => ({
    scanRun: { isScanning: false, progress: null, jobId: null },
    scan: vi.fn(),
    scanAndWait: scan,
    cancelScan,
    history: { activeJobIds: [] as string[] },
  }),
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

const clickDescribe = async (): Promise<void> => {
  await userEvent.click(await screen.findByRole('button', { name: 'Describe 2 selected' }));
};

describe('describe-start orchestration (WBUX-6 L2b)', () => {
  beforeEach(() => {
    scan.mockClear();
    describeMutate.mockClear();
    cancelScan.mockReset();
    settingsState.recognitionEnabled = true;
    vi.mocked(fetchSettings).mockImplementation(() =>
      Promise.resolve({
        recognition_enabled: settingsState.recognitionEnabled,
      } as Awaited<ReturnType<typeof fetchSettings>>),
    );
  });

  it('ON: analyzes selected ids before describe, and does not describe until analyze resolves', async () => {
    renderSelection();
    await screen.findByText(/Identifies people first \(AI\)/);

    await clickDescribe();

    expect(scan).toHaveBeenCalledWith([11, 12]);
    expect(describeMutate).not.toHaveBeenCalled();
    const identifying = screen.getByRole('button', { name: 'Identifying people…' });
    expect(identifying).toHaveAttribute('aria-disabled', 'true');

    scan.resolve({ jobs: [] });

    await waitFor(() => {
      expect(describeMutate).toHaveBeenCalledWith([11, 12]);
    });
    expect(describeMutate).toHaveBeenCalledOnce();
  });

  it('OFF: never calls analyze and starts describe immediately', async () => {
    settingsState.recognitionEnabled = false;
    renderSelection();
    await screen.findByText(/People are not identified \(recognition off\)/);

    await clickDescribe();

    expect(scan).not.toHaveBeenCalled();
    expect(describeMutate).toHaveBeenCalledWith([11, 12]);
  });

  it('analyze reject: never starts describe and renders the error text', async () => {
    renderSelection();
    await screen.findByText(/Identifies people first \(AI\)/);

    await clickDescribe();
    expect(describeMutate).not.toHaveBeenCalled();

    await act(async () => {
      scan.reject(new Error('analyze exploded'));
      await Promise.resolve();
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('analyze exploded');
    expect(describeMutate).not.toHaveBeenCalled();
  });

  it('pipeline rejection (e.g. 409 recognition_disabled) renders the user-safe message and never starts describe', async () => {
    renderSelection();
    await screen.findByText(/Identifies people first \(AI\)/);

    await clickDescribe();
    await act(async () => {
      scan.reject(new Error('People identification is turned off in Settings.'));
      await Promise.resolve();
    });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'People identification is turned off in Settings.',
    );
    expect(describeMutate).not.toHaveBeenCalled();
  });

  it('does not start describe before settings resolve; ON then scans first', async () => {
    let resolveSettings!: (value: Awaited<ReturnType<typeof fetchSettings>>) => void;
    vi.mocked(fetchSettings).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSettings = resolve;
        }),
    );

    renderSelection();

    const button = await screen.findByRole('button', { name: 'Loading settings…' });
    expect(screen.queryByText(/recognition off/)).not.toBeInTheDocument();
    await userEvent.click(button);
    expect(scan).not.toHaveBeenCalled();
    expect(describeMutate).not.toHaveBeenCalled();

    await act(async () => {
      resolveSettings({
        recognition_enabled: true,
      } as Awaited<ReturnType<typeof fetchSettings>>);
    });

    await screen.findByText(/Identifies people first \(AI\)/);
    await clickDescribe();
    expect(scan).toHaveBeenCalledWith([11, 12]);
    expect(describeMutate).not.toHaveBeenCalled();
  });

  it('identifying primary stays focusable and Cancel rejects the waiter', async () => {
    cancelScan.mockImplementation(() => {
      scan.reject(new Error('People identification was cancelled.'));
    });

    renderSelection();
    await screen.findByText(/Identifies people first \(AI\)/);
    await clickDescribe();

    const identifying = screen.getByRole('button', { name: 'Identifying people…' });
    expect(identifying).not.toBeDisabled();
    expect(identifying).toHaveAttribute('aria-disabled', 'true');
    expect(identifying.getAttribute('aria-describedby')).toBeTruthy();

    // WBUX6-W4-R-02: the in-flight operation is identification, not a describe run.
    expect(screen.queryByRole('button', { name: 'Cancel describe run' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel people identification' }));

    expect(cancelScan).toHaveBeenCalled();
    expect(await screen.findByRole('alert')).toHaveTextContent('People identification was cancelled.');
    expect(describeMutate).not.toHaveBeenCalled();
  });
});
