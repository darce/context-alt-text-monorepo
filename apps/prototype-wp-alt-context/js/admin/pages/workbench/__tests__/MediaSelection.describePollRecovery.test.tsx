import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../../api/config';
import * as describeApi from '../../../api/describeApi';
import { DESCRIBE_RUN_PHASE, DESCRIBE_RUN_STATUS, GPU_STATE, type DescribeRunResponse } from '../../../api/describeApi';
import * as describeIdempotencyKey from '../../../api/describeIdempotencyKey';
import { _resetActiveDescribeRunForTests } from '../../../hooks/activeDescribeRun';
import {
  _resetDescribeOperationStoreForTests,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  DESCRIBE_RUN_RESUME_STATUS,
  describeOperationRunStorageKey,
  getDescribeRunContext,
  pendingTerminalRuns,
  putDescribeOperationContext,
} from '../../../hooks/describeOperationStore';
import { _resetCooldownForTests, openCooldown } from '../../../utils/recognitionCooldown';
import { ActivityStatusStrip } from '../ActivityStatusStrip';
import { MediaSelection } from '../MediaSelection';

const { selection } = vi.hoisted(() => {
  const selection: Record<string, boolean> = { '11': true };
  return { selection };
});

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _position, explicitIndex) =>
      String(args[explicitIndex ? Number(explicitIndex) - 1 : index++] ?? ''),
    );
  },
}));

vi.mock('../../../api/describeApi', async (importOriginal) => ({
  ...(await importOriginal<typeof describeApi>()),
  fetchBulkDescribeRun: vi.fn(),
  cancelBulkDescribeRun: vi.fn(),
  submitBulkDescribeRun: vi.fn(),
}));

vi.mock('../../../api/settingsApi', () => ({
  fetchSettings: vi.fn(() => Promise.resolve({ recognition_enabled: false })),
}));
vi.mock('../../../api/gpuApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/gpuApi')>()),
  fetchGpuStatus: vi.fn(() => Promise.resolve({ gpu_state: { state: 'ready' }, snapshot_fresh: true })),
}));
vi.mock('../../../hooks/useSyncOffline', () => ({ useSyncOffline: () => false }));
vi.mock('../MediaSelectionTableBody', () => ({ MediaSelectionTableBody: () => null }));
vi.mock('../WorkbenchNavContext', () => ({ useWorkbenchNav: () => ({ setAdvancedOpen: vi.fn() }) }));
vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: false, progress: null },
    scanAndWait: vi.fn(),
    cancelScan: vi.fn(),
    history: { activeJobIds: [] },
  }),
}));
vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({
    selection: { selection, toggleRow: vi.fn(), toggleAll: vi.fn() },
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
        isError: false,
        refetch: vi.fn(),
        detailQuery: { isPending: false, isLoading: false, isFetching: false, isError: false, refetch: vi.fn() },
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
    },
  }),
}));

const TENANT = 'tenant-recovery';
const run = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: TENANT,
  run_id: 'run-A',
  status: DESCRIBE_RUN_STATUS.RUNNING,
  phase: DESCRIBE_RUN_PHASE.DESCRIBING,
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 1,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: GPU_STATE.READY,
  recognition_enabled: false,
  ...overrides,
});
const poll = vi.mocked(describeApi.fetchBulkDescribeRun);
const submit = vi.mocked(describeApi.submitBulkDescribeRun);
const cancel = vi.mocked(describeApi.cancelBulkDescribeRun);
let client: QueryClient;

const mount = () =>
  render(
    <QueryClientProvider client={client}>
      <ActivityStatusStrip />
      <MediaSelection />
    </QueryClientProvider>,
  );
const readRun = async () => {
  await act(async () => {
    await client.refetchQueries({ queryKey: ['bulkDescribeRun', 'run-A'], exact: true });
  });
};
const confirmCancel = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'Cancel run' }));
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel run' }));
};
const expectRetainedRun = () => {
  expect(getDescribeRunContext()?.id).toBe('run-A');
  const stored: unknown = JSON.parse(sessionStorage.getItem(describeOperationRunStorageKey(TENANT)) ?? 'null');
  expect(stored).toMatchObject({ id: 'run-A' });
  expect(submit).toHaveBeenCalledTimes(1);
};

