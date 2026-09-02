import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BatchAnalyzeResponse } from '../../api/recognition/types/scan';
import { HTTPError } from '../../utils/http';
import { setLogLevel, setLogSink, type LogRecord } from '../../utils/logger';
import { useCancelScanJobs, useClusterIdentities, useScanIdentities } from '../useRecognitionHooks';
import { useJobStateMachineMutations } from '../useJobStateMachineMutations';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../useRecognitionHooks', () => ({
  useScanIdentities: vi.fn(),
  useClusterIdentities: vi.fn(),
  useCancelScanJobs: vi.fn(),
}));

const useScanIdentitiesMock = vi.mocked(useScanIdentities);
const useClusterIdentitiesMock = vi.mocked(useClusterIdentities);
const useCancelScanJobsMock = vi.mocked(useCancelScanJobs);

type ScanOptions = NonNullable<Parameters<typeof useScanIdentities>[0]>;
type CancelOptions = NonNullable<Parameters<typeof useCancelScanJobs>[0]>;

let scanOptions: ScanOptions | undefined;
let cancelOptions: CancelOptions | undefined;

const leakingScanError = (): HTTPError =>
  new HTTPError({
    status: 500,
    retryAfterSeconds: undefined,
    endpoint: 'https://example.test/wp-json/acx/v1/recognition/analyze?token=secret-token',
    bodyPreview: 'raw-response-body-secret',
    message: 'Request failed (500): raw-response-body-secret',
  });

const scanResponse = (jobIds: string[], total = 10): BatchAnalyzeResponse => ({
  batchRunId: 'run-1',
  jobs: jobIds.map((id) => ({
    id,
    type: 'analyze',
    status: 'pending',
    progress: { completed: 0, total },
    started_at: '2026-01-01T00:00:00Z',
    finished_at: null,
  })),
});

const mockMutationContext = {} as never;

const captureRecords = (): LogRecord[] => {
  const records: LogRecord[] = [];
  setLogSink((record) => {
    records.push(record);
  });
  return records;
};

const renderMutations = (activeJobIds: string[] = []) => {
  const addJob = vi.fn();
  const removeJob = vi.fn();
  const setIsWaitingForScanCompletion = vi.fn();
  const setIsCancellingScan = vi.fn();
  const setActiveBatchRunId = vi.fn();
  const invalidateIdentities = vi.fn();
  const onScanComplete = vi.fn();
  const onScanError = vi.fn();
  const onCancelComplete = vi.fn();

  const rendered = renderHook(() =>
    useJobStateMachineMutations({
      activeJobIds,
      addJob,
      removeJob,
      setIsWaitingForScanCompletion,
      setIsCancellingScan,
      setActiveBatchRunId,
      invalidateIdentities,
      onScanComplete,
      onScanError,
      onCancelComplete,
    }),
  );

  return {
    ...rendered,
    addJob,
    onScanComplete,
    onScanError,
    onCancelComplete,
  };
};

