/**
 * UXP-2 slice 2: shared recognition cooldown gates exactly six pollers —
 * useScanStatus, useMultiScanStatus, useBatchRunStatus, useDescribeRunProgress,
 * useMediaIdentities, useRecognitionClusters — and nothing else (useSyncHealth
 * keeps its cadence). Suspend on arm, resume at expiry without remount, no
 * timer leak on unmount.
 */
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../api/recognition';
import * as describeApi from '../../api/describeApi';
import { HTTPError } from '../../utils/http';
import { _resetCooldownForTests, openCooldown, openCooldownFromError } from '../../utils/recognitionCooldown';
import { useBatchRunStatus, useMultiScanStatus, useRecognitionClusters, useScanStatus } from '../useRecognitionHooks';
import { useDescribeRunProgress } from '../useDescribeRunProgress';
import { useMediaIdentities } from '../useMediaIdentities';
import { useExportJobStatus } from '../useRetentionStatus';
import { useRecognitionCooldown } from '../useRecognitionCooldown';
import { useSyncHealth } from '../useSyncHealth';

vi.mock('../../api/recognition', async () => {
  const actual = await vi.importActual<typeof recognitionApi>('../../api/recognition');
  return {
    ...actual,
    fetchScanStatus: vi.fn(),
    fetchBatchRunStatus: vi.fn(),
    listRecognitionClusters: vi.fn(),
    fetchMediaIdentities: vi.fn(),
    fetchSyncHealth: vi.fn(),
    getExportJobStatus: vi.fn(),
  };
});

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return { ...actual, fetchBulkDescribeRun: vi.fn() };
});

const fetchScanStatusMock = vi.mocked(recognitionApi.fetchScanStatus);
const fetchBatchRunStatusMock = vi.mocked(recognitionApi.fetchBatchRunStatus);
const listRecognitionClustersMock = vi.mocked(recognitionApi.listRecognitionClusters);
const fetchMediaIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);
const fetchSyncHealthMock = vi.mocked(recognitionApi.fetchSyncHealth);
const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);
const getExportJobStatusMock = vi.mocked(recognitionApi.getExportJobStatus);

/** All six gated pollers plus the deliberately ungated sync-health poller. */
const useAllPollers = () => {
  useScanStatus('job-1');
  useMultiScanStatus(['job-2', 'job-3']);
  useBatchRunStatus('run-1');
  useDescribeRunProgress('run-9');
  useMediaIdentities([7]);
  useRecognitionClusters();
  useSyncHealth();
};

const gatedCallCounts = () => ({
  scan: fetchScanStatusMock.mock.calls.length,
  batch: fetchBatchRunStatusMock.mock.calls.length,
  clusters: listRecognitionClustersMock.mock.calls.length,
  media: fetchMediaIdentitiesMock.mock.calls.length,
  describe: fetchBulkDescribeRunMock.mock.calls.length,
});

const createWrapper = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return ({ children }: React.PropsWithChildren): React.JSX.Element => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

