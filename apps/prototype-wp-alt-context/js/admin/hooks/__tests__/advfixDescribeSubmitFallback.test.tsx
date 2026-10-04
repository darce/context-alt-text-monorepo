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
import {
  _resetDescribeOperationStoreForTests,
  DESCRIBE_OPERATION_CONTEXT_VERSION,
  DESCRIBE_OPERATION_KIND,
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

const TENANT = 'tenant-fallback';
const submitBulkDescribeRunMock = vi.mocked(describeApi.submitBulkDescribeRun);
const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);
const fetchDescribeRunItemsMock = vi.mocked(describeApi.fetchDescribeRunItems);
const fetchGpuStatusMock = vi.mocked(gpuApi.fetchGpuStatus);

const runResponse = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: TENANT,
  run_id: 'run-fallback',
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

const installConfig = (tenantId: string | null): void => {
  resetConfigCache();
  registerConfig({
    nonce: 'test-nonce',
    ajaxUrl: '/wp-admin/admin-ajax.php',
    endpoints: {},
    ...(tenantId === null ? {} : { tenant_id: tenantId }),
  });
};

describe('describe submit hook-local fallback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    installConfig(TENANT);
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
    vi.restoreAllMocks();
    sessionStorage.clear();
    _resetDescribeOperationStoreForTests();
    resetConfigCache();
  });

  it('submits a bulk action with an idempotency key when no tenant is configured', async () => {
    installConfig(null);
    const { result } = renderHook(() => useBulkDescribe(), {
      wrapper: createQueryWrapper(queryClient),
    });

    act(() => result.current.submit.mutate([104, 209]));

    await waitFor(() => expect(result.current.submit.isSuccess).toBe(true));
    expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(1);
    expect(submitBulkDescribeRunMock).toHaveBeenCalledWith(
      [104, 209],
      expect.stringMatching(/^[A-Za-z0-9_-]{16,128}$/),
    );
  });

  it('reuses its hook-local key and frozen media ids when storage writes fail', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('sessionStorage is unavailable');
    });
    submitBulkDescribeRunMock
      .mockRejectedValueOnce(new Error('Connection lost after submit'))
      .mockResolvedValueOnce(runResponse({ run_id: 'run-retried' }));
    const { result } = renderHook(() => useBulkDescribe(), {
      wrapper: createQueryWrapper(queryClient),
    });

    act(() => result.current.submit.mutate([202, 101]));
    await waitFor(() => expect(result.current.submit.isError).toBe(true));
    const firstKey = submitBulkDescribeRunMock.mock.calls[0]?.[1];
    expect(firstKey).toMatch(/^[A-Za-z0-9_-]{16,128}$/);

    act(() => result.current.submit.mutate([101, 202]));
    await waitFor(() => expect(result.current.submit.isSuccess).toBe(true));

    expect(setItem).toHaveBeenCalled();
    expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(2);
    expect(submitBulkDescribeRunMock.mock.calls[0]?.[0]).toEqual([101, 202]);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[0]).toEqual([101, 202]);
    expect(submitBulkDescribeRunMock.mock.calls[1]?.[1]).toBe(firstKey);
  });

  it('submits the unfinished warmup retry ids when no tenant is configured', async () => {
    installConfig(null);
    putDescribeOperationContext({
      version: DESCRIBE_OPERATION_CONTEXT_VERSION,
      kind: DESCRIBE_OPERATION_KIND.RUN,
      id: 'run-source',
      startup_id: null,
      started_at: Date.now(),
      request: { writeAlt: false, force: false },
    });
    fetchDescribeRunItemsMock.mockResolvedValue(
      itemsResponse('run-source', [describeItem(51), describeItem(52, 'completed')]),
    );
    const { result } = renderHook(() => useActivityStatus(), {
      wrapper: createQueryWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.status.reason).toBe(ACTIVITY_REASON.GPU_WARMUP_TIMEOUT));
    act(() => result.current.actions.onRetry?.());

    await waitFor(() => expect(submitBulkDescribeRunMock).toHaveBeenCalledTimes(1));
    expect(submitBulkDescribeRunMock).toHaveBeenCalledWith(
      [51],
      expect.stringMatching(/^[A-Za-z0-9_-]{16,128}$/),
    );
  });
});
