import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BatchAnalyzeResponse } from '../../api/recognition/types/scan';
import { HTTPError } from '../../utils/http';
import { REDACTED_SEGMENT, setLogLevel, setLogSink, type LogRecord } from '../../utils/logger';
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

/**
 * The TanStack v5 mutation-callback context, derived from the real callback signature
 * instead of `{} as never` (FEBT1-W2C-04). If the arity or the context type changes, the
 * call sites below stop compiling — which is the whole point of pinning them here.
 */
type ScanMutationContext = Parameters<NonNullable<ScanOptions['onSuccess']>>[3];
type CancelMutationContext = Parameters<NonNullable<CancelOptions['onSuccess']>>[3];

/**
 * The hooks return the full TanStack UseMutationResult (~20 members); these tests only
 * drive the callbacks. The narrowing lives in this one audited helper instead of being
 * repeated as inline `as unknown as ...` at every call site
 * (effective-typescript Item 9 / Item 42, FEBT1-W2C-04). The input shape is declared, so a
 * stub that stops providing `mutate`/`isPending` fails to compile.
 */
interface MutationResultStub {
  mutate: () => void;
  isPending: boolean;
}

const asMutationResult = <TResult>(stub: MutationResultStub): TResult => stub as unknown as TResult;

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

/**
 * A leaking endpoint whose path carries a real job id, not just route literals. The old
 * private redactor in useJobStateMachineMutations returned `url.pathname` verbatim, so this
 * id reached the sink; the shared `redactEndpoint` fails closed per segment (FEBT-1-W1-O-06).
 */
