import { classifyError, isAppError, type AppError } from './appError';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

export const LOG_LEVEL_ORDER = { debug: 0, info: 1, warn: 2, error: 3 } as const;

export interface LogFields {
  jobId?: string;
  requestId?: string;
  [key: string]: unknown;
}

export interface LogRecord {
  ts: number;
  level: LogLevel;
  scope: string;
  message: string;
  fields: LogFields;
}

export type LogSink = (record: LogRecord) => void;

export interface Logger {
  debug(message: string, fields?: LogFields): void;
  info(message: string, fields?: LogFields): void;
  warn(message: string, fields?: LogFields): void;
  error(message: string, fields?: LogFields): void;
  child(fields: LogFields): Logger;
}

/**
 * The job's *state*, as `logJobEvent` projects it onto a record. Deliberately
 * CLOSED, and deliberately narrow: it holds what is true of the job at the
 * moment of the event, not what is true of one observation of it.
 *
 * Per-event dimensions — stream `durationMs`, `reconnectAttempts`, retry
 * counters, anything that measures *this* attempt rather than the job — do NOT
 * belong here. They ride on a child logger:
 *
 * ```ts
 * logJobEvent(jobLog.child({ durationMs, reconnectAttempts }), event, state);
 * ```
 *
 * `child()` fields are merged into `LogRecord.fields` by `emit`, so the emitted
 * record is still one wide event carrying every dimension (OBS-02,
 * lexicons/engineering.md:472) and a post-mortem greps one line, not two.
 * Widening this interface instead would give the same field two owners — the
 * caller could set it either way and the two could disagree (REF-19 no
 * information leakage, lexicons/engineering.md:338) — and would add optional
 * members with zero call sites inside this module (REF-12 YAGNI,
 * lexicons/engineering.md:331). Recorded for FEBT2-LB-NEW-04, where lane B hit
 * this seam and correctly used `child()`; the contract is now written down and
 * pinned by a test rather than rediscovered.
 */
export interface JobLogStateSummary {
  readonly status: string;
  readonly jobId?: string | null;
  readonly done?: number;
  readonly total?: number;
  readonly failedCount?: number;
}

const CONSOLE_METHODS: Record<LogLevel, 'debug' | 'info' | 'warn' | 'error'> = {
  debug: 'debug',
  info: 'info',
  warn: 'warn',
  error: 'error',
};

const defaultMinLevel = (): LogLevel => (import.meta.env.PROD ? 'info' : 'debug');

let minLevel: LogLevel = defaultMinLevel();

export const setLogLevel = (level: LogLevel | null): void => {
  minLevel = level ?? defaultMinLevel();
};

interface FlattenedError {
  name: string;
  message: string;
  status?: number;
  endpoint?: string;
  cause?: unknown;
}

/** Stand-in emitted for any path segment that is not provably a route literal (REF-33). */
export const REDACTED_SEGMENT = '<redacted>';

/**
 * Segments that provably cannot carry entropy: lowercase word(s) joined by
 * hyphens, or an API version token (`v1`). A uuid, numeric id, hex digest,
 * base64 token, or nonce cannot match this, so it can never be emitted.
 */
const SAFE_PATH_SEGMENT = /^(?:[a-z]+(?:-[a-z]+)*|v[0-9]+)$/;

/** Upper bound so a long word-shaped token cannot ride through the allowlist. */
const MAX_SAFE_SEGMENT_LENGTH = 32;

const redactPathSegment = (segment: string): string => {
  if (segment === '') {
    return segment;
  }
  if (segment.length <= MAX_SAFE_SEGMENT_LENGTH && SAFE_PATH_SEGMENT.test(segment)) {
    return segment;
  }
  return REDACTED_SEGMENT;
};

