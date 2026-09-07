import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import {
  applyDescribeRunDrafts,
  correctDescriptionHistoryItem,
  describeMedia,
  DESCRIPTION_CORRECTION_CODE,
  GPU_STATE,
  NAMING_PROVENANCE_STATUS,
  NAMING_REALIZER,
  fetchDescribeRunItems,
  fetchDescriptionCandidates,
  fetchDescriptionHistory,
  isGpuState,
  parseNamingProvenance,
  resolveDescribeErrorCode,
  resolveDescribeErrorDataBooleanField,
  resolveDescribeErrorDataField,
  resolveDescribeErrorMessage,
  type DescriptionCandidateRow,
  type DescribeRunItemsResponse,
} from '../describeApi';

const mockConfig = {
  nonce: 'nonce-xyz',
  ajaxUrl: '/wp-admin/admin-ajax.php',
  endpoints: {
    recognitionDescribe: 'https://example.com/acx/v1/recognition/describe',
    recognitionDescribeCandidates: 'https://example.com/acx/v1/recognition/describe/candidates',
    recognitionDescribeHistory: 'https://example.com/acx/v1/recognition/describe/history',
    recognitionDescribeRuns: 'https://example.com/acx/v1/recognition/describe/runs',
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

  it('exports the exact canonical GPU state vocabulary', () => {
    expect(Object.values(GPU_STATE)).toEqual(['unknown', 'stopped', 'starting', 'warming', 'ready', 'degraded']);
  });

  it('recognizes only canonical GPU states at runtime', () => {
    for (const state of Object.values(GPU_STATE)) {
      expect(isGpuState(state)).toBe(true);
    }

    for (const value of ['bogus', '', null, undefined, 42, {}]) {
      expect(isGpuState(value)).toBe(false);
    }
  });

  it('exports the exact canonical naming provenance vocabulary', () => {
    expect(Object.values(NAMING_PROVENANCE_STATUS)).toEqual([
      'applied',
      'disabled',
      'skipped_budget',
      'no_faces',
    ]);
    expect(Object.values(NAMING_REALIZER)).toEqual(['grounded', 'positional_fallback']);
  });

  it('accepts a valid naming provenance shape at the API boundary', () => {
    expect(
      parseNamingProvenance({
        status: NAMING_PROVENANCE_STATUS.APPLIED,
        realizer: NAMING_REALIZER.POSITIONAL_FALLBACK,
        names_applied: ['Ada', 'Bea'],
      }),
    ).toEqual({
      status: 'applied',
      realizer: 'positional_fallback',
      names_applied: ['Ada', 'Bea'],
    });
  });

  it('rejects malformed naming provenance instead of exposing unvalidated values', () => {
    expect(
      parseNamingProvenance({
        status: 'applied',
        realizer: 'untrusted-method',
        names_applied: ['Ada', 42],
      }),
    ).toBeUndefined();
    expect(parseNamingProvenance(null)).toBeUndefined();
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

  it('fetches a run\'s per-item drafts with existing_alt bucketing and the REST nonce', async () => {
    const itemsResponse = {
      run_id: 'run-abc',
      items: [
        {
          media_id: 70,
          status: 'completed',
          alt_text_draft: 'A described bridge.',
          caption: 'A bridge.',
          provenance: sampleResponse,
          tier: 'final_gpu',
          result_generation: 2,
          existing_alt: true,
        },
        {
          media_id: 71,
          status: 'completed',
          alt_text_draft: 'A described flower.',
          caption: 'A flower.',
          provenance: sampleResponse,
          tier: 'final_gpu',
          result_generation: 1,
          existing_alt: false,
        },
      ],
    } satisfies DescribeRunItemsResponse;
    fetchApiMock.mockResolvedValue(itemsResponse);

    const result = await fetchDescribeRunItems('run-abc');

    expect(result).toEqual(itemsResponse);
    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [endpoint, options] = fetchApiMock.mock.calls[0];
    expect(endpoint).toBe('https://example.com/acx/v1/recognition/describe/runs/run-abc/items');
    expect(options).toMatchObject({ method: 'GET', restNonce: 'nonce-xyz' });
    expect(options).not.toHaveProperty('body');
  });

  it('preserves valid item naming provenance while normalizing the response boundary', async () => {
    const naming = {
      status: NAMING_PROVENANCE_STATUS.APPLIED,
      realizer: NAMING_REALIZER.GROUNDED,
      names_applied: ['Ada'],
    } as const;
    const itemsResponse = {
      run_id: 'run-naming',
      items: [
        {
          media_id: 73,
          status: 'completed',
          alt_text_draft: 'Ada stands by the window.',
          caption: 'A person by a window.',
          provenance: { naming },
          tier: 'final_gpu',
          result_generation: 1,
          existing_alt: false,
        },
      ],
    } satisfies DescribeRunItemsResponse;
    fetchApiMock.mockResolvedValue(itemsResponse);

    const result = await fetchDescribeRunItems('run-naming');

    expect(result.items[0]?.provenance).toEqual({ naming });
  });

  it('drops malformed item naming provenance while preserving the rest of the item', async () => {
    const itemsResponse = {
      run_id: 'run-malformed-naming',
      items: [
        {
          media_id: 74,
          status: 'completed',
          alt_text_draft: 'A person by a window.',
          caption: 'A person by a window.',
          provenance: {
            naming: {
              status: 'applied',
              realizer: 'untrusted-method',
              names_applied: ['Ada', 42],
            },
          },
          tier: 'final_gpu',
          result_generation: 1,
          existing_alt: false,
        },
      ],
    };
    fetchApiMock.mockResolvedValue(itemsResponse);

    const result = await fetchDescribeRunItems('run-malformed-naming');

    expect(result.items[0]?.provenance).toEqual({});
    expect(result.items[0]?.alt_text_draft).toBe('A person by a window.');
  });

  it('preserves a null tier for a queued run item that has not generated a result', async () => {
    const itemsResponse = {
      run_id: 'run-queued',
      items: [
        {
          media_id: 72,
          status: 'queued',
          alt_text_draft: null,
          caption: null,
          provenance: null,
          tier: null,
          result_generation: 0,
          existing_alt: false,
        },
      ],
    } satisfies DescribeRunItemsResponse;
    fetchApiMock.mockResolvedValue(itemsResponse);

    const result = await fetchDescribeRunItems('run-queued');

    expect(result.items[0]?.tier).toBeNull();
  });

  it('url-encodes the run id when reading items', async () => {
    fetchApiMock.mockResolvedValue({ run_id: 'a/b', items: [] });

    await fetchDescribeRunItems('a/b');

    const [endpoint] = fetchApiMock.mock.calls[0];
    expect(endpoint).toBe('https://example.com/acx/v1/recognition/describe/runs/a%2Fb/items');
  });

  it('applies run drafts with an explicit overwrite list and the REST nonce', async () => {
    const applyResponse = {
      run_id: 'run-abc',
      applied: [71, 70],
      partial: [],
      skipped_existing: [],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    };
    fetchApiMock.mockResolvedValue(applyResponse);

    const result = await applyDescribeRunDrafts('run-abc', [70]);

    expect(result).toEqual(applyResponse);
    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [endpoint, options] = fetchApiMock.mock.calls[0];
    expect(endpoint).toBe('https://example.com/acx/v1/recognition/describe/runs/run-abc/apply');
    expect(options).toMatchObject({
      method: 'POST',
      body: { overwrite_media_ids: [70] },
      restNonce: 'nonce-xyz',
    });
  });

  it('applies run drafts with an empty overwrite list by default (never clobbers existing alt)', async () => {
    fetchApiMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [],
      skipped_existing: [70],
      skipped_no_draft: [],
      skipped_invalid: [],
      failed: [],
    });

    await applyDescribeRunDrafts('run-abc');

    const [, options] = fetchApiMock.mock.calls[0];
    expect(options).toMatchObject({ body: { overwrite_media_ids: [] } });
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

  it('omits decorative from the correction body when the flag is not requested [WBUX-5-S2C3C-BR-01]', async () => {
    // Existing callers pass only (mediaId, altText). The wire body must stay
    // identical to today's { alt_text } — server defaults decorative to false.
    // [TEST-15] discrimination: goes RED if decorative:false is always sent, or
    // if decorative:true is sent when the caller omits the option.
    fetchApiMock.mockResolvedValue({
      media_id: 42,
      title: 'Bridge',
      mime_type: 'image/jpeg',
      current_alt_text: 'Corrected bridge alt text',
      generated_alt_text: 'A bridge over water.',
      provenance: sampleResponse,
      human_edit: { alt_text: 'Corrected bridge alt text', edited_at: null, user_id: 7 },
      run_status: null,
    });

    await correctDescriptionHistoryItem(42, 'Corrected bridge alt text');

    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [, options] = fetchApiMock.mock.calls[0];
    expect(options).toMatchObject({
      method: 'POST',
      body: { alt_text: 'Corrected bridge alt text' },
      restNonce: 'nonce-xyz',
    });
    expect(options?.body).not.toHaveProperty('decorative');
  });

  it('posts decorative:true with empty alt_text when marking an image decorative [WBUX-5-S2C3C-BR-01][TEST-06]', async () => {
    // Headline: the deliberate decorative path must send both signals on the wire.
    // [TEST-15] discrimination: goes RED if decorative is dropped from the body,
    // if alt_text is non-empty, or if the flag is only true when alt is non-empty.
    fetchApiMock.mockResolvedValue({
      media_id: 42,
      title: 'Spacer',
      mime_type: 'image/png',
      current_alt_text: '',
      generated_alt_text: '',
      provenance: null,
      human_edit: { alt_text: '', edited_at: null, user_id: 7 },
      run_status: null,
    });

    await correctDescriptionHistoryItem(42, '', { decorative: true });

    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    const [, options] = fetchApiMock.mock.calls[0];
    expect(options).toMatchObject({
      method: 'POST',
      body: { alt_text: '', decorative: true },
      restNonce: 'nonce-xyz',
    });
  });

  it('posts decorative:false when options.decorative is explicit false [A-02][INT-09]', async () => {
    // Un-mark path: explicit false must appear on the wire. Pre-fix only sent
    // decorative when true, so this goes RED without the tri-state body change.
    // [TEST-15] discrimination: fails if decorative is dropped for false.
    fetchApiMock.mockResolvedValue({
      media_id: 42,
      title: 'Bridge',
      mime_type: 'image/jpeg',
      current_alt_text: '',
      generated_alt_text: '',
      provenance: null,
      human_edit: { alt_text: '', edited_at: null, user_id: 7 },
      run_status: null,
      is_decorative: false,
    });

    await correctDescriptionHistoryItem(42, '', { decorative: false });
    const [, options] = fetchApiMock.mock.calls[0];
    expect(options?.body).toEqual({ alt_text: '', decorative: false });
  });

  it('still omits decorative when options is undefined [A-02]', async () => {
    fetchApiMock.mockResolvedValue({
      media_id: 42,
      title: 'Bridge',
      mime_type: 'image/jpeg',
      current_alt_text: 'x',
      generated_alt_text: 'x',
      provenance: null,
      human_edit: { alt_text: 'x', edited_at: null, user_id: 7 },
      run_status: null,
      is_decorative: false,
    });

    await correctDescriptionHistoryItem(42, 'x', undefined);
    const [, options] = fetchApiMock.mock.calls[0];
    expect(options?.body).toEqual({ alt_text: 'x' });
    expect(options?.body).not.toHaveProperty('decorative');
  });

  it('accepts reason decorative on a DescriptionCandidateRow without a cast [WBUX-5-S2C3C-BR-01]', async () => {
    // Type-level pin: assigning reason:'decorative' must compile without `as`.
    // Runtime: the candidates envelope carries the same value.
    const decorativeRow: DescriptionCandidateRow = {
      media_id: 99,
      filename: 'ornament.png',
      title: 'Flourish',
      mime_type: 'image/png',
      current_alt_text: '',
      reason: 'decorative',
    };
    fetchApiMock.mockResolvedValue({
      candidates: [],
      exclusions: [decorativeRow],
      limit: 10,
      offset: 0,
      total_candidates: 0,
      total_exclusions: 1,
    });

    const result = await fetchDescriptionCandidates({ limit: 10, offset: 0 });
    expect(result.exclusions[0]?.reason).toBe('decorative');
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

  it('extracts the WP_Error message from a correction rejection body', () => {
    const err = new Error(
      'Request to .../correction failed (500): {"code":"description_correction_partial","message":"Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.","data":{"status":500}}',
    );
    expect(resolveDescribeErrorMessage(err, 'Could not save.')).toBe(
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.',
    );
  });
});

describe('resolveDescribeErrorCode', () => {
  it('extracts the WP_Error code from a correction rejection body', () => {
    const err = new Error(
      'Request to .../correction failed (500): {"code":"description_correction_partial","message":"Alt text was saved, but the human-edit record could not be stored.","data":{"status":500}}',
    );
    expect(resolveDescribeErrorCode(err)).toBe('description_correction_partial');
  });

  it('returns null when the error carries no structured code', () => {
    expect(resolveDescribeErrorCode(new Error('network down'))).toBeNull();
  });

  it('returns null for non-Error values', () => {
    expect(resolveDescribeErrorCode('not-an-error')).toBeNull();
    expect(resolveDescribeErrorCode(null)).toBeNull();
  });

  it('returns null when the payload has a blank code', () => {
    const err = new Error('Request failed (500): {"code":"  ","message":"something"}');
    expect(resolveDescribeErrorCode(err)).toBeNull();
  });
});

describe('DESCRIPTION_CORRECTION_CODE', () => {
  it('exports the stable correction rejection codes [sr-007]', () => {
    expect(DESCRIPTION_CORRECTION_CODE.PARTIAL).toBe('description_correction_partial');
    expect(DESCRIPTION_CORRECTION_CODE.FAILED).toBe('description_correction_failed');
  });
});

describe('resolveDescribeErrorDataField', () => {
  it('extracts stored_alt_text from a partial correction rejection body', () => {
    const err = new Error(
      'Request to .../correction failed (500): {"code":"description_correction_partial","message":"Alt text was saved, but the human-edit record could not be stored.","data":{"status":500,"stored_alt_text":"Sunset over the bay"}}',
    );
    expect(resolveDescribeErrorDataField(err, 'stored_alt_text')).toBe('Sunset over the bay');
  });

  it('returns null when the named field is absent from data', () => {
    const err = new Error(
      'Request to .../correction failed (500): {"code":"description_correction_partial","message":"Alt text was saved.","data":{"status":500}}',
    );
    expect(resolveDescribeErrorDataField(err, 'stored_alt_text')).toBeNull();
  });

  it('returns null when the error carries no structured payload', () => {
    expect(resolveDescribeErrorDataField(new Error('network down'), 'stored_alt_text')).toBeNull();
  });

  it('returns null for non-Error values', () => {
    expect(resolveDescribeErrorDataField('not-an-error', 'stored_alt_text')).toBeNull();
    expect(resolveDescribeErrorDataField(null, 'stored_alt_text')).toBeNull();
  });

  it('returns empty string when that is the stored value (legitimate alt)', () => {
    const err = new Error(
      'Request failed (500): {"code":"description_correction_partial","message":"x","data":{"status":500,"stored_alt_text":""}}',
    );
    expect(resolveDescribeErrorDataField(err, 'stored_alt_text')).toBe('');
  });

  it('returns null when the field is present but not a string', () => {
    const err = new Error(
      'Request failed (500): {"code":"description_correction_partial","message":"x","data":{"status":500,"stored_alt_text":42}}',
    );
    expect(resolveDescribeErrorDataField(err, 'stored_alt_text')).toBeNull();
  });
});

describe('resolveDescribeErrorDataBooleanField', () => {
  it('extracts is_decorative boolean from a partial correction rejection body [A-03]', () => {
    const err = new Error(
      'Request to .../correction failed (500): {"code":"description_correction_partial","message":"x","data":{"status":500,"stored_alt_text":"","is_decorative":true}}',
    );
    expect(resolveDescribeErrorDataBooleanField(err, 'is_decorative')).toBe(true);
  });

  it('returns false when is_decorative is false (not null) [A-03]', () => {
    const err = new Error(
      'Request failed (500): {"code":"description_correction_partial","message":"x","data":{"status":500,"stored_alt_text":"Alt","is_decorative":false}}',
    );
    expect(resolveDescribeErrorDataBooleanField(err, 'is_decorative')).toBe(false);
  });

  it('returns null when is_decorative is absent [A-03][rg-015]', () => {
    const err = new Error(
      'Request failed (500): {"code":"description_correction_partial","message":"x","data":{"status":500,"stored_alt_text":""}}',
    );
    expect(resolveDescribeErrorDataBooleanField(err, 'is_decorative')).toBeNull();
  });

  it('returns null when is_decorative is a string "1" rather than a boolean [A-03]', () => {
    const err = new Error(
      'Request failed (500): {"code":"description_correction_partial","message":"x","data":{"status":500,"is_decorative":"1"}}',
    );
    expect(resolveDescribeErrorDataBooleanField(err, 'is_decorative')).toBeNull();
  });
});
