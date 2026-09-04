import { afterEach, describe, expect, it, vi } from 'vitest';

import { NonceRefreshFailedError } from '../../api/config';
import { classifyError, isAppError } from '../appError';
import { HTTPError, ResponseParseError } from '../http';
import {
  consoleSink,
  createJobLogger,
  createLogger,
  logJobEvent,
  LOG_LEVEL_ORDER,
  newRequestId,
  redactEndpoint,
  REDACTED_SEGMENT,
  setLogLevel,
  setLogSink,
  withRequestId,
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
    withRequestId(createLogger('x')).warn('visible');
    expect(warn).toHaveBeenCalledTimes(1);
    const [prefix, fields] = warn.mock.calls[0] as [string, Record<string, unknown>];
    expect(prefix).toBe('[alt-context/x] visible');
    expect(typeof fields.requestId).toBe('string');
    expect(fields.requestId).not.toBe('');
  });
});

const BODY_SECRET = 'SECRET_BODY_LEAK_XYZ_42';
const ENDPOINT_SECRET = 'SECRET_QUERY_TOKEN_XYZ_42';
const PREVIEW_SECRET = 'SECRET_BODY_PREVIEW_XYZ_42';

const leakingHttpError = (): HTTPError =>
  new HTTPError({
    status: 500,
    retryAfterSeconds: undefined,
    endpoint: `http://example.test/jobs?token=${ENDPOINT_SECRET}`,
    bodyPreview: PREVIEW_SECRET,
    message: `Request to http://example.test/jobs failed (500): ${BODY_SECRET}`,
  });

const captureRecords = (): LogRecord[] => {
  const records: LogRecord[] = [];
  setLogSink((record) => {
    records.push(record);
  });
  return records;
};

const PATH_SECRET = 'SECRET_PATH_TOKEN_XYZ_42';

describe('redactEndpoint fails closed [O-03][OBS-05][WEB-44][FEBT1-LE-01]', () => {
  it('keeps route literals and the api version token', () => {
    expect(redactEndpoint('/wp-json/acx/v1/recognition/clusters')).toBe(
      '/wp-json/acx/v1/recognition/clusters',
    );
    expect(redactEndpoint('/wp-json/acx/v1/identity-clusters')).toBe('/wp-json/acx/v1/identity-clusters');
  });

  it('collapses a secret carried in a PATH segment, not only in the query string', () => {
    expect(redactEndpoint(`/wp-json/acx/v1/jobs/${PATH_SECRET}/data`)).toBe(
      `/wp-json/acx/v1/jobs/${REDACTED_SEGMENT}/data`,
    );
    expect(redactEndpoint(`/wp-json/acx/v1/jobs/${PATH_SECRET}/data`)).not.toContain(PATH_SECRET);
  });

  it.each([
    ['uuid', '/jobs/f47ac10b-58cc-4372-a567-0e02b2c3d479/data', `/jobs/${REDACTED_SEGMENT}/data`],
    ['numeric id', '/media/12345', `/media/${REDACTED_SEGMENT}`],
    ['hex digest', '/media/deadbeefcafe1234', `/media/${REDACTED_SEGMENT}`],
    ['mixed alnum nonce', '/media/ab12cd34', `/media/${REDACTED_SEGMENT}`],
    ['uppercase token', '/media/ABCDEF', `/media/${REDACTED_SEGMENT}`],
    ['underscore token', '/media/some_token', `/media/${REDACTED_SEGMENT}`],
    ['overlong word token', `/media/${'a'.repeat(33)}`, `/media/${REDACTED_SEGMENT}`],
  ])('collapses an unknown %s segment', (_label, endpoint, expected) => {
    expect(redactEndpoint(endpoint)).toBe(expected);
  });

  it('drops origin, query and fragment entirely', () => {
    expect(redactEndpoint(`https://example.test/jobs?token=${ENDPOINT_SECRET}#${PATH_SECRET}`)).toBe('/jobs');
  });

  it('returns the stand-in when the endpoint cannot be parsed at all', () => {
    expect(redactEndpoint('http://%%%')).toBe(REDACTED_SEGMENT);
  });

  it('a path-segment secret never reaches the sink through a logged AppError [O-03]', () => {
    const records = captureRecords();
    createLogger('http').error('request failed', {
      error: new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: `http://example.test/jobs/${PATH_SECRET}/data`,
        bodyPreview: PREVIEW_SECRET,
        message: `Request to http://example.test/jobs/${PATH_SECRET}/data failed (500)`,
      }),
    });

    expect(JSON.stringify(records[0])).not.toContain(PATH_SECRET);
    expect((records[0].fields.error as { endpoint?: string }).endpoint).toBe(
      `/jobs/${REDACTED_SEGMENT}/data`,
    );
    setLogSink(null);
  });
});

