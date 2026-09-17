import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as gpuApi from '../../../api/gpuApi';
import {
  DESCRIBE_RUN_PHASE,
  DESCRIBE_RUN_STATUS,
  GPU_STATE,
  isDescribeRunTerminal,
  isGpuState,
  type DescribeRunResponse,
} from '../../../api/describeApi';
import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import { MediaSelection } from '../MediaSelection';

const { bulkDescribeState, fetchGpuStatusMock, fetchSettingsMock } = vi.hoisted(() => ({
  bulkDescribeState: {
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
      gpuState: 'unknown',
      startupId: null,
      isWarming: false,
      timing: null,
      retry: vi.fn(),
      error: null,
      stalledForSeconds: null,
      isFrozen: false,
    },
    runId: null,
    activeRunId: null,
  } as Record<string, any>,
  fetchGpuStatusMock: vi.fn(),
  fetchSettingsMock: vi.fn(),
}));

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _position, explicitIndex) => {
      const argumentIndex = explicitIndex ? Number(explicitIndex) - 1 : index++;
      return String(args[argumentIndex] ?? '');
    });
  },
}));

vi.mock('../../../api/gpuApi', async (importOriginal) => {
  const actual = await importOriginal<typeof gpuApi>();
  return { ...actual, fetchGpuStatus: fetchGpuStatusMock };
});

vi.mock('../../../api/settingsApi', () => ({
  fetchSettings: fetchSettingsMock,
}));

vi.mock('../../../hooks/useBulkDescribe', () => ({
  useBulkDescribe: () => bulkDescribeState,
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

vi.mock('../MediaSelectionTableBody', () => ({
  MediaSelectionTableBody: () => null,
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
      mediaQuery: {
        data: { items: [], total: 0, totalPages: 1 },
        isPending: false,
        isFetching: false,
        isError: false,
        isSuccess: true,
        refetch: vi.fn(),
        itemsWithIdentities: [],
        detailQuery: {
          data: { detailsByMedia: {}, limit: 100, total: 0, truncated: false },
          isPending: false,
          isLoading: false,
          isFetching: false,
          isError: false,
          refetch: vi.fn(),
        },
        identitiesQuery: {
          data: { identities_by_media: {}, data_source: 'local_projection' },
          isLoading: false,
          isError: false,
          isPlaceholderData: false,
          isFetching: false,
          refetch: vi.fn(),
        },
      },
      statusMessage: '',
      isStatusPending: false,
      detailTruncationNotice: null,
      hasIdentities: false,
    },
  }),
}));

vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: false, progress: null },
    scanAndWait: vi.fn(),
    cancelScan: vi.fn(),
    history: { activeJobIds: [] },
  }),
}));

const statusResponse = () => ({
  gpu_state: {
    state: GPU_STATE.STOPPED,
    instance_id: null,
    written_at: 1_700_000_000,
    reason: null,
    since: null,
    intent: 'auto',
    intent_expires_at: null,
    intent_status: 'none',
    honoured_nonce: null,
    lease_expires_at: null,
    instance_running_since: null,
    last_transition_reason: 'unknown',
  },
  snapshot_age_seconds: 1,
  snapshot_fresh: true,
  intent: null,
  load: { has_work: false, written_at: 1_700_000_001, fresh: true },
  server_time: '2026-09-17T00:00:00Z',
});

const runResponse = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'tenant',
  run_id: 'run-terminal',
  status: DESCRIBE_RUN_STATUS.RUNNING,
  phase: DESCRIBE_RUN_PHASE.DESCRIBING,
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 2,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: GPU_STATE.UNKNOWN,
  recognition_enabled: false,
  ...overrides,
});

const progressFromRun = (run: DescribeRunResponse): DescribeRunProgress => ({
  run,
  status: run.status,
  progressFraction: run.total > 0 ? (run.completed + run.failed + run.skipped) / run.total : 0,
  etaSeconds: run.eta_seconds,
  gpuState: isGpuState(run.gpu_state) ? run.gpu_state : GPU_STATE.UNKNOWN,
  startupId: run.startup_id ?? null,
  isWarming: run.phase === DESCRIBE_RUN_PHASE.WARMING,
  isTerminal: isDescribeRunTerminal(run.status),
  stalledForSeconds: null,
  isPolling: !isDescribeRunTerminal(run.status),
  isFrozen: false,
  isError: false,
  error: null,
  retry: vi.fn(),
  timing: run.timing ?? null,
});

const renderSelection = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MediaSelection />
    </QueryClientProvider>,
  );
};

describe('MediaSelection GPU status wiring [GPUFLOW-2-F6BI-08][GPUFLOW-2-SPAOPERATIONSTORE-R-10]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchGpuStatusMock.mockResolvedValue(statusResponse());
    fetchSettingsMock.mockResolvedValue({ recognition_enabled: false });
    Object.assign(bulkDescribeState, {
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
        gpuState: GPU_STATE.UNKNOWN,
        startupId: null,
        isWarming: false,
        timing: null,
        retry: vi.fn(),
        error: null,
        stalledForSeconds: null,
        isFrozen: false,
      },
      runId: null,
      activeRunId: null,
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('mounts the shared GPU status and polls while idle', async () => {
    renderSelection();

    const status = await screen.findByRole('status', {
      name: 'Description Service is off — it starts when you describe',
    });
    expect(status).toHaveAttribute('data-gpu-state', GPU_STATE.STOPPED);
    await waitFor(() => expect(fetchGpuStatusMock).toHaveBeenCalledTimes(1));
  });

  it('keeps terminal summary/review visible without offering cancel or treating GPU as run-pending', async () => {
    const terminalRun = runResponse({
      status: DESCRIBE_RUN_STATUS.COMPLETED,
      phase: DESCRIBE_RUN_PHASE.COMPLETE,
      completed: 2,
      total: 2,
      gpu_state: GPU_STATE.READY,
    });
    Object.assign(bulkDescribeState, {
      runId: terminalRun.run_id,
      activeRunId: null,
      progress: progressFromRun(terminalRun),
    });

    renderSelection();

    expect(await screen.findByText('✔ 2 drafts ready to review')).toBeInTheDocument();
    const reviewLink = screen.getByRole('link', { name: 'Review drafts' });
    expect(reviewLink).toHaveAttribute('href', '#/description-history?run=run-terminal');
    expect(screen.queryByRole('button', { name: 'Cancel describe run' })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchGpuStatusMock).toHaveBeenCalledTimes(1));
  });

  it('pauses the idle status query while a run is in flight', async () => {
    const activeRun = runResponse({
      run_id: 'run-active',
      status: DESCRIBE_RUN_STATUS.RUNNING,
      phase: DESCRIBE_RUN_PHASE.WARMING,
      gpu_state: GPU_STATE.WARMING,
    });
    Object.assign(bulkDescribeState, {
      runId: activeRun.run_id,
      activeRunId: activeRun.run_id,
      progress: progressFromRun(activeRun),
    });

    renderSelection();

    expect(await screen.findByRole('status', { name: 'Description Service is starting…' })).toBeInTheDocument();
    expect(fetchGpuStatusMock).not.toHaveBeenCalled();
  });
});
