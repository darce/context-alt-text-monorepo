import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as httpModule from '../../utils/http';
import { createLogger, setLogSink, type LogRecord } from '../../utils/logger';
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
    setLogSink(null);
  });

  it('lets fetchMediaIdentities resolve endpoint + nonce with no AltContextAdmin global', async () => {
    registerConfig({
      nonce: 'attachment-edit-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
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

  it('missing nonce/ajaxUrl warn through a scoped logger, not console.warn [O-06][W2-L5]', () => {
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    registerConfig({
      nonce: '',
      ajaxUrl: '   ',
      endpoints: {},
    });

    const messages = records.map((record) => record.message);
    expect(messages).toContain(
      'AltContextAdmin configuration field "nonce" is missing or empty; dependent features degrade.',
    );
    expect(messages).toContain(
      'AltContextAdmin configuration field "ajaxUrl" is missing or empty; dependent features degrade.',
    );
    expect(records.every((record) => record.level === 'warn' && record.scope === 'api.config')).toBe(true);
    expect(warn).not.toHaveBeenCalled();
    expect(getConfig().nonce).toBe('');
    expect(getConfig().ajaxUrl).toBe('');
    // Keep createLogger reachable so a missing import fails this test, not typecheck.
    expect(typeof createLogger).toBe('function');
  });

  it('SPA path still reads window.AltContextAdmin when nothing is registered', () => {
    window.AltContextAdmin = {
      nonce: 'spa-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        recognitionMediaIdentities: 'https://example.test/spa-identities',
      },
    };

    expect(getConfig().nonce).toBe('spa-nonce');
    expect(getEndpoint('recognitionMediaIdentities')).toBe('https://example.test/spa-identities');
  });
});
