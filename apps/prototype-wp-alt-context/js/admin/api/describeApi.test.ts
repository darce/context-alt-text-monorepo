import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../utils/http';
import { fetchDescribeRunItems, MalformedDescribeRunResponseError } from './describeApi';

const endpoint = 'https://example.com/acx/v1/recognition/describe/runs/run-abc/items';

vi.mock('./config', () => ({
  getEndpoint: vi.fn(() => 'https://example.com/acx/v1/recognition/describe/runs'),
  getConfig: vi.fn(() => ({ nonce: 'nonce-xyz' })),
}));

vi.mock('./recognition/requestTimeout', () => ({
  createRecognitionTimeoutSignal: vi.fn(() => undefined),
}));

vi.mock('../utils/http', () => ({
  fetchRequiredApi: vi.fn(),
}));

const fetchApiMock = vi.mocked(httpModule.fetchRequiredApi);

const validItem = {
  media_id: 70,
  status: 'completed',
  alt_text_draft: 'A described bridge.',
  caption: 'A bridge.',
  provenance: null,
  tier: 'final_gpu',
  result_generation: 1,
  existing_alt: false,
};

describe('fetchDescribeRunItems response boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('rejects a response with no items field using the endpoint and field', async () => {
    fetchApiMock.mockResolvedValue({ run_id: 'run-abc' });

    await expect(fetchDescribeRunItems('run-abc')).rejects.toThrow(
      new MalformedDescribeRunResponseError(`${endpoint} response.items`),
    );
  });

  it('rejects a response whose items field is not an array', async () => {
    fetchApiMock.mockResolvedValue({ run_id: 'run-abc', items: null });

    await expect(fetchDescribeRunItems('run-abc')).rejects.toThrow(
      new MalformedDescribeRunResponseError(`${endpoint} response.items`),
    );
  });

  it('rejects an item missing a required mapper field instead of throwing a TypeError', async () => {
    const incompleteItem: Record<string, unknown> = { ...validItem };
    delete incompleteItem.provenance;
    fetchApiMock.mockResolvedValue({ run_id: 'run-abc', items: [incompleteItem] });

    await expect(fetchDescribeRunItems('run-abc')).rejects.toThrow(
      new MalformedDescribeRunResponseError(`${endpoint} response.items[0].provenance`),
    );
  });
});