describe('MediaSelection accepted-run polling recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetActiveDescribeRunForTests();
    _resetDescribeOperationStoreForTests();
    _resetCooldownForTests();
    sessionStorage.clear();
    resetConfigCache();
    registerConfig({ nonce: 'test', ajaxUrl: '/wp-admin/admin-ajax.php', endpoints: {}, tenant_id: TENANT });
    Object.keys(selection).forEach((key) => delete selection[key]);
    selection['11'] = true;
    client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    submit.mockResolvedValue(run());
    poll.mockResolvedValue(run());
    cancel.mockResolvedValue(run({ cancel_requested: true }));
  });

  afterEach(async () => {
    cleanup();
    await client.cancelQueries();
    client.clear();
    _resetActiveDescribeRunForTests();
    _resetDescribeOperationStoreForTests();
    _resetCooldownForTests();
    sessionStorage.clear();
    resetConfigCache();
    vi.restoreAllMocks();
  });

  it.each(['first read', 'later poll'] as const)(
    'holds the accepted selection after a failed %s until an authoritative terminal read',
    async (failureAt) => {
      const keys = vi.spyOn(describeIdempotencyKey, 'createDescribeIdempotencyKey');
      if (failureAt === 'first read') {
        poll.mockRejectedValue(new Error('lost run status'));
      }
      mount();
      const describeButton = await screen.findByRole('button', { name: 'Describe 1 selected' });
      fireEvent.click(describeButton);
      await waitFor(() => expect(getDescribeRunContext()?.id).toBe('run-A'));
      if (failureAt === 'later poll') {
        await screen.findByText('Describing…');
        poll.mockRejectedValue(new Error('lost run status'));
        await readRun();
      }
      await screen.findByRole('button', { name: 'Retry' });
      expect(describeButton).toBeDisabled();
      fireEvent.click(describeButton);
      expectRetainedRun();
      expect(keys).toHaveBeenCalledTimes(1);

      let resolveCancel!: (value: DescribeRunResponse) => void;
      cancel.mockReturnValue(
        new Promise((resolve) => {
          resolveCancel = resolve;
        }),
      );
      await confirmCancel();
      await waitFor(() => expect(cancel).toHaveBeenCalledExactlyOnceWith('run-A'));
      expect(describeButton).toBeDisabled();
      expectRetainedRun();
      await act(async () => {
        resolveCancel(run({ cancel_requested: true }));
        await Promise.resolve();
      });
      // An acknowledged cancellation request still leaves paid work unresolved.
      expect(describeButton).toBeDisabled();
      expectRetainedRun();

      // A failed subsequent poll can be retried only against the accepted identity.
      await readRun();
      poll.mockResolvedValue(run({ cancel_requested: true }));
      const reads = poll.mock.calls.length;
      fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
      await waitFor(() => expect(poll.mock.calls.length).toBeGreaterThan(reads));
      expect(poll.mock.calls.every(([runId]) => runId === 'run-A')).toBe(true);
      await waitFor(() => expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument());
      expect(screen.queryByRole('button', { name: 'Cancel run' })).not.toBeInTheDocument();
      expect(describeButton).toBeDisabled();
      expectRetainedRun();

      poll.mockResolvedValue(run({ status: DESCRIBE_RUN_STATUS.CANCELLED, phase: DESCRIBE_RUN_PHASE.CANCELLED }));
      await readRun();
      await waitFor(() => expect(getDescribeRunContext()).toBeNull());
      expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).toBeNull();
      expect(describeButton).toBeEnabled();
      submit.mockResolvedValue(run({ run_id: 'run-B' }));
      poll.mockImplementation((runId) => Promise.resolve(run({ run_id: runId })));
      fireEvent.click(describeButton);
      await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
      expect(keys).toHaveBeenCalledTimes(2);
      expect(submit.mock.calls[1][1]).not.toBe(submit.mock.calls[0][1]);
      await waitFor(() => expect(getDescribeRunContext()?.id).toBe('run-B'));
    },
  );

  it('honours cooldown for recovery Retry while still allowing Cancel', async () => {
    poll.mockRejectedValue(new Error('lost run status'));
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Describe 1 selected' }));
    const retry = await screen.findByRole('button', { name: 'Retry' });
    const reads = poll.mock.calls.length;
    act(() => openCooldown(30));
    fireEvent.click(retry);
    await act(async () => {
      await Promise.resolve();
    });
    expect(poll).toHaveBeenCalledTimes(reads);
    expect(screen.getByRole('button', { name: 'Cancel run' })).toBeEnabled();
    expectRetainedRun();
    act(() => _resetCooldownForTests());
    fireEvent.click(retry);
    await waitFor(() => expect(poll.mock.calls.length).toBeGreaterThan(reads));
    expectRetainedRun();
  });

  it('holds a restored unresolved run through a failed first read and settles it on Retry', async () => {
    putDescribeOperationContext({
      version: DESCRIBE_OPERATION_CONTEXT_VERSION,
      kind: DESCRIBE_OPERATION_KIND.RUN,
      id: 'run-A',
      startup_id: null,
      started_at: Date.now(),
      request: { writeAlt: false, force: false },
      status: DESCRIBE_RUN_RESUME_STATUS.NEEDS_TERMINAL_CHECK,
    });
    poll.mockRejectedValue(new Error('lost run status'));
    mount();
    const retry = await screen.findByRole('button', { name: 'Retry' });
    const describeButton = screen.getByRole('button', { name: 'Describe 1 selected' });
    expect(describeButton).toBeDisabled();
    fireEvent.click(describeButton);
    expect(submit).not.toHaveBeenCalled();
    expect(pendingTerminalRuns().map(({ id }) => id)).toEqual(['run-A']);
    expect(screen.getByRole('button', { name: 'Cancel run' })).toBeEnabled();
    poll.mockResolvedValue(
      run({ status: DESCRIBE_RUN_STATUS.COMPLETED, phase: DESCRIBE_RUN_PHASE.COMPLETE, completed: 1 }),
    );
    fireEvent.click(retry);
    await waitFor(() => expect(pendingTerminalRuns()).toEqual([]));
    expect(describeButton).toBeEnabled();
    expect(poll.mock.calls.every(([runId]) => runId === 'run-A')).toBe(true);
    expect(submit).not.toHaveBeenCalled();
  });

  it('preserves the existing different-selection action without releasing the accepted selection', async () => {
    poll.mockRejectedValue(new Error('lost run status'));
    const mounted = mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Describe 1 selected' }));
    await screen.findByRole('button', { name: 'Retry' });
    delete selection['11'];
    selection['12'] = true;
    mounted.rerender(
      <QueryClientProvider client={client}>
        <ActivityStatusStrip />
        <MediaSelection />
      </QueryClientProvider>,
    );
    expect(screen.getByRole('button', { name: 'Describe 1 selected' })).toBeEnabled();
    expectRetainedRun();
    delete selection['12'];
    selection['11'] = true;
    mounted.rerender(
      <QueryClientProvider client={client}>
        <ActivityStatusStrip />
        <MediaSelection />
      </QueryClientProvider>,
    );
    expect(screen.getByRole('button', { name: 'Describe 1 selected' })).toBeDisabled();
    expectRetainedRun();
  });

  it.each(['first read', 'later poll'] as const)('holds overlapping selections after a lost %s', async (failureAt) => {
    const keys = vi.spyOn(describeIdempotencyKey, 'createDescribeIdempotencyKey');
    if (failureAt === 'first read') poll.mockRejectedValue(new Error('lost run status'));
    const mounted = mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Describe 1 selected' }));
    await waitFor(() => expect(getDescribeRunContext()?.id).toBe('run-A'));
    if (failureAt === 'later poll') {
      await screen.findByText('Describing…');
      poll.mockRejectedValue(new Error('lost run status'));
      await readRun();
    }
    await screen.findByRole('button', { name: 'Retry' });
    for (const ids of [[11, 12], [12, 11], [11]]) {
      Object.keys(selection).forEach((key) => delete selection[key]);
      ids.forEach((id) => { selection[String(id)] = true; });
      mounted.rerender(<QueryClientProvider client={client}><ActivityStatusStrip /><MediaSelection /></QueryClientProvider>);
      const button = screen.getByRole('button', { name: `Describe ${ids.length} selected` });
      expect(button).toBeDisabled();
      fireEvent.click(button);
      expectRetainedRun();
      expect(keys).toHaveBeenCalledTimes(1);
    }
  });

  it('parks every unresolved run before a disjoint submit and keeps its selection and recovery actions after remount', async () => {
    poll.mockRejectedValue(new Error('lost run status'));
    let mounted = mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Describe 1 selected' }));
    await screen.findByRole('button', { name: 'Retry' });
    for (const [id, runId] of [[12, 'run-B'], [13, 'run-C']] as const) {
      Object.keys(selection).forEach((key) => delete selection[key]);
      selection[String(id)] = true;
      mounted.rerender(<QueryClientProvider client={client}><ActivityStatusStrip /><MediaSelection /></QueryClientProvider>);
      const button = screen.getByRole('button', { name: 'Describe 1 selected' });
      expect(button).toBeEnabled();
      submit.mockResolvedValue(run({ run_id: runId }));
      fireEvent.click(button);
      await waitFor(() => expect(getDescribeRunContext()?.id).toBe(runId));
      await waitFor(() => expect(client.getQueryState(['bulkDescribeRun', runId])?.status).toBe('error'));
    }
    expect(pendingTerminalRuns().map(({ id }) => id)).toEqual(['run-A', 'run-B']);
    expect(submit.mock.calls.map(([ids]) => ids)).toEqual([[11], [12], [13]]);
    expect(new Set(submit.mock.calls.map(([, key]) => key)).size).toBe(3);
    mounted.unmount();
    _resetDescribeOperationStoreForTests();
    Object.keys(selection).forEach((key) => delete selection[key]);
    selection['11'] = true;
    selection['12'] = true;
    mounted = mount();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Describe 2 selected' })).toBeDisabled());
    expect(pendingTerminalRuns().map(({ id }) => id)).toEqual(['run-A', 'run-B']);
    const recoveryA = within(await screen.findByRole('region', { name: 'Describe run run-A' }));
    const recoveryB = within(await screen.findByRole('region', { name: 'Describe run run-B' }));
    poll.mockImplementation((runId) => runId === 'run-B'
      ? Promise.resolve(run({ run_id: runId, cancel_requested: true }))
      : Promise.reject(new Error('lost run status')));
    fireEvent.click(recoveryB.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(recoveryB.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument());
    expect(poll.mock.calls.at(-1)?.[0]).toBe('run-B');
    expect(pendingTerminalRuns().map(({ id }) => id)).toEqual(['run-A', 'run-B']);
    fireEvent.click(recoveryA.getByRole('button', { name: 'Cancel run' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel run' }));
    await waitFor(() => expect(cancel).toHaveBeenCalledExactlyOnceWith('run-A'));
    await waitFor(() => expect(recoveryA.queryByRole('button', { name: 'Cancel run' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Describe 2 selected' })).toBeDisabled();
    for (const runId of ['run-B', 'run-A']) {
      poll.mockImplementation((id) => id === runId
        ? Promise.resolve(run({ run_id: id, status: DESCRIBE_RUN_STATUS.COMPLETED, phase: DESCRIBE_RUN_PHASE.COMPLETE }))
        : Promise.reject(new Error('lost run status')));
      await act(async () => { await client.refetchQueries({ queryKey: ['bulkDescribeRun', runId], exact: true }); });
      await waitFor(() => expect(pendingTerminalRuns().some(({ id }) => id === runId)).toBe(false));
    }
    await waitFor(() => expect(screen.getByRole('button', { name: 'Describe 2 selected' })).toBeEnabled());
    expect(getDescribeRunContext()?.id).toBe('run-C');
    delete selection['11'];
    delete selection['12'];
    selection['13'] = true;
    mounted.rerender(<QueryClientProvider client={client}><ActivityStatusStrip /><MediaSelection /></QueryClientProvider>);
    expect(screen.getByRole('button', { name: 'Describe 1 selected' })).toBeDisabled();
    expect(submit).toHaveBeenCalledTimes(3);
  });

  it('releases the selection when Cancel returns authoritative terminal cancellation', async () => {
    poll.mockRejectedValue(new Error('lost run status'));
    cancel.mockResolvedValue(run({ status: DESCRIBE_RUN_STATUS.CANCELLED, phase: DESCRIBE_RUN_PHASE.CANCELLED }));
    mount();
    const describeButton = await screen.findByRole('button', { name: 'Describe 1 selected' });
    fireEvent.click(describeButton);
    await screen.findByRole('button', { name: 'Retry' });
    await confirmCancel();
    await waitFor(() => expect(getDescribeRunContext()).toBeNull());
    expect(describeButton).toBeEnabled();
    expect(cancel).toHaveBeenCalledExactlyOnceWith('run-A');
    expect(submit).toHaveBeenCalledTimes(1);
  });
});
