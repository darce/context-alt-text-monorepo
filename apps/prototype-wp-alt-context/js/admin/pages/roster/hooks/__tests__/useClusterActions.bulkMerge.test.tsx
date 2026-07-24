import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../../../api/recognition';
import { BULK_MERGE_STEP_TIMEOUT_MS, useClusterActions } from '../useClusterActions';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('../../../../api/recognition', () => ({
  dismissCluster: vi.fn(),
  mergeCluster: vi.fn(),
  reassignClusterIdentity: vi.fn(),
  scanFacesBatched: vi.fn(),
}));

vi.mock('../../../../api/rosterApi', () => ({
  commitClusterToRosterEntry: vi.fn(),
}));

vi.mock('../../../../context/ToastContext', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

vi.mock('../../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

const mergeOk = {
  source_id: 'c-2',
  source_label: null,
  target_id: 'c-1',
  target_label: 'Target',
  identities_moved: 1,
  moved_identity_ids: ['id-1'],
  target_identity_count: 2,
};

const createWrapper = () => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

describe('useClusterActions bulk merge announce + failure (E21-9 Slice 4)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('announces per-step progress via bulkMergeProgress (role=status data)', async () => {
    const hold = new Map<string, { resolve: (v: typeof mergeOk) => void }>();

    vi.mocked(recognitionApi.mergeCluster).mockImplementation(
      (sourceId) =>
        new Promise<typeof mergeOk>((resolve) => {
          hold.set(sourceId, { resolve: (v) => resolve({ ...v, source_id: sourceId }) });
        }),
    );

    const { result } = renderHook(() => useClusterActions(), { wrapper: createWrapper() });

    result.current.bulkMergeMutation.mutate({ clusterIds: ['c-1', 'c-2', 'c-3'] });

    await waitFor(() => {
      expect(hold.has('c-2')).toBe(true);
    });

    await waitFor(() => {
      expect(result.current.bulkMergeProgress).toEqual({ current: 1, total: 2 });
    });

    await act(async () => {
      hold.get('c-2')?.resolve(mergeOk);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(hold.has('c-3')).toBe(true);
      expect(result.current.bulkMergeProgress).toEqual({ current: 2, total: 2 });
    });

    await act(async () => {
      hold.get('c-3')?.resolve(mergeOk);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.bulkMergeMutation.isSuccess).toBe(true);
    });
    expect(result.current.bulkMergeProgress).toBeNull();
  });

  it('stops on first failure, names failed cluster, keeps remainder selected (no onBulkMergeSettled)', async () => {
    const onBulkMergeSettled = vi.fn();
    const onBulkMergeFailure = vi.fn();

    vi.mocked(recognitionApi.mergeCluster).mockImplementation((sourceId) => {
      if (sourceId === 'c-2') {
        return Promise.reject(new Error('merge boom'));
      }
      return Promise.resolve({ ...mergeOk, source_id: sourceId });
    });

    const { result } = renderHook(
      () => useClusterActions({ onBulkMergeSettled, onBulkMergeFailure }),
      { wrapper: createWrapper() },
    );

    act(() => {
      result.current.bulkMergeMutation.mutate({ clusterIds: ['c-1', 'c-2', 'c-3'] });
    });

    await waitFor(() => {
      expect(result.current.bulkMergeFailure).not.toBeNull();
    });

    expect(result.current.bulkMergeFailure?.failedClusterId).toBe('c-2');
    expect(result.current.bulkMergeFailure?.message).toMatch(/c-2|cluster/i);
    expect(result.current.bulkMergeFailure?.remainingClusterIds).toEqual(['c-1', 'c-2', 'c-3']);
    expect(onBulkMergeFailure).toHaveBeenCalledWith(['c-1', 'c-2', 'c-3']);
    expect(onBulkMergeSettled).not.toHaveBeenCalled();
    expect(recognitionApi.mergeCluster).toHaveBeenCalledTimes(1);
    expect(recognitionApi.mergeCluster).toHaveBeenCalledWith('c-2', 'c-1', undefined, expect.any(AbortSignal));
  });

  it('sequential-order discrimination: next merge starts only after prior settles (fails under parallel fan-out)', async () => {
    const events: string[] = [];
    const resolvers: (() => void)[] = [];

    vi.mocked(recognitionApi.mergeCluster).mockImplementation(
      (sourceId) =>
        new Promise((resolve) => {
          events.push(`start:${sourceId}`);
          resolvers.push(() => {
            events.push(`end:${sourceId}`);
            resolve({ ...mergeOk, source_id: sourceId });
          });
        }),
    );

    const { result } = renderHook(() => useClusterActions(), { wrapper: createWrapper() });

    act(() => {
      result.current.bulkMergeMutation.mutate({ clusterIds: ['target', 's1', 's2'] });
    });

    await waitFor(() => {
      expect(events).toEqual(['start:s1']);
    });

    // Resolve out of "desired" visual order: only s1 is in flight; s2 must not start yet.
    await act(async () => {
      resolvers[0]?.();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(events).toEqual(['start:s1', 'end:s1', 'start:s2']);
    });

    await act(async () => {
      resolvers[1]?.();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.bulkMergeMutation.isSuccess).toBe(true);
    });
    expect(events).toEqual(['start:s1', 'end:s1', 'start:s2', 'end:s2']);
  });

  it('stall-timeout: never-resolving merge aborts at 30s and lands in failure state', async () => {
    vi.useFakeTimers();
    const onBulkMergeFailure = vi.fn();

    vi.mocked(recognitionApi.mergeCluster).mockImplementation(
      (_sourceId, _targetId, _label, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            const err = new DOMException('The operation was aborted.', 'AbortError');
            reject(err);
          });
        }),
    );

    const { result } = renderHook(() => useClusterActions({ onBulkMergeFailure }), { wrapper: createWrapper() });

    act(() => {
      result.current.bulkMergeMutation.mutate({ clusterIds: ['c-1', 'c-hang'] });
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(BULK_MERGE_STEP_TIMEOUT_MS);
    });

    await waitFor(() => {
      expect(result.current.bulkMergeFailure).not.toBeNull();
    });

    expect(result.current.bulkMergeFailure?.failedClusterId).toBe('c-hang');
    expect(result.current.bulkMergeFailure?.message).toMatch(/timed out/i);
    expect(onBulkMergeFailure).toHaveBeenCalledWith(['c-1', 'c-hang']);
  });

  it('calls onBulkMergeSettled only after full success', async () => {
    const onBulkMergeSettled = vi.fn();
    vi.mocked(recognitionApi.mergeCluster).mockResolvedValue(mergeOk);

    const { result } = renderHook(() => useClusterActions({ onBulkMergeSettled }), { wrapper: createWrapper() });

    act(() => {
      result.current.bulkMergeMutation.mutate({ clusterIds: ['c-1', 'c-2'] });
    });

    await waitFor(() => {
      expect(onBulkMergeSettled).toHaveBeenCalledTimes(1);
    });
    expect(result.current.bulkMergeFailure).toBeNull();
  });
});
