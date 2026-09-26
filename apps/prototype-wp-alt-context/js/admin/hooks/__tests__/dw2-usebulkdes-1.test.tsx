import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import React, { createElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GPU_STATE, type DescribeRunResponse } from '../../api/describeApi';
import * as gpuApi from '../../api/gpuApi';
import { useBulkDescribe } from '../useBulkDescribe';
import { GpuTierStatus } from '../../pages/workbench/GpuTierStatus';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _position, explicitIndex) => {
      const argumentIndex = explicitIndex ? Number(explicitIndex) - 1 : index++;
      return String(args[argumentIndex] ?? '');
    });
  },
}));

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/describeApi')>();
  return {
    ...actual,
    cancelBulkDescribeRun: vi.fn(),
    submitBulkDescribeRun: vi.fn(),
    fetchBulkDescribeRun: vi.fn(),
  };
});

vi.mock('../../api/gpuApi', async (importOriginal) => {
  const actual = await importOriginal<typeof gpuApi>();
  return { ...actual, fetchGpuStatus: vi.fn() };
});

const describeApi = await import('../../api/describeApi');
const submitBulkDescribeRunMock = vi.mocked(describeApi.submitBulkDescribeRun);
const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);
const fetchGpuStatusMock = vi.mocked(gpuApi.fetchGpuStatus);

const runResponse = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'tenant',
  run_id: 'run-unreadable',
  status: 'pending',
  phase: 'queued',
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

const gpuStatus = (state: string, reason: string | null = null) => ({
  gpu_state: {
    state,
    instance_id: null,
    written_at: 1_700_000_000,
    reason,
    since: null,
    intent: 'auto' as const,
    intent_expires_at: null,
    intent_status: 'none' as const,
    honoured_nonce: null,
    lease_expires_at: null,
    instance_running_since: null,
    last_transition_reason: 'unknown' as const,
  },
  snapshot_age_seconds: 1,
  snapshot_fresh: true,
  intent: null,
  load: { has_work: false, written_at: 1_700_000_001, fresh: true },
  server_time: '2026-09-26T00:00:00Z',
});

const createWrapper = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: React.PropsWithChildren) =>
    createElement(QueryClientProvider, { client }, children);
  return { client, wrapper };
};

const mediaSelectionSource = (): string => {
  const workingDirectory = process.cwd();
  const appRoot = workingDirectory.endsWith('/apps/prototype-wp-alt-context')
    ? workingDirectory
    : resolve(workingDirectory, 'apps/prototype-wp-alt-context');
  return readFileSync(resolve(appRoot, 'js/admin/pages/workbench/MediaSelection.tsx'), 'utf8');
};

const renderGpu = (props: Record<string, unknown>) => {
  const { wrapper } = createWrapper();
  return render(createElement(GpuTierStatus as React.ComponentType<Record<string, unknown>>, props), { wrapper });
};

describe('DEFWAVE-2 workbench deferred findings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    fetchBulkDescribeRunMock.mockResolvedValue(runResponse({ status: 'completed' }));
    fetchGpuStatusMock.mockResolvedValue(gpuStatus('stopped') as Awaited<ReturnType<typeof gpuApi.fetchGpuStatus>>);
  });

  afterEach(async () => {
    cleanup();
    sessionStorage.clear();
  });

  it('exposes submit unreadable media ids to its caller after a successful partial run', async () => {
    submitBulkDescribeRunMock.mockResolvedValue({
      ...runResponse(),
      unreadable_media_ids: [104, 209],
    });
    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useBulkDescribe(), { wrapper });

    result.current.submit.mutate([104, 209, 311]);

    await waitFor(() => expect(result.current.submit.isSuccess).toBe(true));
    expect(result.current).toHaveProperty('unreadableMediaIds', [104, 209]);
  });

  it.each([
    ['warmup ETA', { warmup_eta_seconds: 12, startup_budget_seconds: 90 }, 'about 12s'],
    ['startup budget', { startup_budget_seconds: 90 }, 'up to 90s'],
  ])('uses the %s from the failed describe operation in the idle warming chip', async (_label, waitDetail, waitCopy) => {
    fetchGpuStatusMock.mockResolvedValue(
      gpuStatus('warming') as Awaited<ReturnType<typeof gpuApi.fetchGpuStatus>>,
    );
    const operationError = new Error(
      `Request failed (503): ${JSON.stringify({ detail: waitDetail })}`,
    );
    renderGpu({ operationError });

    expect(await screen.findByRole('status')).toHaveTextContent(
      `Description Service is starting… ${waitCopy}`,
    );
  });

  it.each([
    ['degraded', 'readiness_timeout', 'Description Service startup timed out.'],
    ['unknown', 'readiness_stall', 'Description Service startup is taking longer than expected.'],
  ])('maps the idle %s lifecycle reason to safe operator copy', async (state, reason, copy) => {
    fetchGpuStatusMock.mockResolvedValue(
      gpuStatus(state, reason) as Awaited<ReturnType<typeof gpuApi.fetchGpuStatus>>,
    );
    renderGpu({});

    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent(copy);
    expect(status.textContent).not.toContain(reason);
  });

  it('mounts the GPU status in MediaSelection and wires submit wait metadata and pending state', () => {
    const source = mediaSelectionSource();

    expect(source.includes("import { GpuTierStatus } from './GpuTierStatus';")).toBe(true);
    expect(source.includes('<GpuTierStatus')).toBe(true);
    expect(source.includes('isRunPending={isGpuServiceStatusPending}')).toBe(true);
    expect(source.includes('useMutationState')).toBe(true);
    expect(source.includes('operationError={gpuOperationError}')).toBe(true);
    expect(source.includes('unreadableMediaIds')).toBe(true);
  });

  it('wires unreadable media ids to a recovery notice', () => {
    const source = mediaSelectionSource();

    expect(source.includes('bulkDescribe.unreadableMediaIds')).toBe(true);
    expect(source.includes('unreadableMediaIds.map((mediaId)')).toBe(true);
    expect(source.toLowerCase().includes('re-upload')).toBe(true);
  });
});
