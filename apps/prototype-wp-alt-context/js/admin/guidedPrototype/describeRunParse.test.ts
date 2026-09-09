import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../utils/http';
import {
  cancelBulkDescribeRun,
  fetchBulkDescribeRun,
  GPU_STATE,
  MalformedDescribeRunResponseError,
  parseDescribeRunResponse,
  submitBulkDescribeRun,
} from '../api/describeApi';

vi.mock('../api/config', () => ({
  getConfig: vi.fn(() => ({ nonce: 'nonce-guided' })),
  getEndpoint: vi.fn((key: string) => `https://example.test/${key}`),
}));

vi.mock('../api/recognition/requestTimeout', () => ({
  createRecognitionTimeoutSignal: vi.fn(() => undefined),
}));

vi.mock('../utils/http', () => ({
  fetchRequiredApi: vi.fn(),
}));

const fetchApiMock = vi.mocked(httpModule.fetchRequiredApi);

const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const RUN_ID = '6ba7b810-9dad-41d1-80b4-00c04fd430c8';

const validRun = {
  tenant_id: TENANT_ID,
  run_id: RUN_ID,
  status: 'running',
  phase: 'queued',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 1,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: GPU_STATE.STOPPED,
  recognition_enabled: true,
} as const;

beforeEach(() => {
  vi.clearAllMocks();
});

describe('parseDescribeRunResponse', () => {
  it('accepts a schema-shaped envelope including a non-null gpu_state', () => {
    expect(parseDescribeRunResponse(validRun).run_id).toBe(RUN_ID);
    expect(parseDescribeRunResponse(validRun).gpu_state).toBe(GPU_STATE.STOPPED);
  });

  it('rejects a missing or null run_id so pollers cannot treat undefined as live', () => {
    const missing = { ...validRun } as Record<string, unknown>;
    delete missing.run_id;
    expect(() => parseDescribeRunResponse(missing)).toThrow(MalformedDescribeRunResponseError);
    expect(() => parseDescribeRunResponse({ ...validRun, run_id: null })).toThrow(/response\.run_id/);
    expect(() => parseDescribeRunResponse({ ...validRun, run_id: '' })).toThrow(/response\.run_id/);
  });

  it('rejects a null or unknown gpu_state', () => {
    expect(() => parseDescribeRunResponse({ ...validRun, gpu_state: null })).toThrow(/response\.gpu_state/);
    expect(() => parseDescribeRunResponse({ ...validRun, gpu_state: 'cold' })).toThrow(/response\.gpu_state/);
  });

  it.each([
    ['tenant_id', 'not-a-uuid'],
    ['tenant_id', ` ${TENANT_ID}`],
    ['tenant_id', `${TENANT_ID} `],
    ['run_id', 'not-a-uuid'],
    ['run_id', ` ${RUN_ID}`],
    ['run_id', `${RUN_ID} `],
  ] as const)('rejects a malformed or whitespace-padded %s', (field, value) => {
    expect(() => parseDescribeRunResponse({ ...validRun, [field]: value })).toThrow(
      new MalformedDescribeRunResponseError(`response.${field}`),
    );
  });
});

describe('bulk describe-run wrapper boundaries', () => {
  it.each([
    [
      'submit',
      () => submitBulkDescribeRun([101]),
      'https://example.test/recognitionDescribeRuns',
      { method: 'POST', body: { media_ids: [101] } },
    ],
    [
      'fetch',
      () => fetchBulkDescribeRun(RUN_ID),
      `https://example.test/recognitionDescribeRuns/${RUN_ID}`,
      { method: 'GET' },
    ],
    [
      'cancel',
      () => cancelBulkDescribeRun(RUN_ID),
      `https://example.test/recognitionDescribeRuns/${RUN_ID}/cancel`,
      { method: 'POST' },
    ],
  ] as const)('validates the %s response at the network boundary', async (_label, invoke, endpoint, options) => {
    fetchApiMock.mockResolvedValue(validRun);

    await expect(invoke()).resolves.toEqual(validRun);
    expect(fetchApiMock).toHaveBeenCalledWith(
      endpoint,
      expect.objectContaining({ ...options, restNonce: 'nonce-guided' }),
    );
  });

  it.each([
    ['submit', () => submitBulkDescribeRun([101])],
    ['fetch', () => fetchBulkDescribeRun(RUN_ID)],
    ['cancel', () => cancelBulkDescribeRun(RUN_ID)],
  ] as const)('rejects a malformed response from the %s wrapper', async (_label, invoke) => {
    fetchApiMock.mockResolvedValue({ ...validRun, run_id: 'not-a-uuid' });

    await expect(invoke()).rejects.toThrow(/response\.run_id/);
    expect(fetchApiMock).toHaveBeenCalledOnce();
  });
});
