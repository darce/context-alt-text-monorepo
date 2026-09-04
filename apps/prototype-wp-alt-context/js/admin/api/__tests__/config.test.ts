import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { registerConfig, resetConfigCache } from '../config';
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
