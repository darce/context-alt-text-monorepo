import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import { fetchWorkbenchMediaDetail } from '../workbenchMediaApi';

const mockConfig = {
  nonce: 'nonce-123',
  endpoints: {
    workbenchMediaDetail: 'https://example.com/workbench/media/detail',
  } as Record<string, string>,
};

vi.mock('../config', () => ({
  getEndpoint: vi.fn((...keys: string[]) => {
    const configuredKey = keys.find((key) => mockConfig.endpoints[key]);
    return configuredKey ? mockConfig.endpoints[configuredKey] : `https://example.com/${keys[0] ?? 'default'}`;
  }),
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

  it('rejects workbench media detail payloads without envelope metadata', async () => {
    fetchApiMock.mockResolvedValue({
      details_by_media: {
        '11': {
          id: 11,
          mimeType: 'image/jpeg',
          updatedAt: '2026-04-29T00:00:00Z',
          dimensions: { width: 1200, height: 800 },
          xmpPersistence: null,
        },
      },
    });

    await expect(fetchWorkbenchMediaDetail([11])).rejects.toThrow('Workbench media detail response was malformed.');
  });

  it('rejects workbench media detail payloads with null details_by_media', async () => {
    fetchApiMock.mockResolvedValue({
      details_by_media: null,
      limit: 100,
      total: 0,
      truncated: false,
    });

    await expect(fetchWorkbenchMediaDetail([11])).rejects.toThrow('Workbench media detail response was malformed.');
  });

  it('returns envelope metadata for valid workbench media detail payloads', async () => {
    fetchApiMock.mockResolvedValue({
      details_by_media: {
        '11': {
          id: 11,
          mimeType: 'image/jpeg',
          updatedAt: '2026-04-29T00:00:00Z',
          dimensions: { width: 1200, height: 800 },
          xmpPersistence: null,
        },
      },
      limit: 100,
      total: 1,
      truncated: false,
    });

    await expect(fetchWorkbenchMediaDetail([11])).resolves.toEqual({
      detailsByMedia: {
        '11': {
          id: 11,
          mimeType: 'image/jpeg',
          updatedAt: '2026-04-29T00:00:00Z',
          dimensions: { width: 1200, height: 800 },
          xmpPersistence: null,
        },
      },
      limit: 100,
      total: 1,
      truncated: false,
    });
  });
});
