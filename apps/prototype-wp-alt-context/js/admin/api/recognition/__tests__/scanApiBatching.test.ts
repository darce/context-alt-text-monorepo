import { beforeEach, describe, expect, it, vi } from 'vitest';

import { scanFaces, scanFacesBatched } from '../scanApi';
import type { AnalyzeResponse } from '../types';
import type { HTTPOptions } from '../../../utils/http';

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

describe('scanFacesBatched chunk size', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation((_endpoint: string, options?: HTTPOptions) => {
      const mediaIds = hasMediaIds(options?.body) ? options.body.media_ids : [];
      return Promise.resolve(makeAnalyzeResponse(mediaIds));
    });
    mockConfig.maxMediaPerBatch = 10000;
  });

  it('sends a single request when total <= server multipart cap of 5', async () => {
    const result = await scanFacesBatched({ mediaIds: [1, 2, 3, 4, 5] });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.jobs).toHaveLength(1);
    expect(getRequestBody(0)).toEqual(expect.objectContaining({ media_ids: [1, 2, 3, 4, 5] }));
    expect(getRequestBody(0).idempotency_key).toBe(`${result.batchRunId}-b0`);
    expect(getRequestBody(0).idempotency_key).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
  });

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
