import { QueryClient } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { buildTestQueryClient, createQueryWrapper } from '../../test-utils/queryClient';
import { registerConfig, resetConfigCache } from '../../api/config';
import * as describeApi from '../../api/describeApi';
import type { DescribeRunResponse } from '../../api/describeApi';
import { queryKeys } from '../../api/queryKeys';
import type { WorkbenchMediaResponse } from '../../api/workbenchMediaApi';
import { setActiveDescribeRunId } from '../activeDescribeRun';
import {
  _resetDescribeOperationStoreForTests,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  describeOperationRunStorageKey,
  getDescribeRunContext,
  isDescribeOperationExpired,
  type DescribeOperationContextInput,
} from '../describeOperationStore';
import {
  formatBulkDescribeErrorMessage,
  persistRunContext,
  useBulkDescribe,
} from '../useBulkDescribe';
import { SUGGEST_WARMING_HARD_CEILING_MS } from '../useDescribeMedia';
import { mediaStatsMissingQueryKey, mediaStatsTotalQueryKey } from '../useMediaStats';
import { MEDIA_PAGE_SIZE_OPTIONS } from '../useWorkbenchFilters';

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return {
    ...actual,
    cancelBulkDescribeRun: vi.fn(),
    submitBulkDescribeRun: vi.fn(),
    fetchBulkDescribeRun: vi.fn(),
  };
});

const submitBulkDescribeRunMock = vi.mocked(describeApi.submitBulkDescribeRun);
const cancelBulkDescribeRunMock = vi.mocked(describeApi.cancelBulkDescribeRun);
const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);

const runResponse = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'tenant',
  run_id: 'run-1',
  status: 'pending',
  phase: 'queued',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 2,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: null,
  // Snapshot of the site's recognition setting at submit (schema default true); this test's world is recognition-on.
  recognition_enabled: true,
  ...overrides,
});

const defaultPerPage = MEDIA_PAGE_SIZE_OPTIONS[0];
const largePerPage = MEDIA_PAGE_SIZE_OPTIONS[MEDIA_PAGE_SIZE_OPTIONS.length - 1];

const workbenchListPageKeys = [
  ...MEDIA_PAGE_SIZE_OPTIONS.map((perPage) =>
    queryKeys.media.workbenchPage({ page: 1, perPage, status: 'all' }),
  ),
  queryKeys.media.workbenchPage({
    page: 1,
    perPage: defaultPerPage,
    status: 'all',
    search: 'ada',
  }),
  queryKeys.media.workbenchPage({
    page: 1,
    perPage: largePerPage,
    status: 'all',
    search: '',
  }),
];

const emptyPage: WorkbenchMediaResponse = { items: [], total: 0, totalPages: 0 };

const seedWorkbenchCache = (client: QueryClient): void => {
  for (const key of workbenchListPageKeys) {
    client.setQueryData(key, emptyPage);
  }
  client.setQueryData(mediaStatsTotalQueryKey, { items: [], total: 10, totalPages: 10 });
  client.setQueryData(mediaStatsMissingQueryKey, { items: [], total: 3, totalPages: 3 });
};

const resetCachedQueries = (client: QueryClient): void => {
  for (const key of workbenchListPageKeys) {
    client.removeQueries({ queryKey: key });
  }
  client.removeQueries({ queryKey: mediaStatsTotalQueryKey });
  client.removeQueries({ queryKey: mediaStatsMissingQueryKey });
  seedWorkbenchCache(client);
};

const expectListPagesInvalidated = (client: QueryClient, invalidated: boolean): void => {
  for (const key of workbenchListPageKeys) {
    expect(client.getQueryState(key)?.isInvalidated).toBe(invalidated);
  }
};

let queryClient: QueryClient;
let wrapper: ReturnType<typeof createQueryWrapper>;

const createSeededWrapper = (): {
  wrapper: ReturnType<typeof createQueryWrapper>;
  queryClient: QueryClient;
} => {
  const queryClient = buildTestQueryClient();
  seedWorkbenchCache(queryClient);
  return { wrapper: createQueryWrapper(queryClient), queryClient };
};