describe('correlation id binding [O-01]', () => {
  afterEach(() => {
    setLogSink(null);
    setLogLevel(null);
  });

  it('a unit of work propagates one requestId to every level [O-01][OBS-03][FEBT1-W2B-01]', () => {
    const records = captureRecords();
    const log = withRequestId(createLogger('bootstrap'));
    log.debug('d');
    log.info('i');
    log.warn('w');
    log.error('e');

    expect(records).toHaveLength(4);
    const requestId = records[0].fields.requestId;
    expect(requestId).toEqual(expect.any(String));
    expect(String(requestId).length).toBeGreaterThan(0);
    for (const record of records) {
      expect(record.fields.requestId).toBe(requestId);
    }
  });

  /**
   * Replaces the former 'two loggers receive distinct request ids' assertion,
   * which pinned the FEBT1-W2B-01 defect: an import-time uuid per createLogger
   * meant a scan submit and its SSE stream could never share a grep key. The
   * replacement is strictly stronger — it pins BOTH halves of the contract
   * (correlation is opened explicitly, and once opened it is shareable across
   * scopes) rather than only that two loggers differ.
   */
  it('module loggers carry no requestId; joining one unit of work gives both the same key [O-01][OBS-03][FEBT1-W2B-01]', () => {
    const records = captureRecords();
    const submit = createLogger('a');
    const stream = createLogger('b');
    submit.info('one');
    stream.info('two');

    expect(records).toHaveLength(2);
    expect(records[0].fields).not.toHaveProperty('requestId');
    expect(records[1].fields).not.toHaveProperty('requestId');

    const requestId = newRequestId();
    withRequestId(submit, requestId).info('one');
    withRequestId(stream, requestId).info('two');

    expect(records).toHaveLength(4);
    expect(records[2].fields.requestId).toBe(requestId);
    expect(records[3].fields.requestId).toBe(requestId);
  });

  it('withRequestId opens a unit of work two scopes can share [O-01][OBS-03][FEBT1-W2B-01]', () => {
    const records = captureRecords();
    const requestId = newRequestId();
    withRequestId(createLogger('scanSubmit'), requestId).info('submitted');
    withRequestId(createLogger('scanStream'), requestId).info('streaming');

    expect(records).toHaveLength(2);
    expect(records[0].scope).toBe('scanSubmit');
    expect(records[1].scope).toBe('scanStream');
    expect(records[0].fields.requestId).toBe(requestId);
    expect(records[1].fields.requestId).toBe(requestId);
  });

  it('withRequestId mints a fresh id per unit of work off one module logger [O-01][OBS-03][FEBT1-W2B-01]', () => {
    const records = captureRecords();
    const moduleLog = createLogger('jobPersistence');
    withRequestId(moduleLog).info('action one');
    withRequestId(moduleLog).info('action two');

    expect(records).toHaveLength(2);
    expect(typeof records[0].fields.requestId).toBe('string');
    expect(records[0].fields.requestId).not.toBe(records[1].fields.requestId);
  });

  it('child logger inherits the unit-of-work requestId [O-01][OBS-03]', () => {
    const records = captureRecords();
    const parent = withRequestId(createLogger('jobPersistence'));
    const child = parent.child({ extra: 1 });
    parent.info('parent');
    child.info('child');

    expect(records).toHaveLength(2);
    const requestId = records[0].fields.requestId;
    expect(requestId).toEqual(expect.any(String));
    expect(String(requestId).length).toBeGreaterThan(0);
    expect(records[1].fields.requestId).toBe(requestId);
    expect(records[1].fields.extra).toBe(1);
  });

  it('a child of a logger with no unit of work stays uncorrelated [O-01][OBS-03][FEBT1-W2B-01]', () => {
    const records = captureRecords();
    createLogger('jobPersistence').child({ extra: 1 }).info('child');

    expect(records).toHaveLength(1);
    expect(records[0].fields).not.toHaveProperty('requestId');
    expect(records[0].fields.extra).toBe(1);
  });

  it('createJobLogger carries jobId but not a correlation id [O-01][OBS-03][FEBT1-W2B-01]', () => {
    const records = captureRecords();
    createJobLogger('jobPersistence', 'job-123').info('start');

    expect(records).toHaveLength(1);
    expect(records[0].fields.jobId).toBe('job-123');
    expect(records[0].fields).not.toHaveProperty('requestId');
  });

  it('createJobLogger records jobId and requestId on every line [O-01][OBS-03]', () => {
    const records = captureRecords();
    const log = withRequestId(createJobLogger('jobPersistence', 'job-123'));
    log.info('start');
    log.warn('stall');
    log.error('fail');

    expect(records).toHaveLength(3);
    const requestId = records[0].fields.requestId;
    expect(requestId).toEqual(expect.any(String));
    expect(String(requestId).length).toBeGreaterThan(0);
    for (const record of records) {
      expect(record.fields.jobId).toBe('job-123');
      expect(record.fields.requestId).toBe(requestId);
    }
  });
});

