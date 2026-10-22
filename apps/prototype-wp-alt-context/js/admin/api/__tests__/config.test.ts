import { afterEach, beforeEach, describe, expect, expectTypeOf, it } from 'vitest';

import { getConfig, registerConfig, resetConfigCache, type ApiConfig, type NormalizedConfig } from '../config';
import { setLogSink, type LogRecord } from '../../utils/logger';

/**
 * OBS-03 (correlation id on every line): a module-scope logger is not a unit of
 * work. Soft config-degradation warnings must correlate per normalization pass,
 * so a grep on one requestId reconstructs exactly one config load.
 */
describe('config soft-warning correlation [OBS-03]', () => {
  let records: LogRecord[] = [];

  beforeEach(() => {
    records = [];
    resetConfigCache();
    setLogSink((record) => {
      records.push(record);
    });
  });

  afterEach(() => {
    setLogSink(null);
    resetConfigCache();
  });

  it('groups every soft warning from one normalization under a single requestId', () => {
    registerConfig({ nonce: '', ajaxUrl: '', endpoints: {} });

    expect(records).toHaveLength(2);
    const ids = new Set(records.map((record) => record.fields.requestId));
    expect(ids.size).toBe(1);
    const [requestId] = [...ids];
    expect(typeof requestId).toBe('string');
    expect(requestId).not.toBe('');
    for (const record of records) {
      expect(record.level).toBe('warn');
      expect(record.scope).toBe('api.config');
    }
  });

  it('mints a distinct requestId per normalization pass', () => {
    registerConfig({ nonce: 'abc', ajaxUrl: '', endpoints: {} });
    resetConfigCache();
    registerConfig({ nonce: 'abc', ajaxUrl: '', endpoints: {} });

    const ids = records.map((record) => record.fields.requestId);
    expect(ids).toHaveLength(2);
    expect(ids[0]).not.toBe(ids[1]);
  });
});

/**
 * WBRC-1: Admin::localize_spa_config publishes a nested
 * `recognitionPolicy: { enabled, canManage }`. Nesting keeps wp_localize_script
 * from string-casting the booleans, so only literal booleans are valid. Anything
 * else is unknown (null): never silently Off, and never a capability grant.
 */
describe('recognition policy bootstrap [WBRC-1]', () => {
  const VALID: ApiConfig = { nonce: 'abcdef1234', ajaxUrl: '/wp-admin/admin-ajax.php', endpoints: {} };
  const UNKNOWN = { enabled: null, canManage: null };
  let records: LogRecord[] = [];

  /**
   * window.AltContextAdmin is untrusted page data (cached HTML can predate or
   * mangle the field). A malformed payload therefore crosses the boundary as
   * `unknown`, the way the real global does; the production type stays exact.
   */
  const untrustedBootstrap = (recognitionPolicy: unknown): ApiConfig => {
    const raw: unknown = { ...VALID, recognitionPolicy };
    return raw as ApiConfig;
  };

  beforeEach(() => {
    records = [];
    resetConfigCache();
    setLogSink((record) => {
      records.push(record);
    });
  });

  afterEach(() => {
    setLogSink(null);
    resetConfigCache();
    delete window.AltContextAdmin;
  });

  it('pins the normalized shape to nullable booleans', () => {
    expectTypeOf<NormalizedConfig['recognitionPolicy']>().toEqualTypeOf<{
      enabled: boolean | null;
      canManage: boolean | null;
    }>();
  });

  it.each([
    [true, true],
    [true, false],
    [false, true],
    [false, false],
  ])('preserves the producer literals enabled=%s canManage=%s independently', (enabled, canManage) => {
    const config = registerConfig({ ...VALID, recognitionPolicy: { enabled, canManage } });

    expect(config.recognitionPolicy).toEqual({ enabled, canManage });
    expect(records).toEqual([]);
  });

  it('keeps an older bootstrap without the field unknown, without warning', () => {
    expect(registerConfig(VALID).recognitionPolicy).toEqual(UNKNOWN);
    expect(records).toEqual([]);
  });

  it.each([
    ['null', null],
    ['a bare boolean', true],
    ['a string', 'false'],
    ['an empty object', {}],
    ['an array', [true, true]],
    ['string booleans', { enabled: 'false', canManage: 'true' }],
    ['wp_localize_script-style strings', { enabled: '1', canManage: '' }],
    ['numbers', { enabled: 1, canManage: 0 }],
    ['nulls', { enabled: null, canManage: null }],
  ])('keeps %s unknown and warns once for the pass', (_label, recognitionPolicy) => {
    const config = registerConfig(untrustedBootstrap(recognitionPolicy));

    expect(config.recognitionPolicy).toEqual(UNKNOWN);
    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({
      level: 'warn',
      scope: 'api.config',
      fields: { field: 'recognitionPolicy' },
    });
    expect(records[0]?.fields.requestId).toEqual(expect.any(String));
  });

  it('judges each field alone: a valid state survives, a malformed capability is never granted', () => {
    const config = registerConfig(untrustedBootstrap({ enabled: true, canManage: 'yes' }));

    expect(config.recognitionPolicy).toEqual({ enabled: true, canManage: null });
  });

  it('never turns a malformed state into Off, even beside a valid capability', () => {
    const config = registerConfig(untrustedBootstrap({ enabled: 'off', canManage: true }));

    expect(config.recognitionPolicy).toEqual({ enabled: null, canManage: true });
  });

  it('normalizes the window.AltContextAdmin global the SPA actually reads', () => {
    window.AltContextAdmin = untrustedBootstrap({ enabled: false, canManage: 'true' });

    expect(getConfig().recognitionPolicy).toEqual({ enabled: false, canManage: null });
  });
});
