import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import { fetchWorkbenchMediaDetail } from '../workbenchMediaApi';

const mockConfig = {
  nonce: 'nonce-123',
};

vi.mock('../config', () => ({
  getEndpoint: vi.fn((key: string) => `https://example.com/${key}`),
  getConfig: vi.fn(() => mockConfig),
}));

vi.mock('../recognition/requestTimeout', () => ({
  createRecognitionTimeoutSignal: vi.fn(() => undefined),
}));

vi.mock('../../utils/http', () => {
  const requestMock = vi.fn();
  return {
    fetchRequiredApi: requestMock,
  };
});

describe('workbenchMediaApi', () => {
  const fetchApiMock = vi.mocked(httpModule.fetchRequiredApi);

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('normalizes media-detail truncation metadata', async () => {
    fetchApiMock.mockResolvedValue({
      details_by_media: { '11': { id: 11 } },
      limit: 100,
      total: 101,
      truncated: true,
    });

    const result = await fetchWorkbenchMediaDetail([11, 12]);

    expect(result.limit).toBe(100);
    expect(result.total).toBe(101);
    expect(result.truncated).toBe(true);
    expect(result.detailsByMedia).toEqual({ '11': { id: 11 } });
  });

  it('rejects media-detail payloads that omit truncation metadata', async () => {
    fetchApiMock.mockResolvedValue({ details_by_media: {} });

    await expect(fetchWorkbenchMediaDetail([11])).rejects.toThrow(
      'Workbench media detail response was malformed.',
    );
  });
});