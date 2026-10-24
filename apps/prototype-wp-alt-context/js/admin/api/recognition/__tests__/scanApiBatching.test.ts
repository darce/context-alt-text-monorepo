import { beforeEach, describe, expect, it, vi } from 'vitest';

import { scanFaces, scanFacesBatched } from '../scanApi';
import type { AnalyzeResponse } from '../types';
import type { HTTPOptions } from '../../../utils/http';
import { AuthExpiredError, HTTPError } from '../../../utils/errorTaxonomy';
import { _resetCooldownForTests, isCoolingDown } from '../../../utils/recognitionCooldown';

interface ScanRequestBody {
  media_ids: number[];
  idempotency_key?: string;
  batch_index?: number;
  submitted_total?: number;
}
type FetchRequiredApiMock = (endpoint: string, options?: HTTPOptions) => Promise<AnalyzeResponse | { status: string }>;

const hasMediaIds = (value: unknown): value is ScanRequestBody => {
  if (typeof value !== 'object' || value === null) {
    return false;
  }

  const maybeMediaIds = (value as { media_ids?: unknown }).media_ids;
  return Array.isArray(maybeMediaIds);
};

const makeAnalyzeResponse = (mediaIds: number[]): AnalyzeResponse => ({
  id: `job-${mediaIds.join('-')}`,
  type: 'analyze',
  status: 'pending',
  progress: { completed: 0, total: mediaIds.length },
  started_at: '2026-04-25T00:00:00Z',
  finished_at: null,
});

const mockConfig = {
  nonce: 'nonce-123',
  ajaxUrl: '/wp-admin/admin-ajax.php',
  endpoints: {
    recognitionAnalyze: 'https://example.com/analyze',
    recognitionBatchRuns: 'https://example.com/batch-runs',
  } as Record<string, string>,
  maxMediaPerBatch: 10000,
  devMode: false,
};

vi.mock('../../config', () => ({
  getEndpoint: vi.fn((primary: string) => mockConfig.endpoints[primary] ?? `https://example.com/${primary}`),
  getConfig: vi.fn(() => mockConfig),
  isDevMode: vi.fn(() => false),
}));

const fetchMock = vi.fn<FetchRequiredApiMock>();

const getRequestBody = (callIndex: number): ScanRequestBody => {
  const options = fetchMock.mock.calls[callIndex]?.[1];
  expect(options).toBeDefined();
  expect(hasMediaIds(options?.body)).toBe(true);
  return options!.body as ScanRequestBody;
};

vi.mock('../../../utils/http', () => ({
  fetchApi: (endpoint: string, options?: HTTPOptions) => fetchMock(endpoint, options),
  fetchRequiredApi: (endpoint: string, options?: HTTPOptions) => fetchMock(endpoint, options),
  stripTrailingSlash: (value: string) => (value.endsWith('/') ? value.slice(0, -1) : value),
}));

const analyzeCalls = () => fetchMock.mock.calls.filter(([url]) => url === mockConfig.endpoints.recognitionAnalyze);

const refusedStatus = (status: number): HTTPError =>
  new HTTPError({
    status,
    endpoint: mockConfig.endpoints.recognitionAnalyze,
    bodyPreview: '',
    retryAfterSeconds: undefined,
    message: 'Scan refused',
  });

/** Every run-wide refusal shape the submit loop must stop on (401/402/403/429 and session expiry). */
const RUN_WIDE_REFUSALS: [string, () => Error][] = [
  ['HTTP 401', () => refusedStatus(401)],
  ['HTTP 402', () => refusedStatus(402)],
  ['HTTP 403', () => refusedStatus(403)],
  ['HTTP 429', () => refusedStatus(429)],
  ['session expiry', () => new AuthExpiredError({ endpoint: mockConfig.endpoints.recognitionAnalyze, status: 403 })],
];

