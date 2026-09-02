export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

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

const CONSOLE_METHODS: Record<LogLevel, 'debug' | 'info' | 'warn' | 'error'> = {
  debug: 'debug',
  info: 'info',
  warn: 'warn',
  error: 'error',
};

const flattenFieldValue = (value: unknown): unknown => {
  if (value instanceof Error) {
    return { name: value.name, message: value.message };
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
  const prefix = `[${record.scope}] ${record.message}`;
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
  const parentFields = flattenFields(fields);

  const emit = (level: LogLevel, message: string, callFields?: LogFields): void => {
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
