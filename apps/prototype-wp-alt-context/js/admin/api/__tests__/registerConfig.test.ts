import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import {
  getConfig,
  getEndpoint,
  registerConfig,
  resetConfigCache,
} from '../config';
import { fetchMediaIdentities } from '../recognition/identityQueriesApi';

vi.mock('../../utils/http', () => {
  const requestMock = vi.fn();
  return {
    fetchApi: requestMock,
    fetchRequiredApi: requestMock,
    stripTrailingSlash: (value: string) => (value.endsWith('/') ? value.slice(0, -1) : value),
  };
});

describe('registerConfig seam (UXP-5 slice 3)', () => {
  const fetchApiMock = vi.mocked(httpModule.fetchRequiredApi);

  beforeEach(() => {
    vi.clearAllMocks();
    resetConfigCache();
    delete window.AltContextAdmin;
  });

  afterEach(() => {
    resetConfigCache();
    delete window.AltContextAdmin;
  });

  it('lets fetchMediaIdentities resolve endpoint + nonce with no AltContextAdmin global', async () => {
    registerConfig({
      nonce: 'attachment-edit-nonce',
      endpoints: {
        recognitionMediaIdentities: 'https://example.test/wp-json/acx/v1/recognition/media-identities',
      },
    });

    expect(window.AltContextAdmin).toBeUndefined();
    expect(getConfig().nonce).toBe('attachment-edit-nonce');
    expect(getEndpoint('recognitionMediaIdentities')).toBe(
      'https://example.test/wp-json/acx/v1/recognition/media-identities',
    );

    fetchApiMock.mockResolvedValue({
      identities_by_media: {},
      data_source: 'local_projection',
    });

    await fetchMediaIdentities([42]);

    expect(fetchApiMock).toHaveBeenCalledTimes(1);
    expect(fetchApiMock).toHaveBeenCalledWith(
      expect.stringContaining('media_ids'),
      expect.objectContaining({
        method: 'GET',
        restNonce: 'attachment-edit-nonce',
      }),
    );
  });

  it('throws the SPA missing-config error when registerConfig is skipped [TEST-15]', () => {
    expect(window.AltContextAdmin).toBeUndefined();
    expect(() => getConfig()).toThrow('AltContextAdmin configuration is missing.');
  });

  it('SPA path still reads window.AltContextAdmin when nothing is registered', () => {
    window.AltContextAdmin = {
      nonce: 'spa-nonce',
      endpoints: {
        recognitionMediaIdentities: 'https://example.test/spa-identities',
      },
    };

    expect(getConfig().nonce).toBe('spa-nonce');
    expect(getEndpoint('recognitionMediaIdentities')).toBe('https://example.test/spa-identities');
  });
});