describe('scanFacesBatched chunk size', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation((_endpoint: string, options?: HTTPOptions) => {
      const mediaIds = hasMediaIds(options?.body) ? options.body.media_ids : [];
      return Promise.resolve(makeAnalyzeResponse(mediaIds));
    });
    mockConfig.maxMediaPerBatch = 10000;
    _resetCooldownForTests();
  });

  it.each(RUN_WIDE_REFUSALS)(
    'returns the accepted jobs with the original %s that stopped later submissions',
    async (_label, makeRefusal) => {
      const error = makeRefusal();
      fetchMock.mockResolvedValueOnce(makeAnalyzeResponse([1, 2, 3, 4, 5])).mockRejectedValueOnce(error);
      const result = await scanFacesBatched({ mediaIds: Array.from({ length: 15 }, (_, i) => i + 1) });
      expect(result.jobs.map((job) => job.id)).toEqual(['job-1-2-3-4-5']);
      expect(result.refusal).toBe(error);
      expect(analyzeCalls()).toHaveLength(2);
      expect(fetchMock.mock.calls[2]?.[0]).toContain('/client-failures');
      expect(fetchMock.mock.calls[2]?.[1]?.body).toEqual({
        batch_index: 1,
        submitted_total: 15,
        media_ids: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
      });
    },
  );

  it('keeps every accepted chunk when the refusal arrives on a later chunk', async () => {
    const error = refusedStatus(402);
    fetchMock
      .mockResolvedValueOnce(makeAnalyzeResponse([1, 2, 3, 4, 5]))
      .mockResolvedValueOnce(makeAnalyzeResponse([6, 7, 8, 9, 10]))
      .mockRejectedValueOnce(error);
    const result = await scanFacesBatched({ mediaIds: Array.from({ length: 20 }, (_, i) => i + 1) });
    expect(result.jobs.map((job) => job.id)).toEqual(['job-1-2-3-4-5', 'job-6-7-8-9-10']);
    expect(result.refusal).toBe(error);
    expect(analyzeCalls()).toHaveLength(3);
    expect(fetchMock.mock.calls[3]?.[1]?.body).toEqual({
      batch_index: 2,
      submitted_total: 20,
      media_ids: [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
    });
  });

  it('arms the shared recognition cooldown for a later 429 that no rejection will carry', async () => {
    fetchMock.mockResolvedValueOnce(makeAnalyzeResponse([1, 2, 3, 4, 5])).mockRejectedValueOnce(refusedStatus(429));
    await scanFacesBatched({ mediaIds: Array.from({ length: 15 }, (_, i) => i + 1) });
    expect(isCoolingDown()).toBe(true);
  });

  it('leaves the cooldown alone for a later refusal that is not an ask-again-later', async () => {
    fetchMock.mockResolvedValueOnce(makeAnalyzeResponse([1, 2, 3, 4, 5])).mockRejectedValueOnce(refusedStatus(402));
    await scanFacesBatched({ mediaIds: Array.from({ length: 15 }, (_, i) => i + 1) });
    expect(isCoolingDown()).toBe(false);
  });

  it.each(RUN_WIDE_REFUSALS)(
    'rejects an initial ordinary multi-chunk %s with the identical error',
    async (_label, makeRefusal) => {
      const error = makeRefusal();
      fetchMock.mockRejectedValueOnce(error);
      await expect(scanFacesBatched({ mediaIds: Array.from({ length: 15 }, (_, i) => i + 1) })).rejects.toBe(error);
      expect(analyzeCalls()).toHaveLength(1);
      expect(fetchMock.mock.calls[1]?.[1]?.body).toEqual({
        batch_index: 0,
        submitted_total: 15,
        media_ids: Array.from({ length: 15 }, (_, i) => i + 1),
      });
    },
  );

  it('keeps submitting after a batch-local failure and reports no run-wide refusal', async () => {
    fetchMock.mockResolvedValueOnce(makeAnalyzeResponse([1, 2, 3, 4, 5])).mockRejectedValueOnce(refusedStatus(500));
    const result = await scanFacesBatched({ mediaIds: Array.from({ length: 15 }, (_, i) => i + 1) });
    expect(result.jobs.map((job) => job.id)).toEqual(['job-1-2-3-4-5', 'job-11-12-13-14-15']);
    expect(result.refusal).toBeUndefined();
    expect(analyzeCalls()).toHaveLength(3);
    expect(fetchMock.mock.calls[2]?.[1]?.body).toEqual({
      batch_index: 1,
      submitted_total: 15,
      media_ids: [6, 7, 8, 9, 10],
    });
  });

  it.each([401, 402, 403, 429])(
    'stops all remaining submissions after HTTP %i and preserves the rejection',
    async (status) => {
      const error = new HTTPError({
        status,
        endpoint: mockConfig.endpoints.recognitionAnalyze,
        bodyPreview: '',
        retryAfterSeconds: undefined,
        message: 'Scan refused',
      });
      const mediaIds = Array.from({ length: 100 }, (_, i) => i + 1);
      fetchMock.mockRejectedValueOnce(error);
      await expect(scanFacesBatched({ mediaIds, developmentFacesOnly: true })).rejects.toBe(error);
      expect(fetchMock.mock.calls.filter(([url]) => url === mockConfig.endpoints.recognitionAnalyze)).toHaveLength(1);
      expect(fetchMock.mock.calls[1]?.[1]?.body).toEqual({ batch_index: 0, submitted_total: 100, media_ids: mediaIds });
    },
  );

  it.each([402, 429])('surfaces HTTP %i for a single ordinary scan instead of empty success', async (status) => {
    const error = new HTTPError({
      status,
      endpoint: mockConfig.endpoints.recognitionAnalyze,
      bodyPreview: '',
      retryAfterSeconds: undefined,
      message: 'Scan refused',
    });
    fetchMock.mockRejectedValueOnce(error);
    await expect(scanFacesBatched({ mediaIds: [1] })).rejects.toBe(error);
  });

  it('keeps accepted jobs trackable and accounts for all skipped media after a later refusal', async () => {
    const error = new HTTPError({
      status: 402,
      endpoint: mockConfig.endpoints.recognitionAnalyze,
      bodyPreview: '',
      retryAfterSeconds: undefined,
      message: 'Allowance exhausted',
    });
    fetchMock.mockResolvedValueOnce(makeAnalyzeResponse([1, 2, 3, 4, 5])).mockRejectedValueOnce(error);
    const result = await scanFacesBatched({ mediaIds: Array.from({ length: 15 }, (_, i) => i + 1) });
    expect(result.jobs.map((job) => job.id)).toEqual(['job-1-2-3-4-5']);
    expect(fetchMock.mock.calls.filter(([url]) => url === mockConfig.endpoints.recognitionAnalyze)).toHaveLength(2);
    expect(fetchMock.mock.calls[2]?.[1]?.body).toEqual({
      batch_index: 1,
      submitted_total: 15,
      media_ids: [6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    });
  });

  it('sends a single request when total <= server multipart cap of 5', async () => {
    const result = await scanFacesBatched({ mediaIds: [1, 2, 3, 4, 5] });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.jobs).toHaveLength(1);
    expect(getRequestBody(0)).toEqual(expect.objectContaining({ media_ids: [1, 2, 3, 4, 5] }));
    expect(getRequestBody(0).idempotency_key).toBe(`${result.batchRunId}-b0`);
    expect(getRequestBody(0).idempotency_key).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
  });

  it('marks every face-only batch for the server development gate and calls only analyze', async () => {
    await scanFacesBatched({ mediaIds: [1, 2, 3, 4, 5, 6], developmentFacesOnly: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [endpoint, options] of fetchMock.mock.calls) {
      expect(endpoint).toBe(mockConfig.endpoints.recognitionAnalyze);
      expect(options?.body).toEqual(expect.objectContaining({ development_faces_only: true }));
    }
  });

  it.each([{ mediaIds: [1] }, { mediaIds: [1, 2, 3, 4, 5, 6] }])(
    'surfaces rejected developer submissions for $mediaIds instead of an empty success',
    async ({ mediaIds }) => {
      fetchMock.mockRejectedValue(new Error('Development API unavailable'));
      await expect(scanFacesBatched({ mediaIds, developmentFacesOnly: true })).rejects.toThrow(
        'Development API unavailable',
      );
    },
  );

  it('chunks into batches of 5 when total exceeds the cap', async () => {
    const result = await scanFacesBatched({ mediaIds: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getRequestBody(0)).toEqual(expect.objectContaining({ media_ids: [1, 2, 3, 4, 5] }));
    expect(getRequestBody(1)).toEqual(expect.objectContaining({ media_ids: [6, 7, 8, 9, 10] }));
    expect(getRequestBody(0).idempotency_key).toBe(`${result.batchRunId}-b0`);
    expect(getRequestBody(1).idempotency_key).toBe(`${result.batchRunId}-b1`);
    expect(getRequestBody(1).idempotency_key).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(getRequestBody(0).idempotency_key).not.toBe(getRequestBody(1).idempotency_key);
    expect(result.jobs).toHaveLength(2);
  });

  it('reuses the operation key when a failed chunk is retried', async () => {
    const request = { mediaIds: [1, 2], batchRunId: 'batch-retry-action-123', batchIndex: 2 };
    fetchMock.mockRejectedValueOnce(new Error('response lost'));

    await expect(scanFaces(request)).rejects.toThrow('response lost');
    await scanFaces(request);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getRequestBody(0).idempotency_key).toBe('batch-retry-action-123-b2');
    expect(getRequestBody(1).idempotency_key).toBe(getRequestBody(0).idempotency_key);
  });

  it('uses distinct operation keys for separate actions with identical media', async () => {
    const first = await scanFacesBatched({ mediaIds: [1, 2] });
    const second = await scanFacesBatched({ mediaIds: [1, 2] });

    expect(getRequestBody(0).idempotency_key).toBe(`${first.batchRunId}-b0`);
    expect(getRequestBody(1).idempotency_key).toBe(`${second.batchRunId}-b0`);
    expect(getRequestBody(0).idempotency_key).not.toBe(getRequestBody(1).idempotency_key);
  });

  it('mints an operation key for each direct scan action without a batch run ID', async () => {
    await scanFaces({ mediaIds: [1, 2] });
    await scanFaces({ mediaIds: [1, 2] });

    expect(getRequestBody(0).idempotency_key).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(getRequestBody(1).idempotency_key).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(getRequestBody(0).idempotency_key).not.toBe(getRequestBody(1).idempotency_key);
  });

  it('chunks at 5 even when configured maxMediaPerBatch is higher', async () => {
    mockConfig.maxMediaPerBatch = 100;
    await scanFacesBatched({ mediaIds: Array.from({ length: 12 }, (_, i) => i + 1) });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(getRequestBody(0).media_ids).toHaveLength(5);
    expect(getRequestBody(1).media_ids).toHaveLength(5);
    expect(getRequestBody(2).media_ids).toHaveLength(2);
  });

  it('falls back to multipart cap when configured size is non-positive', async () => {
    mockConfig.maxMediaPerBatch = 0;
    await scanFacesBatched({ mediaIds: [1, 2, 3, 4, 5, 6] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getRequestBody(0).media_ids).toHaveLength(5);
    expect(getRequestBody(1).media_ids).toEqual([6]);
  });

  it('respects a configured size below the multipart cap', async () => {
    mockConfig.maxMediaPerBatch = 3;
    await scanFacesBatched({ mediaIds: [1, 2, 3, 4, 5] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getRequestBody(0).media_ids).toHaveLength(3);
    expect(getRequestBody(1).media_ids).toHaveLength(2);
  });

  it('records a synthetic failed batch when a multipart submit rejects', async () => {
    fetchMock.mockRejectedValueOnce(new Error('network down'));
    fetchMock.mockResolvedValueOnce({ status: 'recorded' });

    const result = await scanFacesBatched({ mediaIds: [1, 2, 3, 4, 5, 6] });

    expect(result.jobs).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]?.[0]).toContain('/client-failures');
    expect(fetchMock.mock.calls[1]?.[1]?.body).toEqual({
      batch_index: 0,
      submitted_total: 6,
      media_ids: [1, 2, 3, 4, 5],
    });
  });
});
