// @vitest-environment jsdom
import { QueryClient } from '@tanstack/react-query';
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerConfig, resetConfigCache } from '../../api/config';
import * as describeApi from '../../api/describeApi';
import {
  DESCRIBE_RUN_PHASE,
  DESCRIBE_RUN_STATUS,
  DESCRIBE_RUN_TERMINAL_CODE,
  GPU_STATE,
  type DescribeRunItem,
  type DescribeRunItemsResponse,
  type DescribeRunResponse,
} from '../../api/describeApi';
import * as gpuApi from '../../api/gpuApi';
import { GPU_INTENT_ACTION, GPU_INTENT_STATUS, type GpuStatusResponse } from '../../api/gpuApi';
import { AuthExpiredError, HTTPError } from '../../utils/http';
import {
  _resetDescribeOperationStoreForTests,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
  describeOperationPendingSubmitStorageKey,
  putDescribeOperationContext,
} from '../describeOperationStore';
import { useBulkDescribe } from '../useBulkDescribe';
import { ACTIVITY_REASON, useActivityStatus } from '../useActivityStatus';
import { buildTestQueryClient, createQueryWrapper } from '../../test-utils/queryClient';

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return {
    ...actual,
    fetchBulkDescribeRun: vi.fn(),
    fetchDescribeRunItems: vi.fn(),
    submitBulkDescribeRun: vi.fn(),
  };
});

vi.mock('../../api/gpuApi', async (importOriginal) => {
  const actual = await importOriginal<typeof gpuApi>();
  return { ...actual, fetchGpuStatus: vi.fn() };
});

const TENANT = 'tenant-afx';
const submitBulkDescribeRunMock = vi.mocked(describeApi.submitBulkDescribeRun);
const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);
const fetchDescribeRunItemsMock = vi.mocked(describeApi.fetchDescribeRunItems);
const fetchGpuStatusMock = vi.mocked(gpuApi.fetchGpuStatus);

const describeHttpError = (status: number): HTTPError =>
  new HTTPError({
    status,
    endpoint: '/acx/v1/describe/runs',
    bodyPreview: '',
    message: `Request failed (${status})`,
  });

const runResponse = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: TENANT,
  run_id: 'run-accepted',
  status: DESCRIBE_RUN_STATUS.PENDING,
  phase: DESCRIBE_RUN_PHASE.QUEUED,
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 2,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: GPU_STATE.STOPPED,
  recognition_enabled: false,
  ...overrides,
});

const warmupTimeoutRun = (runId: string): DescribeRunResponse & {
  terminal: { code: string; retryable: boolean; startup_budget_seconds: number };
} => ({
  ...runResponse({
    run_id: runId,
    status: DESCRIBE_RUN_STATUS.FAILED,
    phase: DESCRIBE_RUN_PHASE.FAILED,
    completed: 1,
    failed: 1,
    total: 3,
  }),
  terminal: {
    code: DESCRIBE_RUN_TERMINAL_CODE.GPU_WARMUP_TIMEOUT,
    retryable: true,
    startup_budget_seconds: 510,
  },
});

const describeItem = (mediaId: number, status = 'failed'): DescribeRunItem => ({
  media_id: mediaId,
  status,
  alt_text_draft: null,
  caption: null,
  provenance: null,
  tier: null,
  result_generation: 0,
  existing_alt: false,
});

const itemsResponse = (runId: string, items: DescribeRunItem[]): DescribeRunItemsResponse => ({
  run_id: runId,
  items,
});

const gpuStatus: GpuStatusResponse = {
  gpu_state: {
    state: GPU_STATE.STOPPED,
    instance_id: null,
    written_at: 1_700_000_000,
    reason: null,
    since: null,
    intent: GPU_INTENT_ACTION.AUTO,
    intent_expires_at: null,
    intent_status: GPU_INTENT_STATUS.NONE,
    honoured_nonce: null,
    lease_expires_at: null,
    instance_running_since: null,
    last_transition_reason: 'unknown',
  },
  snapshot_age_seconds: 12,
  snapshot_fresh: true,
  intent: null,
  load: { has_work: false, written_at: 1_700_000_004, fresh: true },
  server_time: '2026-09-07T12:00:00Z',
};

let queryClient: QueryClient;

const installTenant = (): void => {
  resetConfigCache();
  registerConfig({
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {},
    tenant_id: TENANT,
  });
};

