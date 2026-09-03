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
  /** Mint a requestId for one unit of work; module-scope loggers omit it (rg-015). */
  withRequest(): Logger;
}

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

export const redactEndpoint = (endpoint: string): string => {
  try {
    const url = endpoint.includes('://') ? new URL(endpoint) : new URL(endpoint, 'http://localhost');
    return url.pathname;
  } catch {
    return '<redacted>';
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

const omitEmptyRequestId = (fields: LogFields): LogFields => {
  if (fields.requestId !== '') {
    return fields;
  }
  const rest: LogFields = { ...fields };
  delete rest.requestId;
  return rest;
};

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

export const createLogger = (scope: string, fields: LogFields = {}): Logger => {
  const parentFields = omitEmptyRequestId(flattenFields(fields));

  const emit = (level: LogLevel, message: string, callFields?: LogFields): void => {
    if (LOG_LEVEL_ORDER[level] < LOG_LEVEL_ORDER[minLevel]) {
      return;
    }
    const record: LogRecord = {
      ts: Date.now(),
      level,
      scope,
      message,
      fields: omitEmptyRequestId(flattenFields({ ...parentFields, ...callFields })),
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
    withRequest: () => createLogger(scope, { ...parentFields, requestId: newRequestId() }),
  };
};

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