describe('logJobEvent [O-02]', () => {
  afterEach(() => {
    setLogSink(null);
    setLogLevel(null);
  });

  it('emits exactly one wide record with event, state, job id, and request id [O-02][OBS-02]', () => {
    const records = captureRecords();
    const log = withRequestId(createJobLogger('job', 'job-123'));
    logJobEvent(
      log,
      { type: 'PROGRESS' },
      { status: 'running', jobId: 'job-123', done: 3, total: 10, failedCount: 0 },
    );

    expect(records).toHaveLength(1);
    expect(records[0].fields.event).toBe('PROGRESS');
    expect(records[0].fields.status).toBe('running');
    expect(records[0].fields.jobId).toBe('job-123');
    expect(records[0].fields.done).toBe(3);
    expect(records[0].fields.total).toBe(10);
    expect(records[0].fields.failedCount).toBe(0);
    expect(records[0].fields.requestId).toEqual(expect.any(String));
    expect(String(records[0].fields.requestId).length).toBeGreaterThan(0);
  });
});

describe('boundary error redaction [O-03][O-05]', () => {
  afterEach(() => {
    setLogSink(null);
    setLogLevel(null);
  });

  it('characterises exact LogRecord.fields.error for HTTPError, ResponseParseError, and NonceRefreshFailedError [W2-L5][TEST-15]', () => {
    const records = captureRecords();
    const httpError = new HTTPError({
      status: 500,
      retryAfterSeconds: undefined,
      endpoint: `http://example.test/jobs?token=${ENDPOINT_SECRET}`,
      bodyPreview: PREVIEW_SECRET,
      message: `Request to http://example.test/jobs failed (500): ${BODY_SECRET}`,
    });
    const parseError = new ResponseParseError({
      status: 200,
      endpoint: `http://example.test/media?token=${ENDPOINT_SECRET}`,
      bodyPreview: PREVIEW_SECRET,
      message: `Request to http://example.test/media returned malformed JSON (200): ${BODY_SECRET}. Response preview: ${PREVIEW_SECRET}`,
    });
    const nonceError = new NonceRefreshFailedError({
      message: `nonce refresh failed: ${BODY_SECRET}`,
      causeStatus: 403,
      bodyPreview: PREVIEW_SECRET,
    });
    const log = createLogger('http', { requestId: 'req-char' });
    log.error('http', { error: httpError });
    log.error('parse', { error: parseError });
    log.error('nonce', { error: nonceError });

    expect(records).toHaveLength(3);
    expect(records[0].fields.error).toEqual({
      name: 'HTTPError',
      message: 'HTTP 500',
      status: 500,
      endpoint: '/jobs',
    });
    expect(records[1].fields.error).toEqual({
      name: 'ResponseParseError',
      message: 'JSON parse error',
      status: 200,
      endpoint: '/media',
    });
    expect(records[2].fields.error).toEqual({
      name: 'NonceRefreshFailedError',
      message: 'Nonce refresh failed',
    });
  });

  it('a tagged Error subclass keeps the name-shaped record, never the tag projection [FEBT1G-M-07][FEBT1G-M-10]', () => {
    const records = captureRecords();
    // Mutant pin: if flattenFieldValue checks isAppError before instanceof Error,
    // an Error subclass that happens to carry AppError-shaped fields flips the
    // established {name, ...} record shape to {tag, ...}.
    class TaggedBoundaryError extends Error {
      readonly _tag = 'transport';
      constructor() {
        super('socket closed');
        this.name = 'TaggedBoundaryError';
        this.cause = undefined;
      }
    }
    const tagged = new TaggedBoundaryError();
    expect(isAppError(tagged)).toBe(true);

    createLogger('x').error('failed', { error: tagged, cause: tagged });

    expect(records[0].fields.error).toEqual({ name: 'TaggedBoundaryError', message: 'socket closed' });
    expect(records[0].fields.cause).toEqual({ name: 'TaggedBoundaryError', message: 'socket closed' });
  });

  it('does not project boundary errors via instanceof HTTPError|ResponseParseError|NonceRefreshFailedError [W2-L5]', async () => {
    const fs = await import('node:fs/promises');
    const path = await import('node:path');
    const src = await fs.readFile(path.join(process.cwd(), 'js/admin/utils/logger.ts'), 'utf8');
    expect(src).not.toMatch(/instanceof\s+(HTTPError|ResponseParseError|AuthExpiredError|NonceRefreshFailedError)/);
  });

  it('HTTPError message secrets are absent from the serialized record [O-03][REF-19]', () => {
    const records = captureRecords();
    const error = leakingHttpError();
    createLogger('http').error('request failed', { error });

    expect(records).toHaveLength(1);
    const serialized = JSON.stringify(records[0]);
    expect(serialized).not.toContain(BODY_SECRET);
    expect(serialized).not.toContain(ENDPOINT_SECRET);
    expect(serialized).not.toContain(PREVIEW_SECRET);
    expect(serialized).not.toContain(error.message);
    expect(serialized).not.toContain(error.bodyPreview);
    const projected = records[0].fields.error as { name?: string; message?: string; endpoint?: string };
    expect(projected).toEqual(
      expect.objectContaining({
        name: 'HTTPError',
        message: 'HTTP 500',
        status: 500,
      }),
    );
    expect(projected).not.toHaveProperty('bodyPreview');
    if (typeof projected.endpoint === 'string') {
      expect(projected.endpoint).not.toContain(ENDPOINT_SECRET);
      expect(projected.endpoint).not.toContain('?');
    }
    expect(Object.getPrototypeOf(projected)).toBe(Object.prototype);
  });

  it('ResponseParseError and NonceRefreshFailedError omit bodyPreview and raw message [O-03][REF-19]', () => {
    const records = captureRecords();
    const parseError = new ResponseParseError({
      status: 200,
      endpoint: `http://example.test/media?token=${ENDPOINT_SECRET}`,
      bodyPreview: PREVIEW_SECRET,
      message: `Request to http://example.test/media returned malformed JSON (200): ${BODY_SECRET}. Response preview: ${PREVIEW_SECRET}`,
    });
    const nonceError = new NonceRefreshFailedError({
      message: `nonce refresh failed: ${BODY_SECRET}`,
      causeStatus: 403,
      bodyPreview: PREVIEW_SECRET,
    });
    const log = createLogger('http');
    log.error('parse', { error: parseError });
    log.error('nonce', { error: nonceError });

    expect(records).toHaveLength(2);
    const serialized = JSON.stringify(records);
    expect(serialized).not.toContain(BODY_SECRET);
    expect(serialized).not.toContain(ENDPOINT_SECRET);
    expect(serialized).not.toContain(PREVIEW_SECRET);
    expect(records[0].fields.error).not.toHaveProperty('bodyPreview');
    expect(records[1].fields.error).not.toHaveProperty('bodyPreview');
    expect(Object.getPrototypeOf(records[0].fields.error)).toBe(Object.prototype);
    expect(Object.getPrototypeOf(records[1].fields.error)).toBe(Object.prototype);
  });

  it('HTTPError as Error.cause is a plain projection, never the class instance [O-03][REF-19]', () => {
    const records = captureRecords();
    const nested = new Error('wrapper', { cause: leakingHttpError() });
    createLogger('http').error('wrapped', { error: nested });

    const flattened = records[0].fields.error as { cause?: unknown };
    expect(flattened.cause).not.toBeInstanceOf(Error);
    expect(flattened.cause).not.toBeInstanceOf(HTTPError);
    expect(Object.getPrototypeOf(flattened.cause)).toBe(Object.prototype);
    expect(JSON.stringify(records[0])).not.toContain(BODY_SECRET);
  });

  it('plain Error message still round-trips [O-03]', () => {
    const records = captureRecords();
    createLogger('x').error('failed', { error: new Error('parse failed') });
    expect(records[0].fields.error).toEqual({ name: 'Error', message: 'parse failed' });
  });

  it('AppError field values flatten to a tagged safe projection [O-05][REF-19]', () => {
    const records = captureRecords();
    const classified = classifyError(leakingHttpError());
    expect(isAppError(classified)).toBe(true);
    createLogger('http').error('classified', { error: classified });

    expect(records[0].fields.error).toEqual({
      tag: 'http',
      message: 'HTTP 500',
      status: 500,
      endpoint: '/jobs',
    });
    const serialized = JSON.stringify(records[0]);
    expect(serialized).not.toContain(BODY_SECRET);
    expect(serialized).not.toContain(ENDPOINT_SECRET);
    expect(serialized).not.toContain(PREVIEW_SECRET);
    expect(serialized).not.toContain('_tag');
  });
});

describe('flattenError cause recursion [O-07]', () => {
  afterEach(() => {
    setLogSink(null);
    setLogLevel(null);
  });

  it('follows cause only one level in a two-level chain [O-07][TEST-15]', () => {
    const records = captureRecords();
    const leaf = new Error('leaf-secret');
    const mid = new Error('mid', { cause: leaf });
    const outer = new Error('outer', { cause: mid });
    createLogger('x').error('failed', { error: outer });

    expect(records[0].fields.error).toEqual({
      name: 'Error',
      message: 'outer',
      cause: { name: 'Error', message: 'mid' },
    });
    expect(JSON.stringify(records[0].fields.error)).not.toContain('leaf-secret');
    const flattened = records[0].fields.error as { cause?: Record<string, unknown> };
    expect(flattened.cause).toBeDefined();
    expect(flattened.cause).not.toBeNull();
    expect(Object.hasOwn(flattened.cause ?? {}, 'cause')).toBe(false);
  });
});
