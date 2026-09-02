import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  consoleSink,
  createLogger,
  LOG_LEVEL_ORDER,
  newRequestId,
  setLogLevel,
  setLogSink,
  type LogRecord,
} from '../logger';

describe('createLogger', () => {
  afterEach(() => {
    setLogSink(null);
    setLogLevel(null);
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('capture sink receives records with ts/level/scope/message/fields [OBS-02]', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(1_700_000_000_000));
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });

    const log = createLogger('bootstrap', { requestId: 'req-1' });
    log.warn('Missing WordPress globals', { missing: 'wp' });

    expect(records).toHaveLength(1);
    const rec = records[0];
    expect(rec.ts).toBe(1_700_000_000_000);
    expect(rec.level).toBe('warn');
    expect(rec.scope).toBe('bootstrap');
    expect(rec.message).toBe('Missing WordPress globals');
    expect(rec.fields).toEqual({ requestId: 'req-1', missing: 'wp' });
  });

  it('child merges fields and child fields win over parent [OBS-03]', () => {
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });

    const parent = createLogger('jobPersistence', { jobId: 'parent-job', requestId: 'req-1' });
    const child = parent.child({ jobId: 'child-job', extra: 1 });
    child.info('job updated');

    expect(records).toHaveLength(1);
    expect(records[0].scope).toBe('jobPersistence');
    expect(records[0].fields).toEqual({
      jobId: 'child-job',
      requestId: 'req-1',
      extra: 1,
    });
  });

  it('consoleSink maps each level to the matching console method and omits fields when empty', () => {
    const debug = vi.spyOn(console, 'debug').mockImplementation(() => undefined);
    const info = vi.spyOn(console, 'info').mockImplementation(() => undefined);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const empty = { ts: 1, scope: 's', message: 'm', fields: {} };
    consoleSink({ ...empty, level: 'debug' });
    consoleSink({ ...empty, level: 'info' });
    consoleSink({ ...empty, level: 'warn' });
    consoleSink({ ...empty, level: 'error' });

    expect(debug).toHaveBeenCalledWith('[alt-context/s] m');
    expect(debug.mock.calls[0]).toHaveLength(1);
    expect(info).toHaveBeenCalledWith('[alt-context/s] m');
    expect(info.mock.calls[0]).toHaveLength(1);
    expect(warn).toHaveBeenCalledWith('[alt-context/s] m');
    expect(warn.mock.calls[0]).toHaveLength(1);
    expect(error).toHaveBeenCalledWith('[alt-context/s] m');
    expect(error.mock.calls[0]).toHaveLength(1);

    consoleSink({ ts: 1, level: 'info', scope: 's', message: 'm', fields: { jobId: 'j1' } });
    expect(info).toHaveBeenCalledWith('[alt-context/s] m', { jobId: 'j1' });
  });

  it('Error field values are flattened to { name, message }', () => {
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });

    const boom = new Error('parse failed');
    boom.name = 'SyntaxError';
    createLogger('jobPersistence').error('Failed to parse persisted jobs', { error: boom });

    expect(records[0].fields.error).toEqual({ name: 'SyntaxError', message: 'parse failed' });
    expect(JSON.stringify(records[0].fields.error)).not.toContain('stack');
  });

  it('flattens Error cause one level without stack', () => {
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });

    const outer = new Error('outer', { cause: new TypeError('inner') });
    createLogger('x').error('failed', { error: outer });

    expect(records[0].fields.error).toEqual({
      name: 'Error',
      message: 'outer',
      cause: { name: 'TypeError', message: 'inner' },
    });
    expect(JSON.stringify(records[0].fields.error)).not.toContain('stack');

    const withPrimitive = new Error('outer2', { cause: 42 });
    createLogger('x').error('failed2', { error: withPrimitive });
    expect(records[1].fields.error).toEqual({
      name: 'Error',
      message: 'outer2',
      cause: 42,
    });
  });

  it('drops records below minLevel before they reach the sink', () => {
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });
    setLogLevel('warn');

    const log = createLogger('x');
    log.debug('d');
    log.info('i');
    log.warn('w');
    log.error('e');

    expect(LOG_LEVEL_ORDER.debug).toBeLessThan(LOG_LEVEL_ORDER.warn);
    expect(records.map((record) => record.level)).toEqual(['warn', 'error']);
    expect(records.map((record) => record.message)).toEqual(['w', 'e']);
  });

  it('setLogLevel(null) restores the environment default minLevel', () => {
    const records: LogRecord[] = [];
    setLogSink((record) => {
      records.push(record);
    });
    setLogLevel('error');
    createLogger('x').debug('hidden');
    expect(records).toHaveLength(0);

    setLogLevel(null);
    createLogger('x').debug('visible');
    expect(records).toHaveLength(1);
    expect(records[0].message).toBe('visible');
  });

  it('sink throwing does not propagate', () => {
    setLogSink(() => {
      throw new Error('sink down');
    });
    expect(() => createLogger('x').error('boom')).not.toThrow();
  });

  it('newRequestId returns distinct non-empty strings [OBS-03]', () => {
    const a = newRequestId();
    const b = newRequestId();
    expect(a.length).toBeGreaterThan(0);
    expect(b.length).toBeGreaterThan(0);
    expect(a).not.toBe(b);
  });

  it('newRequestId falls back to req-<base36 time>-<random> when crypto.randomUUID is missing', () => {
    const cryptoObj = globalThis.crypto;
    const original = cryptoObj.randomUUID.bind(cryptoObj);
    // Capability guard: frontend guideline 11.
    Object.defineProperty(cryptoObj, 'randomUUID', {
      configurable: true,
      value: undefined,
    });
    try {
      const id = newRequestId();
      expect(id).toMatch(/^req-[0-9a-z]+-[0-9a-z]+$/);
    } finally {
      Object.defineProperty(cryptoObj, 'randomUUID', {
        configurable: true,
        value: original,
      });
    }
  });

  it('setLogSink(null) restores the default console sink', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    setLogSink(() => undefined);
    createLogger('x').warn('hidden');
    expect(warn).not.toHaveBeenCalled();

    setLogSink(null);
    createLogger('x').warn('visible');
    expect(warn).toHaveBeenCalledWith('[alt-context/x] visible');
  });
});
