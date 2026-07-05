import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import {
  correctDescriptionHistoryItem,
  describeMedia,
  fetchDescriptionCandidates,
  fetchDescriptionHistory,
  resolveDescribeErrorMessage,
} from '../describeApi';

const mockConfig = {
  nonce: 'nonce-xyz',
  endpoints: {
    recognitionDescribe: 'https://example.com/acx/v1/recognition/describe',
    recognitionDescribeCandidates: 'https://example.com/acx/v1/recognition/describe/candidates',
    recognitionDescribeHistory: 'https://example.com/acx/v1/recognition/describe/history',
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

  it('POSTs write intent fields when requested', async () => {
    fetchApiMock.mockResolvedValue({
      ...sampleResponse,
      alt_text_write: { status: 'forced_overwrite', existing_alt_present: true },
    });

    const result = await describeMedia(42, { writeAlt: true, force: true });

    expect(result.alt_text_write?.status).toBe('forced_overwrite');
    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [, options] = fetchApiMock.mock.calls[0];
    expect(options).toMatchObject({
      method: 'POST',
      body: { media_id: 42, write_alt: true, force: true },
      restNonce: 'nonce-xyz',
    });
  });

  it('fetches dry-run description candidates without posting to the backend describe action', async () => {
    fetchApiMock.mockResolvedValue({
      candidates: [{ media_id: 42, filename: '42.jpg', title: 'A flower', mime_type: 'image/jpeg', current_alt_text: '', reason: 'missing_alt' }],
      exclusions: [],
      limit: 10,
      offset: 0,
      total_candidates: 1,
      total_exclusions: 0,
    });

    const result = await fetchDescriptionCandidates({ limit: 10, offset: 0 });

    expect(result.total_candidates).toBe(1);
    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [endpoint, options] = fetchApiMock.mock.calls[0];
    expect(endpoint).toBe('https://example.com/acx/v1/recognition/describe/candidates?limit=10&offset=0');
    expect(options).toMatchObject({
      method: 'GET',
      restNonce: 'nonce-xyz',
    });
    expect(options).not.toHaveProperty('body');
  });

  it('loads description history with pagination and the REST nonce', async () => {
    const historyResponse = {
      total: 1,
      items: [
        {
          media_id: 42,
          title: 'Bridge',
          mime_type: 'image/jpeg',
          current_alt_text: 'Bridge at dusk',
          generated_alt_text: 'A bridge over water.',
          provenance: sampleResponse,
          human_edit: null,
          run_status: null,
        },
      ],
    };
    fetchApiMock.mockResolvedValue(historyResponse);

    const result = await fetchDescriptionHistory({ limit: 25, offset: 50 });

    expect(result).toEqual(historyResponse);
    expect(fetchApiMock).toHaveBeenCalledWith(
      'https://example.com/acx/v1/recognition/describe/history?limit=25&offset=50',
      {
        method: 'GET',
        restNonce: 'nonce-xyz',
      },
    );
  });

  it('posts an edited alt text correction for a history item', async () => {
    const corrected = {
      media_id: 42,
      title: 'Bridge',
      mime_type: 'image/jpeg',
      current_alt_text: 'Corrected bridge alt text',
      generated_alt_text: 'A bridge over water.',
      provenance: sampleResponse,
      human_edit: {
        alt_text: 'Corrected bridge alt text',
        edited_at: '2026-07-04 12:00:00',
        user_id: 7,
      },
      run_status: null,
    };
    fetchApiMock.mockResolvedValue(corrected);

    const result = await correctDescriptionHistoryItem(42, 'Corrected bridge alt text');

    expect(result).toEqual(corrected);
    expect(fetchApiMock).toHaveBeenCalledWith(
      'https://example.com/acx/v1/recognition/describe/history/42/correction',
      {
        method: 'POST',
        body: { alt_text: 'Corrected bridge alt text' },
        restNonce: 'nonce-xyz',
      },
    );
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