const idBearingScanError = (): HTTPError =>
  new HTTPError({
    status: 404,
    retryAfterSeconds: undefined,
    endpoint: 'https://example.test/wp-json/acx/v1/jobs/7f3c1e2a-0000-4000-8000-000000000001/cancel',
    bodyPreview: 'not found',
    message: 'Request failed (404): not found',
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

const mockMutationContext = {} as ScanMutationContext;
const mockCancelContext = {} as CancelMutationContext;

const captureRecords = (): LogRecord[] => {
  const records: LogRecord[] = [];
  setLogSink((record) => {
    records.push(record);
  });
  return records;
};

const renderMutations = (activeJobIds: string[] = []) => {
  const addJob = vi.fn();
  const removeJob = vi.fn<(id: string) => void>();
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
    removeJob,
    setActiveBatchRunId,
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
      return asMutationResult<ReturnType<typeof useScanIdentities>>({ mutate: vi.fn(), isPending: false });
    });
    useClusterIdentitiesMock.mockReturnValue(
      asMutationResult<ReturnType<typeof useClusterIdentities>>({ mutate: vi.fn(), isPending: false }),
    );
    useCancelScanJobsMock.mockImplementation((options) => {
      cancelOptions = options;
      return asMutationResult<ReturnType<typeof useCancelScanJobs>>({ mutate: vi.fn(), isPending: false });
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

    // FEBT1-W2B-02: the submit line must be joinable to EVERY job in the batch, not just
    // jobIds[0] — job-2's later sse.*/stream.done records carry only its own jobId.
    expect(jobEvents[0].fields.jobIds).toEqual(['job-1', 'job-2']);
    expect(jobEvents[0].fields.jobCount).toBe(2);
    expect(jobEvents[0].fields.batchRunId).toBe('run-1');

    const perJob = records.filter((record) => record.message === 'scan.submit_job');
    expect(perJob.map((record) => record.fields.jobId)).toEqual(['job-1', 'job-2']);
    perJob.forEach((record) => {
      expect(record.fields.batchRunId).toBe('run-1');
    });
  });

  it('logs full jobIds, jobCount, and batchRunId on scan.submit [FEBT1-W2B-02]', () => {
    const records = captureRecords();
    renderMutations();

    scanOptions?.onSuccess?.(
      scanResponse(['job-1', 'job-2', 'job-3'], 4),
      [1, 2, 3],
      undefined,
      mockMutationContext,
    );

    const jobEvents = records.filter((record) => record.fields.event === 'scan.submit');
    expect(jobEvents).toHaveLength(1);
    expect(jobEvents[0].fields).toEqual(
      expect.objectContaining({
        event: 'scan.submit',
        jobIds: ['job-1', 'job-2', 'job-3'],
        jobCount: 3,
        batchRunId: 'run-1',
      }),
    );
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
    // A failed submit is still a unit of work: both of its records must carry the same
    // correlation id, or the wide event cannot be joined to the classified error (OBS-03).
    expect(jobEvents[0].fields.requestId).toEqual(expect.any(String));
    expect(errorRecords[0].fields.requestId).toBe(jobEvents[0].fields.requestId);
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

    cancelOptions?.onSuccess?.([], ['job-9'], undefined, mockCancelContext);

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

    cancelOptions?.onError?.(error, ['job-9'], undefined, mockCancelContext);

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
  it('[FEBT-1-W1-O-06] redacts an id segment inside a logged endpoint via the shared redactor', () => {
    const records = captureRecords();
    const error = idBearingScanError();
    renderMutations();

    scanOptions?.onError?.(error, [1], undefined, mockMutationContext);

    const errorRecords = records.filter((record) => record.level === 'error');
    expect(errorRecords).toHaveLength(1);
    expect(errorRecords[0].fields.endpoint).toBe(`/wp-json/acx/v1/jobs/${REDACTED_SEGMENT}/cancel`);
    expect(JSON.stringify(records)).not.toContain('7f3c1e2a');
  });

  it('[FEBT-1-W1-O-06] redacts an id segment on the cancel path too', () => {
    const records = captureRecords();
    const error = idBearingScanError();
    renderMutations(['job-9']);

    cancelOptions?.onError?.(error, ['job-9'], undefined, mockCancelContext);

    const errorRecords = records.filter((record) => record.level === 'error');
    expect(errorRecords).toHaveLength(1);
    expect(errorRecords[0].fields.endpoint).toBe(`/wp-json/acx/v1/jobs/${REDACTED_SEGMENT}/cancel`);
    const cancelEvent = records.find((record) => record.fields.event === 'scan.cancel');
    expect(cancelEvent?.fields.requestId).toEqual(expect.any(String));
    expect(errorRecords[0].fields.requestId).toBe(cancelEvent?.fields.requestId);
  });

  it('[FEBT-1-W1-O-02][OBS-03] one correlation id spans a submit and every per-job line', () => {
    const records = captureRecords();
    renderMutations();

    scanOptions?.onMutate?.([1, 2], mockMutationContext);
    scanOptions?.onSuccess?.(scanResponse(['job-1', 'job-2'], 4), [1, 2], undefined, mockMutationContext);

    const correlated = records.filter(
      (record) => record.fields.event === 'scan.submit' || record.message === 'scan.submit_job',
    );
    expect(correlated).toHaveLength(3);
    const ids = new Set(correlated.map((record) => record.fields.requestId));
    expect(ids.size).toBe(1);
    expect([...ids][0]).toEqual(expect.any(String));
  });

  it('[FEBT-1-W1-O-02][OBS-03] a cancel is its own unit of work, not the scan\'s', () => {
    const records = captureRecords();
    renderMutations(['job-9']);

    scanOptions?.onMutate?.([1], mockMutationContext);
    scanOptions?.onSuccess?.(scanResponse(['job-9'], 4), [1], undefined, mockMutationContext);
    cancelOptions?.onMutate?.(['job-9'], mockCancelContext);
    cancelOptions?.onSuccess?.(undefined as never, ['job-9'], undefined, mockCancelContext);

    const submit = records.find((record) => record.fields.event === 'scan.submit');
    const cancel = records.find((record) => record.fields.event === 'scan.cancel');
    expect(submit?.fields.requestId).toEqual(expect.any(String));
    expect(cancel?.fields.requestId).toEqual(expect.any(String));
    expect(cancel?.fields.requestId).not.toBe(submit?.fields.requestId);
  });
});

describe('[FEBT2-W2-T][OBS-03] the submit unit publishes a correlation id the SSE stream can inherit', () => {
  beforeEach(() => {
    scanOptions = undefined;
    cancelOptions = undefined;
    setLogLevel('debug');
    useScanIdentitiesMock.mockImplementation((options) => {
      scanOptions = options;
      return asMutationResult<ReturnType<typeof useScanIdentities>>({ mutate: vi.fn(), isPending: false });
    });
    useClusterIdentitiesMock.mockReturnValue(
      asMutationResult<ReturnType<typeof useClusterIdentities>>({ mutate: vi.fn(), isPending: false }),
    );
    useCancelScanJobsMock.mockImplementation((options) => {
      cancelOptions = options;
      return asMutationResult<ReturnType<typeof useCancelScanJobs>>({ mutate: vi.fn(), isPending: false });
    });
  });

  afterEach(() => {
    setLogSink(null);
    setLogLevel(null);
    vi.clearAllMocks();
  });

  it('resolves every job the submit created to the SAME id the submit logged', () => {
    const records = captureRecords();
    const { result } = renderMutations();

    scanOptions?.onMutate?.([1, 2], mockMutationContext);
    scanOptions?.onSuccess?.(scanResponse(['job-1', 'job-2'], 4), [1, 2], undefined, mockMutationContext);

    const submit = records.find((record) => record.fields.event === 'scan.submit');
    const submitRequestId = submit?.fields.requestId;
    expect(submitRequestId).toEqual(expect.any(String));
    // Not "some string" — the SAME string the submit line carries, which is the only thing
    // that makes the later stream.* lines greppable from the submit (OBS-03).
    expect(result.current.resolveScanRequestId('job-1')).toBe(submitRequestId);
    expect(result.current.resolveScanRequestId('job-2')).toBe(submitRequestId);
  });

  it('answers null — not a lookalike id — for a job this submit did not create', () => {
    const { result } = renderMutations();

    scanOptions?.onMutate?.([1], mockMutationContext);
    scanOptions?.onSuccess?.(scanResponse(['job-1'], 4), [1], undefined, mockMutationContext);

    // A job rehydrated from persistence, or one the backend auto-chained, was never part of
    // this submit. Claiming it would make a grep return a confident wrong answer, which is
    // worse than returning nothing (ml CAL-02 'unknown is a valid result'; rg-015).
    expect(result.current.resolveScanRequestId('job-unrelated')).toBeNull();
  });

  it('answers null before any submit has succeeded', () => {
    const { result } = renderMutations();

    expect(result.current.resolveScanRequestId('job-1')).toBeNull();
    // In-flight: onMutate has minted an id but no job ids exist yet to pin it to.
    scanOptions?.onMutate?.([1], mockMutationContext);
    expect(result.current.resolveScanRequestId('job-1')).toBeNull();
  });

  it('answers null for a zero-job submit rather than pinning an empty batch', () => {
    const { result } = renderMutations();

    scanOptions?.onMutate?.([1], mockMutationContext);
    scanOptions?.onSuccess?.(scanResponse([], 0), [1], undefined, mockMutationContext);

    expect(result.current.resolveScanRequestId('job-1')).toBeNull();
  });

  it('drops the previous submit pin the moment a new submit starts', () => {
    const { result } = renderMutations();

    scanOptions?.onMutate?.([1], mockMutationContext);
    scanOptions?.onSuccess?.(scanResponse(['job-old'], 4), [1], undefined, mockMutationContext);
    const firstId = result.current.resolveScanRequestId('job-old');
    expect(firstId).toEqual(expect.any(String));

    scanOptions?.onMutate?.([2], mockMutationContext);
    // The old batch's stream lines must not be joined to the NEW submit.
    expect(result.current.resolveScanRequestId('job-old')).toBeNull();

    scanOptions?.onSuccess?.(scanResponse(['job-new'], 4), [2], undefined, mockMutationContext);
    expect(result.current.resolveScanRequestId('job-old')).toBeNull();
    const secondId = result.current.resolveScanRequestId('job-new');
    expect(secondId).toEqual(expect.any(String));
    expect(secondId).not.toBe(firstId);
  });

  it('[FEBT2-LB-NEW-02][RES-20] a successful cancel releases EVERY active job id, not just the first', () => {
    const { removeJob } = renderMutations(['job-a', 'job-b', 'job-c']);

    cancelOptions?.onMutate?.(['job-a', 'job-b', 'job-c'], mockCancelContext);
    cancelOptions?.onSuccess?.(undefined as never, ['job-a', 'job-b', 'job-c'], undefined, mockCancelContext);

    // This is the first link in the chain that closes the SSE transport after a cancel:
    // emptying activeJobs is what drives latestJobId to null in useJobStateMachine, which is
    // what tears the EventSource down. A cancel that released only jobIds[0] would leave a
    // live stream for work the operator stopped (RES-20: finish what you start).
    expect(removeJob.mock.calls.map(([id]) => id)).toEqual(['job-a', 'job-b', 'job-c']);
  });

  it('[FEBT2-W2-T-02][RES-07] a successful cancel reclaims the batch-run id, not just the jobs', () => {
    const { removeJob, setActiveBatchRunId } = renderMutations(['job-a']);

    cancelOptions?.onMutate?.(['job-a'], mockCancelContext);
    cancelOptions?.onSuccess?.(undefined as never, ['job-a'], undefined, mockCancelContext);

    // Releasing the jobs is not enough. useJobStateMachine derives
    // `activeBatchRunId ?? latestScanJob?.batchRunId`, and useRecognitionHooks enables
    // `useBatchRunStatus(batchRunId, Boolean(batchRunId))` off that value — so a retained
    // id outlives the run it names and polls a batch that is gone, forever. Cancel is an
    // exit from the run and must reclaim what the run allocated (RES-07: whatever
    // accumulates needs a reclaimer shipped with it).
    expect(removeJob.mock.calls.map(([id]) => id)).toEqual(['job-a']);
    expect(setActiveBatchRunId).toHaveBeenCalledWith(null);
  });

  it('[FEBT2-W2-T-02] the batch-run id survives a FAILED cancel — nothing was reclaimed', () => {
    const { setActiveBatchRunId } = renderMutations(['job-a']);

    cancelOptions?.onMutate?.(['job-a'], mockCancelContext);
    cancelOptions?.onError?.(new Error('cancel rejected'), ['job-a'], undefined, mockCancelContext);

    // Negative control for the reclaim above: the run is still live when the cancel
    // request fails, so clearing the id here would blind the poll to a run that is still
    // producing progress. Only the success path is an exit.
    expect(setActiveBatchRunId).not.toHaveBeenCalled();
  });
});