describe('describe submit recovery across remounts', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Clear unconsumed once-responses before installing each test's defaults.
    submitBulkDescribeRunMock.mockReset();
    fetchBulkDescribeRunMock.mockReset();
    fetchDescribeRunItemsMock.mockReset();
    fetchGpuStatusMock.mockReset();
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    installTenant();
    queryClient = buildTestQueryClient();
    fetchGpuStatusMock.mockResolvedValue(gpuStatus);
    fetchBulkDescribeRunMock.mockImplementation(async (runId: string) => warmupTimeoutRun(runId));
    fetchDescribeRunItemsMock.mockResolvedValue(itemsResponse('run-source', [describeItem(51)]));
    submitBulkDescribeRunMock.mockResolvedValue(runResponse());
  });

  afterEach(async () => {
    await queryClient.cancelQueries();
    queryClient.clear();
    cleanup();
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    resetConfigCache();
  });

  it('reuses the bulk submit key after an ambiguous response and remount', async () => {
    const selectionKey = JSON.stringify([TENANT, [101, 202]]);
    submitBulkDescribeRunMock
      .mockImplementationOnce(async () => {
        const stored = sessionStorage.getItem(
          describeOperationPendingSubmitStorageKey(TENANT, { kind: 'bulk', selectionKey }),
        );
        expect(stored).not.toBeNull();
        throw new Error('Connection lost after submit');
      })
      .mockResolvedValueOnce(runResponse({ run_id: 'run-recovered' }));
    const wrapper = createQueryWrapper(queryClient);

    const firstMount = renderHook(() => useBulkDescribe(), { wrapper });
    act(() => firstMount.result.current.submit.mutate([202, 101]));
    await waitFor(() => expect(firstMount.result.current.submit.isError).toBe(true));
    const firstKey = submitBulkDescribeRunMock.mock.calls[0]?.[1];
    expect(firstKey).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(submitBulkDescribeRunMock.mock.calls[0]?.[0]).toEqual([101, 202]);
    firstMount.unmount();
    _resetDescribeOperationStoreForTests();

    const secondMount = renderHook(() => useBulkDescribe(), { wrapper });
    act(() => secondMount.result.current.submit.mutate([101, 202]));
    await waitFor(() => expect(secondMount.result.current.submit.isSuccess).toBe(true));

    expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(2);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[0]).toEqual([101, 202]);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[1]).toBe(firstKey);
  });

  it.each([
    ['auth expiry', () => new AuthExpiredError({ endpoint: '/acx/v1/describe/runs', status: 401 })],
    ['HTTP 401', () => describeHttpError(401)],
    ['HTTP 403', () => describeHttpError(403)],
    ['HTTP 408', () => describeHttpError(408)],
    ['HTTP 425', () => describeHttpError(425)],
    ['HTTP 429', () => describeHttpError(429)],
  ] as const)(
    'keeps the bulk submit key after an ambiguous response and %s refusal',
    async (_name, refusal) => {
      submitBulkDescribeRunMock
        .mockImplementationOnce(async () => {
          throw new Error('Connection lost after submit');
        })
        .mockImplementationOnce(async () => {
          throw refusal();
        })
        .mockResolvedValueOnce(runResponse({ run_id: 'run-recovered' }));

      const wrapper = createQueryWrapper(queryClient);
      const hook = renderHook(() => useBulkDescribe(), { wrapper });
      await act(async () => {
        await expect(hook.result.current.submit.mutateAsync([202, 101])).rejects.toBeDefined();
      });
      const firstKey = submitBulkDescribeRunMock.mock.calls[0]?.[1];
      expect(firstKey).toMatch(/^[A-Za-z0-9_-]{16,128}$/);

      await act(async () => {
        await expect(hook.result.current.submit.mutateAsync([101, 202])).rejects.toBeDefined();
      });
      await act(async () => {
        await hook.result.current.submit.mutateAsync([101, 202]);
      });

      expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(3);
      expect(submitBulkDescribeRunMock.mock.calls.map(([ids]) => ids)).toEqual([
        [101, 202],
        [101, 202],
        [101, 202],
      ]);
      expect(submitBulkDescribeRunMock.mock.calls.map(([, key]) => key)).toEqual([
        firstKey,
        firstKey,
        firstKey,
      ]);
    },
  );

  it('reuses the warmup retry key after an ambiguous response and auth refusal', async () => {
    putDescribeOperationContext({
      version: DESCRIBE_OPERATION_CONTEXT_VERSION,
      kind: DESCRIBE_OPERATION_KIND.RUN,
      id: 'run-source',
      startup_id: null,
      started_at: Date.now(),
      request: { writeAlt: false, force: false },
    });
    fetchDescribeRunItemsMock
      .mockResolvedValueOnce(itemsResponse('run-source', [describeItem(51)]))
      .mockResolvedValueOnce(itemsResponse('run-source', [describeItem(99)]));
    submitBulkDescribeRunMock
      .mockImplementationOnce(async () => {
        throw new Error('Connection lost after submit');
      })
      .mockImplementationOnce(async () => {
        throw new AuthExpiredError({ endpoint: '/acx/v1/describe/runs', status: 401 });
      })
      .mockResolvedValueOnce(runResponse({ run_id: 'run-retried' }));

    const wrapper = createQueryWrapper(queryClient);
    const hook = renderHook(() => useActivityStatus(), { wrapper });
    await waitFor(() =>
      expect(hook.result.current.status.reason).toBe(ACTIVITY_REASON.GPU_WARMUP_TIMEOUT),
    );

    for (let attempt = 1; attempt <= 2; attempt += 1) {
      act(() => hook.result.current.actions.onRetry?.());
      await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(attempt));
      await waitFor(() =>
        expect(
          queryClient
            .getMutationCache()
            .getAll()
            .filter((mutation) => mutation.state.status === 'error'),
        ).toHaveLength(attempt),
      );
    }

    const firstKey = submitBulkDescribeRunMock.mock.calls[0]?.[1];
    expect(submitBulkDescribeRunMock.mock.calls[0]?.[0]).toEqual([51]);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[0]).toEqual([51]);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[1]).toBe(firstKey);

    act(() => hook.result.current.actions.onRetry?.());
    await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(3));
    expect(submitBulkDescribeRunMock.mock.calls[2]?.[0]).toEqual([51]);
    expect(submitBulkDescribeRunMock.mock.calls[2]?.[1]).toBe(firstKey);
    expect(fetchDescribeRunItemsMock).toHaveBeenCalledTimes(1);
  });

  it('retires the bulk submit key after an ambiguous response followed by HTTP 422', async () => {
    submitBulkDescribeRunMock
      .mockImplementationOnce(async () => {
        throw new Error('Connection lost after submit');
      })
      .mockImplementationOnce(async () => {
        throw describeHttpError(422);
      })
      .mockResolvedValueOnce(runResponse({ run_id: 'run-after-refusal' }));

    const wrapper = createQueryWrapper(queryClient);
    const hook = renderHook(() => useBulkDescribe(), { wrapper });
    await act(async () => {
      await expect(hook.result.current.submit.mutateAsync([101, 202])).rejects.toBeDefined();
    });
    const firstKey = submitBulkDescribeRunMock.mock.calls[0]?.[1];
    await act(async () => {
      await expect(hook.result.current.submit.mutateAsync([101, 202])).rejects.toBeDefined();
    });
    await act(async () => {
      await hook.result.current.submit.mutateAsync([101, 202]);
    });

    expect(submitBulkDescribeRunMock.mock.calls[1]?.[1]).toBe(firstKey);
    expect(submitBulkDescribeRunMock.mock.calls[2]?.[1]).not.toBe(firstKey);
  });

  it('reuses warmup retry key and frozen unfinished ids after an ambiguous response and remount', async () => {
    putDescribeOperationContext({
      version: DESCRIBE_OPERATION_CONTEXT_VERSION,
      kind: DESCRIBE_OPERATION_KIND.RUN,
      id: 'run-source',
      startup_id: null,
      started_at: Date.now(),
      request: { writeAlt: false, force: false },
    });
    fetchDescribeRunItemsMock
      .mockResolvedValueOnce(itemsResponse('run-source', [describeItem(51)]))
      .mockResolvedValueOnce(itemsResponse('run-source', [describeItem(99)]));
    submitBulkDescribeRunMock
      .mockImplementationOnce(async () => {
        const stored = sessionStorage.getItem(
          describeOperationPendingSubmitStorageKey(TENANT, {
            kind: 'warmup_recovery',
            sourceRunId: 'run-source',
          }),
        );
        expect(stored).not.toBeNull();
        throw new Error('Connection lost after submit');
      })
      .mockResolvedValueOnce(runResponse({ run_id: 'run-retried' }));
    const wrapper = createQueryWrapper(queryClient);

    const firstMount = renderHook(() => useActivityStatus(), { wrapper });
    await waitFor(() => expect(firstMount.result.current.status.reason).toBe(ACTIVITY_REASON.GPU_WARMUP_TIMEOUT));
    act(() => firstMount.result.current.actions.onRetry?.());
    await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(queryClient.getMutationCache().getAll().some((mutation) => mutation.state.status === 'error')).toBe(true),
    );
    const firstKey = submitBulkDescribeRunMock.mock.calls[0]?.[1];
    expect(submitBulkDescribeRunMock.mock.calls[0]?.[0]).toEqual([51]);
    firstMount.unmount();
    _resetDescribeOperationStoreForTests();

    const secondMount = renderHook(() => useActivityStatus(), { wrapper });
    await waitFor(() => expect(secondMount.result.current.status.reason).toBe(ACTIVITY_REASON.GPU_WARMUP_TIMEOUT));
    act(() => secondMount.result.current.actions.onRetry?.());
    await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(2));

    expect(submitBulkDescribeRunMock.mock.calls[1]?.[0]).toEqual([51]);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[1]).toBe(firstKey);
    expect(fetchDescribeRunItemsMock).toHaveBeenCalledTimes(1);
  });
});