describe('useJobStateMachineMutations logging [O-02][O-06]', () => {
  beforeEach(() => {
    scanOptions = undefined;
    cancelOptions = undefined;
    setLogLevel('debug');
    useScanIdentitiesMock.mockImplementation((options) => {
      scanOptions = options;
      return { mutate: vi.fn(), isPending: false } as unknown as ReturnType<typeof useScanIdentities>;
    });
    useClusterIdentitiesMock.mockReturnValue({ mutate: vi.fn(), isPending: false } as unknown as ReturnType<
      typeof useClusterIdentities
    >);
    useCancelScanJobsMock.mockImplementation((options) => {
      cancelOptions = options;
      return { mutate: vi.fn(), isPending: false } as unknown as ReturnType<typeof useCancelScanJobs>;
    });
  });

  afterEach(() => {
    setLogSink(null);
    setLogLevel(null);
    vi.clearAllMocks();
  });

  it('emits exactly one scan.submit wide event on success settle [O-02]', () => {
    const records = captureRecords();
    const { addJob, onScanComplete } = renderMutations();

    scanOptions?.onSuccess?.(scanResponse(['job-1', 'job-2'], 4), [1, 2], undefined, mockMutationContext);

    const jobEvents = records.filter((record) => record.fields.event === 'scan.submit');
    expect(jobEvents).toHaveLength(1);
    expect(jobEvents[0].level).toBe('info');
    expect(jobEvents[0].fields).toEqual(
      expect.objectContaining({
        event: 'scan.submit',
        status: 'pending',
        jobId: 'job-1',
        done: 0,
        total: 8,
        failedCount: 0,
      }),
    );
    expect(typeof jobEvents[0].fields.requestId).toBe('string');
    expect(String(jobEvents[0].fields.requestId).length).toBeGreaterThan(0);
    expect(addJob).toHaveBeenCalledTimes(2);
    expect(onScanComplete).toHaveBeenCalledWith(['job-1', 'job-2']);
  });

  it('mints a distinct requestId per scan submit unit [FEBT1-W2B-01]', () => {
    const records = captureRecords();
    renderMutations();

    scanOptions?.onSuccess?.(scanResponse(['job-1'], 4), [1], undefined, mockMutationContext);
    scanOptions?.onSuccess?.(scanResponse(['job-2'], 4), [2], undefined, mockMutationContext);

    const jobEvents = records.filter((record) => record.fields.event === 'scan.submit');
    expect(jobEvents).toHaveLength(2);
    expect(typeof jobEvents[0].fields.requestId).toBe('string');
    expect(typeof jobEvents[1].fields.requestId).toBe('string');
    expect(jobEvents[0].fields.requestId).not.toBe(jobEvents[1].fields.requestId);
  });

  it('scan failure records inside one unit share requestId [FEBT1-W2B-01]', () => {
    const records = captureRecords();
    renderMutations();

    scanOptions?.onError?.(leakingScanError(), [1], undefined, mockMutationContext);

    const errorRecords = records.filter((record) => record.level === 'error');
    const jobEvents = records.filter((record) => record.fields.event === 'scan.submit');
    expect(errorRecords).toHaveLength(1);
    expect(jobEvents).toHaveLength(1);
    expect(errorRecords[0].fields.requestId).toBe(jobEvents[0].fields.requestId);
    expect(typeof errorRecords[0].fields.requestId).toBe('string');
  });

  it('emits one scan.submit event plus classified error fields on failure [O-02][O-06][O-03]', () => {
    const records = captureRecords();
    const error = leakingScanError();
    const { onScanError } = renderMutations();

    scanOptions?.onError?.(error, [1], undefined, mockMutationContext);

    const jobEvents = records.filter((record) => record.fields.event === 'scan.submit');
    expect(jobEvents).toHaveLength(1);
    expect(jobEvents[0].fields).toEqual(
      expect.objectContaining({
        event: 'scan.submit',
        status: 'failed',
        failedCount: 1,
      }),
    );

    const errorRecords = records.filter((record) => record.level === 'error');
    expect(errorRecords).toHaveLength(1);
    expect(errorRecords[0].message).toBe('Scan submission failed');
    expect(errorRecords[0].fields).toEqual(
      expect.objectContaining({
        tag: 'http',
        status: 500,
        endpoint: '/wp-json/acx/v1/recognition/analyze',
      }),
    );
    const serialized = JSON.stringify(records);
    expect(serialized).not.toContain('raw-response-body-secret');
    expect(serialized).not.toContain('secret-token');
    expect(serialized).not.toContain(error.bodyPreview);
    expect(onScanError).toHaveBeenCalled();
  });

  it('emits exactly one scan.cancel wide event on success settle [O-02]', () => {
    const records = captureRecords();
    const { onCancelComplete } = renderMutations(['job-9']);

    cancelOptions?.onSuccess?.([], ['job-9'], undefined, mockMutationContext);

    const jobEvents = records.filter((record) => record.fields.event === 'scan.cancel');
    expect(jobEvents).toHaveLength(1);
    expect(jobEvents[0].fields).toEqual(
      expect.objectContaining({
        event: 'scan.cancel',
        status: 'cancelled',
        jobId: 'job-9',
      }),
    );
    expect(onCancelComplete).toHaveBeenCalledTimes(1);
  });

  it('emits one scan.cancel event plus classified error fields on failure [O-02][O-06]', () => {
    const records = captureRecords();
    const error = leakingScanError();
    renderMutations(['job-9']);

    cancelOptions?.onError?.(error, ['job-9'], undefined, mockMutationContext);

    const jobEvents = records.filter((record) => record.fields.event === 'scan.cancel');
    expect(jobEvents).toHaveLength(1);
    expect(jobEvents[0].fields).toEqual(
      expect.objectContaining({
        event: 'scan.cancel',
        status: 'failed',
        jobId: 'job-9',
        failedCount: 1,
      }),
    );
    const errorRecords = records.filter((record) => record.level === 'error');
    expect(errorRecords).toHaveLength(1);
    expect(errorRecords[0].message).toBe('Cancel failed');
    expect(errorRecords[0].fields).toEqual(
      expect.objectContaining({
        tag: 'http',
        status: 500,
        endpoint: '/wp-json/acx/v1/recognition/analyze',
      }),
    );
    expect(JSON.stringify(records)).not.toContain('raw-response-body-secret');
  });
});
