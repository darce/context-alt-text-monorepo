import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fetchBatchRunStatus,
  fetchScanStatus,
  type BatchRunStatus,
  type JobStatusResponse,
} from '../../api/recognition';
import { buildTestQueryClient, createQueryWrapper } from '../../test-utils/queryClient';
import { _resetCooldownForTests } from '../../utils/recognitionCooldown';
import { useCombinedScanStatus } from '../useRecognitionHooks';

vi.mock('../../api/recognition', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/recognition')>()),
  fetchBatchRunStatus: vi.fn(),
  fetchScanStatus: vi.fn(),
}));

describe('combined scan status request budget', () => {
  const clients: ReturnType<typeof buildTestQueryClient>[] = [];
  const wrapper = () => {
    const client = buildTestQueryClient();
    client.setDefaultOptions({ queries: { retry: false, gcTime: Infinity } });
    clients.push(client);
    return createQueryWrapper(client);
  };
  const tick = (ms: number) =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });

  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    _resetCooldownForTests();
    vi.mocked(fetchScanStatus).mockImplementation((id) =>
      Promise.resolve({ id, status: 'running', type: 'clustering' } as JobStatusResponse),
    );
    vi.mocked(fetchBatchRunStatus).mockResolvedValue({ terminal_state: false } as BatchRunStatus);
  });
  afterEach(() => {
    clients.forEach((client) => client.clear());
    clients.length = 0;
    _resetCooldownForTests();
    vi.useRealTimers();
  });

  it('tracks a primary job and aggregate with bounded requests regardless of batch size', async () => {
    const ids = Array.from({ length: 100 }, (_, i) => `job-${i}`);
    const { result } = renderHook(() => useCombinedScanStatus(null, ids, 'batch-1'), { wrapper: wrapper() });
    await tick(0);

    expect(fetchScanStatus).toHaveBeenCalledTimes(1);
    expect(fetchScanStatus).toHaveBeenCalledWith('job-99');
    expect(result.current.scanStatusQuery.data?.type).toBe('clustering');
    await tick(60_000);
    expect(
      vi.mocked(fetchScanStatus).mock.calls.length + vi.mocked(fetchBatchRunStatus).mock.calls.length,
    ).toBeLessThanOrEqual(26);
  });

  it('keeps the batch child selected through projection after local scan jobs are removed', async () => {
    vi.mocked(fetchBatchRunStatus).mockResolvedValue({
      terminal_state: true,
      child_job_ids: ['job-1'],
    } as BatchRunStatus);
    vi.mocked(fetchScanStatus).mockResolvedValue({
      id: 'job-1',
      type: 'clustering',
      status: 'completed',
      progress: { phase: 'awaiting_projection' },
    } as JobStatusResponse);
    const { result, rerender } = renderHook(({ ids }) => useCombinedScanStatus(null, ids, 'batch-1'), {
      wrapper: wrapper(),
      initialProps: { ids: ['job-1'] },
    });
    await tick(0);
    rerender({ ids: [] });
    await tick(0);
    expect(result.current.scanStatusQuery.data?.id).toBe('job-1');
    const before = vi.mocked(fetchScanStatus).mock.calls.length;
    await tick(5_100);
    expect(vi.mocked(fetchScanStatus).mock.calls.length).toBeGreaterThan(before);

    vi.mocked(fetchScanStatus).mockResolvedValue({
      id: 'job-1',
      type: 'clustering',
      status: 'completed',
      progress: { phase: 'complete' },
    } as JobStatusResponse);
    await tick(5_100);
    const terminal = vi.mocked(fetchScanStatus).mock.calls.length;
    await tick(30_000);
    expect(fetchScanStatus).toHaveBeenCalledTimes(terminal);
    expect(fetchBatchRunStatus).toHaveBeenCalledTimes(1);
  });

  it('keeps child status tracking for restored jobs without a batch run', async () => {
    renderHook(() => useCombinedScanStatus(null, ['legacy-1', 'legacy-2'], null), { wrapper: wrapper() });
    await tick(0);
    expect(fetchScanStatus).toHaveBeenCalledWith('legacy-1');
    expect(fetchScanStatus).toHaveBeenCalledWith('legacy-2');
    expect(fetchBatchRunStatus).not.toHaveBeenCalled();
  });
});