const TENANT = 'tenant';

const storedRunContext = (
  overrides: Partial<DescribeOperationContextInput> = {},
): DescribeOperationContextInput => ({
  version: DESCRIBE_OPERATION_CONTEXT_VERSION,
  kind: DESCRIBE_OPERATION_KIND.RUN,
  id: 'run-seeded',
  startup_id: 'startup-seeded',
  started_at: 1_700_000_000_000,
  request: { writeAlt: false, force: false },
  ...overrides,
});

describe('useBulkDescribe', () => {
  beforeEach(() => {
    queryClient = buildTestQueryClient();
    wrapper = createQueryWrapper(queryClient);
    vi.clearAllMocks();
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    resetConfigCache();
    registerConfig({
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {},
      tenant_id: TENANT,
    });
    // Default: a terminal poll response so no test leaves the interval polling.
    fetchBulkDescribeRunMock.mockResolvedValue(runResponse({ status: 'completed' }));
  });

  afterEach(() => {
    queryClient.clear();
    setActiveDescribeRunId(null);
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    resetConfigCache();
  });

  it('submits media ids with an action key and captures the run id', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(runResponse({ run_id: 'run-1', status: 'pending' }));
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-1', status: 'running', phase: 'describing' }),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([101, 202]);

    await waitFor(() => expect(result.current.submit.isSuccess).toBe(true));
    expect(submitBulkDescribeRunMock).toHaveBeenCalledWith(
      [101, 202],
      expect.stringMatching(/^[A-Za-z0-9_-]{16,128}$/),
    );
    expect(result.current.submit.data?.run_id).toBe('run-1');
    await waitFor(() => expect(result.current.runId).toBe('run-1'));
  });

  it('reuses one key across an automatic retry and creates a new key for a new submit', async () => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: 1, retryDelay: 0 },
      },
    });
    wrapper = createQueryWrapper(queryClient);
    submitBulkDescribeRunMock
      .mockRejectedValueOnce(new Error('temporary submit failure'))
      .mockResolvedValue(runResponse({ run_id: 'run-retried', status: 'pending' }));

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([101, 202]);

    await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(2));
    const firstActionKey = submitBulkDescribeRunMock.mock.calls[0]?.[1];
    expect(firstActionKey).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[1]).toBe(firstActionKey);

    result.current.submit.mutate([101, 202]);

    await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(3));
    const nextActionKey = submitBulkDescribeRunMock.mock.calls[2]?.[1];
    expect(nextActionKey).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(nextActionKey).not.toBe(firstActionKey);
  });

  it('replays the same action key and frozen media payload after an ambiguous failure', async () => {
    const submittedMediaIds = [101, 202];
    submitBulkDescribeRunMock
      .mockRejectedValueOnce(new Error('Connection lost after submit'))
      .mockResolvedValue(runResponse({ run_id: 'run-recovered', status: 'pending' }));

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate(submittedMediaIds);
    submittedMediaIds.reverse();

    await waitFor(() => expect(result.current.submit.isError).toBe(true));
    const firstActionKey = submitBulkDescribeRunMock.mock.calls[0]?.[1];
    expect(submitBulkDescribeRunMock.mock.calls[0]?.[0]).toEqual([101, 202]);

    result.current.submit.mutate([101, 202]);

    await waitFor(() => expect(result.current.submit.isSuccess).toBe(true));
    expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(2);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[0]).toEqual([101, 202]);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[1]).toBe(firstActionKey);
  });

  it('polls run status and reflects backend eta_seconds + progress fraction', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(runResponse({ run_id: 'run-9', status: 'pending' }));
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-9', status: 'running', completed: 1, total: 4, eta_seconds: 42 }),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.status).toBe('running'));
    expect(fetchBulkDescribeRunMock).toHaveBeenCalledWith('run-9');
    // ETA is consumed verbatim from the backend, not recomputed.
    expect(result.current.progress.etaSeconds).toBe(42);
    expect(result.current.progress.progressFraction).toBeCloseTo(0.25);
    expect(result.current.progress.isTerminal).toBe(false);
    expect(result.current.progress.isPolling).toBe(true);
  });

  it('marks the run terminal and stops polling when status is completed', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(runResponse({ run_id: 'run-done', status: 'pending' }));
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-done', status: 'completed', completed: 4, total: 4, eta_seconds: 0 }),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.isTerminal).toBe(true));
    expect(result.current.progress.status).toBe('completed');
    expect(result.current.progress.progressFraction).toBe(1);
    expect(result.current.progress.isPolling).toBe(false);
  });

  it('cancels the active run id', async () => {
    cancelBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-2', status: 'cancelled', phase: 'cancelled', skipped: 2, cancel_requested: true }),
    );
    fetchBulkDescribeRunMock
      .mockResolvedValueOnce(runResponse({ run_id: 'run-2', status: 'running' }))
      .mockResolvedValueOnce(runResponse({ run_id: 'run-2', status: 'cancelled', phase: 'cancelled' }));
    setActiveDescribeRunId('run-2');

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    await waitFor(() => expect(result.current.progress.status).toBe('running'));
    result.current.cancel.mutate('run-2');

    await waitFor(() => expect(result.current.cancel.isSuccess).toBe(true));
    expect(cancelBulkDescribeRunMock).toHaveBeenCalledWith('run-2');
    result.current.progress.retry();
    await waitFor(() => expect(result.current.activeRunId).toBeNull());
    expect(result.current.runId).toBe('run-2');
    expect(result.current.progress.run).toMatchObject({ run_id: 'run-2', status: 'cancelled' });
    expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).toBeNull();
  });

  it('persists startup_id from the submit response for resume', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-persist', status: 'pending', startup_id: 'startup-from-run' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-persist', status: 'running', phase: 'warming', total: 2 }),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([1, 2]);

    await waitFor(() => expect(result.current.runId).toBe('run-persist'));
    const raw = sessionStorage.getItem(describeOperationRunStorageKey(TENANT));
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw ?? '{}')).toMatchObject({
      version: DESCRIBE_OPERATION_CONTEXT_VERSION,
      kind: DESCRIBE_OPERATION_KIND.RUN,
      id: 'run-persist',
      startup_id: 'startup-from-run',
    });
    expect(getDescribeRunContext()?.id).toBe('run-persist');
  });

  it('exports persistRunContext so a second caller can persist a new run the same way', () => {
    persistRunContext(runResponse({ run_id: 'run-export', startup_id: 'startup-export' }));
    expect(getDescribeRunContext()).toMatchObject({
      version: DESCRIBE_OPERATION_CONTEXT_VERSION,
      kind: DESCRIBE_OPERATION_KIND.RUN,
      id: 'run-export',
      startup_id: 'startup-export',
    });
  });

  it('persists startup_budget_seconds so a resumed run expires at the warming ceiling (FIN-07)', () => {
    persistRunContext(runResponse({ run_id: 'run-bound', startup_id: 'startup-bound' }));
    const context = getDescribeRunContext();
    if (context === null) {
      throw new Error('expected persisted run context');
    }
    expect(context.startup_budget_seconds).toBe(SUGGEST_WARMING_HARD_CEILING_MS / 1000);
    expect(
      isDescribeOperationExpired(context, context.started_at + SUGGEST_WARMING_HARD_CEILING_MS),
    ).toBe(true);
  });

  it('resumes a seeded run from sessionStorage without a new submit', async () => {
    sessionStorage.setItem(
      describeOperationRunStorageKey(TENANT),
      JSON.stringify(storedRunContext({ id: 'run-seeded' })),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-seeded', status: 'running', phase: 'warming', total: 2 }),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });

    await waitFor(() => expect(result.current.runId).toBe('run-seeded'));
    expect(submitBulkDescribeRunMock).not.toHaveBeenCalled();
    await waitFor(() => expect(fetchBulkDescribeRunMock).toHaveBeenCalledWith('run-seeded'));
    expect(result.current.progress.isTerminal).toBe(false);
  });

  it('clears persisted storage on terminal status while retaining only the terminal summary id', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-done', status: 'pending', startup_id: 'startup-done' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-done', status: 'completed', completed: 4, total: 4, eta_seconds: 0 }),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.isTerminal).toBe(true));
    await waitFor(() => expect(result.current.activeRunId).toBeNull());
    expect(result.current.runId).toBe('run-done');
    expect(result.current.progress.run).toMatchObject({ run_id: 'run-done', status: 'completed' });
    await waitFor(() =>
      expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).toBeNull(),
    );

    submitBulkDescribeRunMock.mockResolvedValueOnce(
      runResponse({ run_id: 'run-fresh', status: 'pending', startup_id: 'startup-fresh' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValueOnce(
      runResponse({ run_id: 'run-fresh', status: 'running', phase: 'describing' }),
    );
    result.current.submit.mutate([5, 6]);

    await waitFor(() => expect(result.current.runId).toBe('run-fresh'));
    expect(result.current.runId).not.toBe('run-done');
  });

  it('does not expose or poll a terminal summary across tenant changes', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-tenant-a', status: 'pending' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-tenant-a', status: 'completed', completed: 2, total: 2 }),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([1, 2]);

    await waitFor(() => expect(result.current.runId).toBe('run-tenant-a'));
    await waitFor(() => expect(result.current.activeRunId).toBeNull());
    expect(result.current.progress.run?.run_id).toBe('run-tenant-a');
    const callsBeforeTenantSwitch = fetchBulkDescribeRunMock.mock.calls.length;

    registerConfig({
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {},
      tenant_id: 'tenant-b',
    });
    // Create and clear a transient B context to exercise the store's existing
    // subscription path while leaving tenant B with no active run.
    setActiveDescribeRunId('run-tenant-b');
    setActiveDescribeRunId(null);

    await waitFor(() => {
      expect(result.current.runId).toBeNull();
      expect(result.current.activeRunId).toBeNull();
      expect(result.current.progress.isPolling).toBe(false);
    });
    expect(fetchBulkDescribeRunMock.mock.calls.slice(callsBeforeTenantSwitch)).not.toContainEqual([
      'run-tenant-a',
    ]);

    registerConfig({
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {},
      tenant_id: TENANT,
    });
    // Emit again after switching back. The terminal summary was cleared for B,
    // so returning to A must not resurrect it as an active run.
    setActiveDescribeRunId('run-tenant-a-new');
    setActiveDescribeRunId(null);

    await waitFor(() => {
      expect(result.current.runId).toBeNull();
      expect(result.current.activeRunId).toBeNull();
    });
    expect(fetchBulkDescribeRunMock.mock.calls.slice(callsBeforeTenantSwitch)).not.toContainEqual([
      'run-tenant-a',
    ]);
  });

  it('does not resume a completed run after remount once storage is cleared', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(runResponse({ run_id: 'run-done', status: 'pending' }));
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-done', status: 'completed', completed: 2, total: 2, eta_seconds: 0 }),
    );

    const { result, unmount } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([1, 2]);
    await waitFor(() => expect(result.current.progress.isTerminal).toBe(true));
    unmount();
    _resetDescribeOperationStoreForTests();

    const callsBeforeReload = fetchBulkDescribeRunMock.mock.calls.length;
    const remounted = renderHook(() => useBulkDescribe(), { wrapper });
    expect(remounted.result.current.runId).toBeNull();
    expect(fetchBulkDescribeRunMock.mock.calls.length).toBe(callsBeforeReload);
    remounted.unmount();
  });

  it('keeps a pending warmup across remount so navigation does not drop the run', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-warm', status: 'pending', startup_id: 'startup-warm' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-warm', status: 'running', phase: 'warming', total: 2 }),
    );

    const { result, unmount } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([1, 2]);
    await waitFor(() => expect(result.current.runId).toBe('run-warm'));
    expect(sessionStorage.getItem(describeOperationRunStorageKey(TENANT))).not.toBeNull();
    unmount();

    const remounted = renderHook(() => useBulkDescribe(), { wrapper });
    expect(remounted.result.current.runId).toBe('run-warm');
    expect(submitBulkDescribeRunMock).toHaveBeenCalledOnce();
    remounted.unmount();
  });

  it('surfaces a stranded run id in the error notice without starting a progress poll (BR-143)', async () => {
    // Membership write failed after the upstream run was accepted — 500 with
    // code describe_run_media_ids_store_failed and data.run_id populated. The
    // paid run is burning compute; the operator must see the id, and we must
    // NOT pretend submit succeeded by polling ([RLSE-04]).
    const strandedRunId = 'run-stranded-42';
    const payload = {
      code: 'describe_run_media_ids_store_failed',
      message: 'Failed to store describe run media membership.',
      data: { status: 500, run_id: strandedRunId },
    };
    submitBulkDescribeRunMock.mockRejectedValue(
      new Error(`Request to /acx/v1/describe/runs failed (500): ${JSON.stringify(payload)}`),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([101, 202]);

    await waitFor(() => expect(result.current.submit.isError).toBe(true));
    // runId stays null — no progress poll, no review link as if success.
    expect(result.current.runId).toBeNull();
    expect(result.current.progress.isPolling).toBe(false);
    expect(fetchBulkDescribeRunMock).not.toHaveBeenCalled();
    // Notice carries the resolved server message AND the stranded run id.
    expect(result.current.errorMessage).toContain('Failed to store describe run media membership.');
    expect(result.current.errorMessage).toContain(strandedRunId);
    expect(result.current.errorMessage).toContain('already running upstream');
    // Never the raw HTTPError envelope.
    expect(result.current.errorMessage).not.toContain('Request to /acx/v1/describe/runs failed');
  });

  it('does not invalidate workbench rows while the run is still describing', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-live', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-live',
        status: 'running',
        phase: 'describing',
        completed: 1,
        total: 4,
        eta_seconds: 42,
      }),
    );

    const { wrapper: scopedWrapper, queryClient } = createSeededWrapper();
    const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.run?.phase).toBe('describing'));
    expect(result.current.progress.isTerminal).toBe(false);
    expectListPagesInvalidated(queryClient, false);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    queryClient.clear();
  });

  it('invalidates workbench list pages exactly once when the run reaches a terminal phase [S6-F1]', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-term', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-term',
        status: 'running',
        phase: 'describing',
        completed: 1,
        total: 4,
      }),
    );

    const { wrapper: scopedWrapper, queryClient } = createSeededWrapper();
    const { result, rerender } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.run?.phase).toBe('describing'));
    expectListPagesInvalidated(queryClient, false);

    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-term',
        status: 'completed',
        phase: 'complete',
        completed: 4,
        total: 4,
        eta_seconds: 0,
      }),
    );
    result.current.progress.retry();
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expect(result.current.progress.isTerminal).toBe(true);
    expectListPagesInvalidated(queryClient, true);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(mediaStatsMissingQueryKey)?.isInvalidated).toBe(false);

    // Subsequent polls / renders at the same terminal phase must not refetch again.
    resetCachedQueries(queryClient);
    expectListPagesInvalidated(queryClient, false);
    result.current.progress.retry();
    rerender();
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expectListPagesInvalidated(queryClient, false);
    queryClient.clear();
  });

  it('invalidates list pages once per successive terminal run id [S6-F2]', async () => {
    const { wrapper: scopedWrapper, queryClient } = createSeededWrapper();
    const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });

    submitBulkDescribeRunMock.mockResolvedValueOnce(
      runResponse({ run_id: 'run-a', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-a',
        status: 'completed',
        phase: 'complete',
        completed: 2,
        total: 2,
        eta_seconds: 0,
      }),
    );
    result.current.submit.mutate([1, 2]);
    await waitFor(() => expect(result.current.progress.run?.run_id).toBe('run-a'));
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expectListPagesInvalidated(queryClient, true);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);

    resetCachedQueries(queryClient);
    expectListPagesInvalidated(queryClient, false);

    submitBulkDescribeRunMock.mockResolvedValueOnce(
      runResponse({ run_id: 'run-b', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-b',
        status: 'completed',
        phase: 'complete',
        completed: 2,
        total: 2,
        eta_seconds: 0,
      }),
    );
    result.current.submit.mutate([3, 4]);
    await waitFor(() => expect(result.current.progress.run?.run_id).toBe('run-b'));
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expectListPagesInvalidated(queryClient, true);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    queryClient.clear();
  });

  it('invalidates workbench list pages once when status is terminal even if phase is stale [HARM-F4]', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-stale-phase', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-stale-phase',
        status: 'completed',
        phase: 'describing',
        completed: 4,
        total: 4,
        eta_seconds: 0,
      }),
    );

    const { wrapper: scopedWrapper, queryClient } = createSeededWrapper();
    const { result, rerender } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.isTerminal).toBe(true));
    expect(result.current.progress.status).toBe('completed');
    expect(result.current.progress.run?.phase).toBe('describing');
    expectListPagesInvalidated(queryClient, true);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(mediaStatsMissingQueryKey)?.isInvalidated).toBe(false);

    resetCachedQueries(queryClient);
    expectListPagesInvalidated(queryClient, false);
    result.current.progress.retry();
    rerender();
    await waitFor(() => expect(result.current.progress.isTerminal).toBe(true));
    expectListPagesInvalidated(queryClient, false);
    queryClient.clear();
  });

  it('does not invalidate workbench list pages when status is non-terminal [HARM-F4]', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-live-status', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-live-status',
        status: 'running',
        phase: 'complete',
        completed: 1,
        total: 4,
        eta_seconds: 42,
      }),
    );

    const { wrapper: scopedWrapper, queryClient } = createSeededWrapper();
    const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.status).toBe('running'));
    expect(result.current.progress.isTerminal).toBe(false);
    expect(result.current.progress.run?.phase).toBe('complete');
    expectListPagesInvalidated(queryClient, false);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    queryClient.clear();
  });

  it('does not invalidate again when the same runId changes complete → failed [S6-F2]', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-same', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-same',
        status: 'completed',
        phase: 'complete',
        completed: 2,
        total: 2,
        eta_seconds: 0,
      }),
    );

    const { wrapper: scopedWrapper, queryClient } = createSeededWrapper();
    const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2]);

    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expectListPagesInvalidated(queryClient, true);

    resetCachedQueries(queryClient);
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-same',
        status: 'failed',
        phase: 'failed',
        completed: 0,
        failed: 2,
        total: 2,
        eta_seconds: 0,
      }),
    );
    result.current.progress.retry();
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('failed'));
    expectListPagesInvalidated(queryClient, false);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    queryClient.clear();
  });

  it.each([
    { status: 'failed', phase: 'failed' },
    { status: 'cancelled', phase: 'cancelled' },
    { status: 'completed_with_errors', phase: 'complete' },
  ] as const)(
    'invalidates workbench list pages once for terminal $status / $phase [S6-F3]',
    async ({ status, phase }) => {
      submitBulkDescribeRunMock.mockResolvedValue(
        runResponse({ run_id: `run-${phase}`, status: 'pending', phase: 'queued' }),
      );
      fetchBulkDescribeRunMock.mockResolvedValue(
        runResponse({
          run_id: `run-${phase}`,
          status,
          phase,
          completed: status === 'failed' ? 0 : 3,
          failed: status === 'completed_with_errors' ? 1 : status === 'failed' ? 2 : 0,
          skipped: status === 'cancelled' ? 2 : 0,
          total: 4,
          eta_seconds: 0,
          cancel_requested: status === 'cancelled',
        }),
      );

      const { wrapper: scopedWrapper, queryClient } = createSeededWrapper();
      const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
      result.current.submit.mutate([1, 2, 3, 4]);

      await waitFor(() => expect(result.current.progress.run?.phase).toBe(phase));
      expect(result.current.progress.isTerminal).toBe(true);
      expectListPagesInvalidated(queryClient, true);
      expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);

      resetCachedQueries(queryClient);
      result.current.progress.retry();
      await waitFor(() => expect(result.current.progress.run?.phase).toBe(phase));
      expectListPagesInvalidated(queryClient, false);
      queryClient.clear();
    },
  );

  it('invalidates workbench list pages once across a same-runId terminal → live → terminal flip [S7-F1]', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-flip', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-flip',
        status: 'completed',
        phase: 'complete',
        completed: 4,
        total: 4,
        eta_seconds: 0,
      }),
    );

    const { wrapper: scopedWrapper, queryClient } = createSeededWrapper();
    const { result, rerender } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.isTerminal).toBe(true));
    expect(result.current.progress.status).toBe('completed');
    expectListPagesInvalidated(queryClient, true);

    // Flip isTerminal true → false so the effect re-runs, then back to true.
    // The once-per-run ref — not the dep array — must suppress the second write.
    resetCachedQueries(queryClient);
    expectListPagesInvalidated(queryClient, false);
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-flip',
        status: 'running',
        phase: 'describing',
        completed: 2,
        total: 4,
        eta_seconds: 20,
      }),
    );
    result.current.progress.retry();
    rerender();
    await waitFor(() => expect(result.current.progress.isTerminal).toBe(false));
    expect(result.current.progress.status).toBe('running');
    expectListPagesInvalidated(queryClient, false);

    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-flip',
        status: 'completed',
        phase: 'complete',
        completed: 4,
        total: 4,
        eta_seconds: 0,
      }),
    );
    result.current.progress.retry();
    rerender();
    await waitFor(() => expect(result.current.progress.isTerminal).toBe(true));
    expect(result.current.progress.status).toBe('completed');
    expectListPagesInvalidated(queryClient, false);
    queryClient.clear();
  });

  it.each([
    { status: 'failed' as const, phase: 'failed' as const },
    { status: 'cancelled' as const, phase: 'cancelled' as const },
  ])(
    'invalidates workbench list pages once when terminal status is $status [S7-F1]',
    async ({ status, phase }) => {
      submitBulkDescribeRunMock.mockResolvedValue(
        runResponse({ run_id: `run-s7-${status}`, status: 'pending', phase: 'queued' }),
      );
      fetchBulkDescribeRunMock.mockResolvedValue(
        runResponse({
          run_id: `run-s7-${status}`,
          status,
          phase,
          completed: status === 'failed' ? 0 : 2,
          failed: status === 'failed' ? 2 : 0,
          skipped: status === 'cancelled' ? 2 : 0,
          total: 2,
          eta_seconds: 0,
          cancel_requested: status === 'cancelled',
        }),
      );

      const { wrapper: scopedWrapper, queryClient } = createSeededWrapper();
      const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
      result.current.submit.mutate([1, 2]);

      await waitFor(() => expect(result.current.progress.isTerminal).toBe(true));
      expect(result.current.progress.status).toBe(status);
      expectListPagesInvalidated(queryClient, true);
      expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
      queryClient.clear();
    },
  );
});

describe('formatBulkDescribeErrorMessage', () => {
  it('includes data.run_id when the membership store fails after upstream accept', () => {
    const error = new Error(
      'Request to /acx/v1/describe/runs failed (500): {"code":"describe_run_media_ids_store_failed","message":"Failed to store describe run media membership.","data":{"status":500,"run_id":"run-99"}}',
    );
    const notice = formatBulkDescribeErrorMessage(error);
    expect(notice).toContain('run-99');
    expect(notice).toContain('Failed to store describe run media membership.');
    expect(notice).toContain('already running upstream');
  });

  it('falls back without inventing a run id when the payload has none', () => {
    const error = new Error(
      'Request to /acx/v1/describe/runs failed (500): {"code":"internal","message":"boom","data":{"status":500}}',
    );
    expect(formatBulkDescribeErrorMessage(error)).toBe('boom');
  });
});