describe('recognition cooldown gate over the six pollers', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T12:00:00.000Z'));
    _resetCooldownForTests();
    vi.clearAllMocks();

    fetchScanStatusMock.mockResolvedValue({ status: 'running' } as recognitionApi.JobStatusResponse);
    fetchBatchRunStatusMock.mockResolvedValue({ terminal_state: false } as recognitionApi.BatchRunStatus);
    listRecognitionClustersMock.mockResolvedValue({ clusters: [] } as unknown as recognitionApi.ClusterListResponse);
    fetchMediaIdentitiesMock.mockResolvedValue({
      identities_by_media: { 7: [{ clustering_pending: true }] },
    } as unknown as recognitionApi.MediaIdentitiesResponse);
    fetchSyncHealthMock.mockResolvedValue({
      breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
      outbox: { pending: 0, failed: 0 },
      conflicts: { open: 0 },
      replays: { failed: null, source: 'unavailable_local' },
      last_pull: { at: null, ok: true },
      warnings: [],
    } as unknown as Awaited<ReturnType<typeof recognitionApi.fetchSyncHealth>>);
    fetchBulkDescribeRunMock.mockResolvedValue({
      tenant_id: 'tenant',
      run_id: 'run-9',
      status: 'running',
      phase: 'describing',
      completed: 1,
      failed: 0,
      skipped: 0,
      total: 4,
      cancel_requested: false,
      eta_seconds: null,
      gpu_state: null,
      // The describe poller is in the recognition-cooldown cohort precisely
      // because the run does identity fusion; a recognition-off run would not
      // share that backpressure. recognition-on is load-bearing here.
      recognition_enabled: true,
    });
  });

  afterEach(() => {
    _resetCooldownForTests();
    vi.useRealTimers();
  });

  it('suspends all six gated pollers for the whole window, then resumes at expiry without remount; sync health cadence untouched', async () => {
    openCooldown(30);

    renderHook(() => useAllPollers(), { wrapper: createWrapper() });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Mount fetch happens once per query (the cooldown gates intervals, not mount).
    const afterMount = gatedCallCounts();
    expect(afterMount).toEqual({ scan: 3, batch: 1, clusters: 1, media: 1, describe: 1 });
    expect(fetchSyncHealthMock).toHaveBeenCalledTimes(1);

    // t=29s: still cooling — zero gated poll fires across the whole window.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(29_000);
    });
    expect(gatedCallCounts()).toEqual(afterMount);
    // Ungated: sync health kept its 15s cadence (fires at 15s).
    expect(fetchSyncHealthMock).toHaveBeenCalledTimes(2);

    // Cross expiry (+5s): every fast poller has completed at least one full
    // own-base cycle again — same mount, no remount. (A poller's expiry tick
    // can be displaced by up to one base cycle when cross-query re-renders
    // reset a changed interval, so the window allows base + slack.)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000);
    });
    const afterExpiry = gatedCallCounts();
    expect(afterExpiry.scan).toBeGreaterThanOrEqual(afterMount.scan + 3);
    expect(afterExpiry.batch).toBeGreaterThanOrEqual(afterMount.batch + 1);
    expect(afterExpiry.media).toBeGreaterThanOrEqual(afterMount.media + 1);
    expect(afterExpiry.describe).toBeGreaterThanOrEqual(afterMount.describe + 1);

    // The 30s clusters poller resumes within one full base cycle past expiry,
    // and the fast pollers keep their native cadence.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_100);
    });
    const resumed = gatedCallCounts();
    expect(resumed.scan).toBeGreaterThan(afterExpiry.scan);
    expect(resumed.batch).toBeGreaterThan(afterExpiry.batch);
    expect(resumed.media).toBeGreaterThan(afterExpiry.media);
    expect(resumed.describe).toBeGreaterThan(afterExpiry.describe);
    expect(resumed.clusters).toBeGreaterThan(afterMount.clusters);
  });

  it('one 429 mid-flight quiets live pollers after at most one already-scheduled tick each', async () => {
    renderHook(() => useAllPollers(), { wrapper: createWrapper() });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_600);
    });
    // Pollers are live (scan-family fired its 1.5s tick).
    expect(fetchScanStatusMock.mock.calls.length).toBe(6);

    // The server says "ask again later" once.
    openCooldownFromError(
      new HTTPError({
        status: 429,
        retryAfterSeconds: 10,
        endpoint: '/acx/v1/recognition/jobs/job-1',
        bodyPreview: '',
        message: 'failed (429)',
      }),
    );

    // Already-scheduled interval ticks may fire once more; after they drain,
    // the window is quiet until expiry (t_arm=1.6s, expiry=11.6s).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_400); // t=5s
    });
    const quiesced = gatedCallCounts();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000); // t=11s, still inside the window
    });
    expect(gatedCallCounts()).toEqual(quiesced);

    // Ungated: sync health fired its 15s tick regardless of the window? Not yet at t=11s.
    expect(fetchSyncHealthMock).toHaveBeenCalledTimes(1);

    // Past expiry the gated pollers resume.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000); // t=16s
    });
    expect(gatedCallCounts().scan).toBeGreaterThan(quiesced.scan);
    expect(fetchSyncHealthMock).toHaveBeenCalledTimes(2);
  });

  it('leaves no timers behind on unmount, even mid-cooldown', async () => {
    const { unmount } = renderHook(() => useAllPollers(), { wrapper: createWrapper() });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_600);
    });
    openCooldown(30);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });

    unmount();
    const countsAtUnmount = gatedCallCounts();
    const syncCallsAtUnmount = fetchSyncHealthMock.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(gatedCallCounts()).toEqual(countsAtUnmount);
    expect(fetchSyncHealthMock).toHaveBeenCalledTimes(syncCallsAtUnmount);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('useRecognitionCooldown observable state', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T12:00:00.000Z'));
    _resetCooldownForTests();
  });

  afterEach(() => {
    _resetCooldownForTests();
    vi.useRealTimers();
  });

  it('reports the live window and counts remaining seconds down to idle', async () => {
    const { result } = renderHook(() => useRecognitionCooldown());
    expect(result.current).toEqual({ isCoolingDown: false, remainingSeconds: 0 });

    act(() => {
      openCooldown(3);
    });
    expect(result.current).toEqual({ isCoolingDown: true, remainingSeconds: 3 });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(result.current).toEqual({ isCoolingDown: true, remainingSeconds: 2 });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(result.current).toEqual({ isCoolingDown: false, remainingSeconds: 0 });
  });

  it('clears its ticker on unmount', () => {
    const { unmount } = renderHook(() => useRecognitionCooldown());
    act(() => {
      openCooldown(30);
    });
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe('recognition cooldown gate over the export-job-status poller (7th)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T12:00:00.000Z'));
    _resetCooldownForTests();
    vi.clearAllMocks();
    getExportJobStatusMock.mockResolvedValue({
      job_id: 'job-1',
      status: 'processing',
    });
  });

  afterEach(() => {
    _resetCooldownForTests();
    vi.useRealTimers();
  });

  it('suspends the 2s export-status poll for the whole window, then resumes at expiry', async () => {
    openCooldown(30);

    renderHook(() => useExportJobStatus('job-1'), { wrapper: createWrapper() });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Mount fetch happens once; the cooldown gates the interval, not the mount.
    expect(getExportJobStatusMock).toHaveBeenCalledTimes(1);

    // Across the whole window the 2s poll never fires again.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(29_000);
    });
    expect(getExportJobStatusMock).toHaveBeenCalledTimes(1);

    // Past expiry the poll resumes on its own 2s cadence without a remount.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000);
    });
    expect(getExportJobStatusMock.mock.calls.length).toBeGreaterThan(1);
  });
});
