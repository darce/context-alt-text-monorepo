import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import { describeMedia, resolveDescribeErrorMessage } from '../describeApi';

const mockConfig = {
  nonce: 'nonce-xyz',
  endpoints: {
    recognitionDescribe: 'https://example.com/acx/v1/recognition/describe',
  } as Record<string, string>,
};

vi.mock('../config', () => ({
  getEndpoint: vi.fn((...keys: string[]) => {
    const configured = keys.find((key) => mockConfig.endpoints[key]);
    return configured ? mockConfig.endpoints[configured] : `https://example.com/${keys[0] ?? 'default'}`;
  }),
  getConfig: vi.fn(() => mockConfig),
}));

vi.mock('../recognition/requestTimeout', () => ({
  createRecognitionTimeoutSignal: vi.fn(() => undefined),
}));

vi.mock('../../utils/http', () => ({
  fetchRequiredApi: vi.fn(),
}));

const fetchApiMock = vi.mocked(httpModule.fetchRequiredApi);

const sampleResponse = {
  tenant_id: '00000000-0000-4000-8000-000000000001',
  media_id: 42,
  image_hash: 'sha256:abc',
  context_hash: 'ctx',
  adapter: 'local_cpu',
  model_id: 'microsoft/Florence-2-base-ft',
  model_version: 'florence-2-base-ft',
  prompt_or_task_version: 'more_detailed_caption+od.b3.v1',
  visual_facts: { caption: 'A red flower.', objects: ['flower'], ocr_text: null },
  alt_text_draft: 'A red flower.',
  context_used: { sources: [], applied: false },
  provider_disclosure: { provider: 'local', left_service_boundary: false },
  cached: false,
  duration_ms: 13800,
  retention_class: 'retain_all',
};

describe('describeApi', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('POSTs media_id to the describe endpoint with the REST nonce and returns the envelope', async () => {
    fetchApiMock.mockResolvedValue(sampleResponse);

    const result = await describeMedia(42);

    expect(result).toEqual(sampleResponse);
    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [endpoint, options] = fetchApiMock.mock.calls[0];
    expect(endpoint).toBe('https://example.com/acx/v1/recognition/describe');
    expect(options).toMatchObject({
      method: 'POST',
      body: { media_id: 42 },
      restNonce: 'nonce-xyz',
    });
  });
});

describe('resolveDescribeErrorMessage', () => {
  it('extracts the FastAPI detail string from a 503 stub rejection', () => {
    const err = new Error(
      'Request to .../describe failed (503): {"detail":"description adapter unavailable: florence_large (~39s/image) requires the async describe worker. See ...notes."}',
    );
    expect(resolveDescribeErrorMessage(err, 'fallback')).toContain('async describe worker');
  });

  it('falls back when the error carries no structured detail', () => {
    expect(resolveDescribeErrorMessage(new Error('network down'), 'Could not describe.')).toBe('Could not describe.');
  });
});