/**
 * Reduce a request endpoint to a route shape safe to write to a log sink
 * (OBS-05 secret hygiene, WEB-44 "a token in a URL is a secret in every log").
 *
 * Fail-closed by construction: origin, query and fragment are dropped outright,
 * and each remaining path segment is emitted ONLY when it matches the route
 * literal allowlist. Everything else — ids, nonces, digests, anything unknown —
 * collapses to `<redacted>`, so `/wp-json/acx/v1/jobs/<uuid>/data` logs as
 * `/wp-json/acx/v1/jobs/<redacted>/data`. The previous implementation returned
 * `url.pathname` verbatim, i.e. it failed OPEN into the sink (FEBT1-LE-01).
 *
 * Single owner for endpoint redaction (REF-19/REF-21: redact inside the logger,
 * not per caller). Callers outside this module import it rather than re-deriving.
 */
export const redactEndpoint = (endpoint: string): string => {
  try {
    const url = endpoint.includes('://') ? new URL(endpoint) : new URL(endpoint, 'http://localhost');
    return url.pathname.split('/').map(redactPathSegment).join('/');
  } catch {
    return REDACTED_SEGMENT;
  }
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const safeAppErrorMessage = (error: AppError): string => {
  switch (error._tag) {
    case 'http':
      return `HTTP ${error.status}`;
    case 'parse':
      return 'JSON parse error';
    case 'nonce_refresh':
      return 'Nonce refresh failed';
    case 'auth_expired':
    case 'abort':
    case 'timeout':
    case 'transport':
    case 'unknown':
      return error.message;
    default: {
      const exhaustive: never = error;
      return exhaustive;
    }
  }
};

const projectAppError = (error: AppError): Record<string, unknown> => {
  const projected: Record<string, unknown> = {
    tag: error._tag,
    message: safeAppErrorMessage(error),
  };
  if ('status' in error) {
    projected.status = error.status;
  }
  if ('endpoint' in error) {
    projected.endpoint = redactEndpoint(error.endpoint);
  }
  return projected;
};

const projectBoundaryError = (value: Error): FlattenedError | null => {
  const classified = classifyError(value);
  if (classified._tag !== 'http' && classified._tag !== 'parse' && classified._tag !== 'nonce_refresh') {
    return null;
  }
  const projected = projectAppError(classified);
  const flattened: FlattenedError = {
    name: value.name,
    message: typeof projected.message === 'string' ? projected.message : safeAppErrorMessage(classified),
  };
  if (typeof projected.status === 'number') {
    flattened.status = projected.status;
  }
  if (typeof projected.endpoint === 'string') {
    flattened.endpoint = projected.endpoint;
  }
  // parse AppError has no status; keep ResponseParseError.status via classified.cause.
  if (classified._tag === 'parse' && flattened.status === undefined && isRecord(classified.cause)) {
    const status = classified.cause.status;
    if (typeof status === 'number') {
      flattened.status = status;
    }
  }
  return flattened;
};

const flattenCause = (cause: unknown): unknown => {
  // Error instances are checked FIRST: a tagged Error subclass must keep the
  // {name, message, ...} record shape, never flip to the plain {tag, ...}
  // projection reserved for classified AppError values (FEBT1G-M-07/M-10).
  if (cause instanceof Error) {
    return flattenError(cause, false);
  }
  if (isAppError(cause)) {
    return projectAppError(cause);
  }
  if (cause === null || typeof cause !== 'object') {
    return cause;
  }
  if (Object.getPrototypeOf(cause) === Object.prototype || Object.getPrototypeOf(cause) === null) {
    return cause;
  }
  return { name: 'opaque' };
};

const flattenError = (value: Error, includeCause: boolean): FlattenedError => {
  const flattened: FlattenedError = projectBoundaryError(value) ?? {
    name: value.name,
    message: value.message,
  };
  if (includeCause && value.cause !== undefined) {
    flattened.cause = flattenCause(value.cause);
  }
  return flattened;
};

const flattenFieldValue = (value: unknown): unknown => {
  // Error-instance check first — see flattenCause (FEBT1G-M-07/M-10).
  if (value instanceof Error) {
    return flattenError(value, true);
  }
  if (isAppError(value)) {
    return projectAppError(value);
  }
  return value;
};

const flattenFields = (fields: LogFields): LogFields => {
  const flattened: LogFields = {};
  for (const [key, value] of Object.entries(fields)) {
    flattened[key] = flattenFieldValue(value);
  }
  return flattened;
};

const isNonEmptyFields = (fields: LogFields): boolean => Object.keys(fields).length > 0;

export const consoleSink: LogSink = (record) => {
  const prefix = `[alt-context/${record.scope}] ${record.message}`;
  const fields = flattenFields(record.fields);
  if (isNonEmptyFields(fields)) {
    console[CONSOLE_METHODS[record.level]](prefix, fields);
    return;
  }
  console[CONSOLE_METHODS[record.level]](prefix);
};

let activeSink: LogSink = consoleSink;

export const setLogSink = (sink: LogSink | null): void => {
  activeSink = sink ?? consoleSink;
};

export const newRequestId = (): string => {
  const cryptoObj = globalThis.crypto;
  if (typeof cryptoObj?.randomUUID === 'function') {
    return cryptoObj.randomUUID();
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
};

/**
 * Create a logger for a module scope.
 *
 * OBS-03: a logger scope is NOT a transaction, so `createLogger` does NOT mint a
 * `requestId`. Minting one here would put an import-time uuid on every line of a
 * module-scope logger — a grep key that correlates "which module" (already carried
 * by `scope`) and not "which unit of work", while looking indistinguishable from a
 * real one (FEBT1-W2B-01). `requestId` is therefore present on a record if and only
 * if a unit of work was opened with `withRequestId`; its absence is readable signal.
 */
export const createLogger = (scope: string, fields: LogFields = {}): Logger => {
  const parentFields = flattenFields(fields);

  const emit = (level: LogLevel, message: string, callFields?: LogFields): void => {
    if (LOG_LEVEL_ORDER[level] < LOG_LEVEL_ORDER[minLevel]) {
      return;
    }
    const record: LogRecord = {
      ts: Date.now(),
      level,
      scope,
      message,
      fields: flattenFields({ ...parentFields, ...callFields }),
    };
    try {
      activeSink(record);
    } catch {
      // Logging must never throw (OBS-02).
    }
  };

  return {
    debug: (message, callFields) => emit('debug', message, callFields),
    info: (message, callFields) => emit('info', message, callFields),
    warn: (message, callFields) => emit('warn', message, callFields),
    error: (message, callFields) => emit('error', message, callFields),
    child: (childFields) => createLogger(scope, { ...parentFields, ...childFields }),
  };
};

/**
 * Open a unit of work: returns a child logger whose `requestId` correlates every
 * record emitted for that one action, including records from further `child()`
 * calls (FEBT1-W2B-01, OBS-03). Pass an existing id to join an in-flight
 * transaction so two scopes — e.g. a scan submit and its SSE stream — share one
 * grep key. This is the ONLY seam that mints a correlation id.
 */
export const withRequestId = (log: Logger, requestId: string = newRequestId()): Logger =>
  log.child({ requestId });

/**
 * Job-scoped logger. `jobId` identifies the long-running job, not one user action:
 * wrap with `withRequestId` to correlate a single action against that job.
 */
export const createJobLogger = (scope: string, jobId: string): Logger => createLogger(scope, { jobId });

export const logJobEvent = (
  log: Logger,
  event: string | { readonly type: string },
  state: JobLogStateSummary,
): void => {
  const eventName = typeof event === 'string' ? event : event.type;
  const fields: LogFields = {
    event: eventName,
    status: state.status,
  };
  if (state.jobId) {
    fields.jobId = state.jobId;
  }
  if (state.done !== undefined) {
    fields.done = state.done;
  }
  if (state.total !== undefined) {
    fields.total = state.total;
  }
  if (state.failedCount !== undefined) {
    fields.failedCount = state.failedCount;
  }
  log.info(eventName, fields);
};
