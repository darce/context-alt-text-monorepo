import { NonceRefreshFailedError } from '../api/config';
import { AuthExpiredError, HTTPError, ResponseParseError } from './http';
import { SPA_SESSION_EXPIRED_COPY } from './sessionExpiredCopy';

export const APP_ERROR_TAGS = [
  'http',
  'parse',
  'auth_expired',
  'nonce_refresh',
  'abort',
  'timeout',
  'transport',
  'unknown',
] as const;

export type AppErrorTag = (typeof APP_ERROR_TAGS)[number];

const APP_ERROR_TAG_INDEX: Record<AppErrorTag, true> = {
  http: true,
  parse: true,
  auth_expired: true,
  nonce_refresh: true,
  abort: true,
  timeout: true,
  transport: true,
  unknown: true,
};

const assertNever = (value: never): never => {
  throw new Error(`Unexpected AppError tag: ${String(value)}`);
};

interface AppErrorBase<T extends AppErrorTag> {
  readonly _tag: T;
  readonly message: string;
  readonly cause: unknown;
}

export type AppError =
  | (AppErrorBase<'http'> & {
      readonly status: number;
      readonly endpoint: string;
      readonly retryAfterMs?: number;
    })
  | (AppErrorBase<'parse'> & { readonly endpoint: string })
  | (AppErrorBase<'auth_expired'> & {
      readonly endpoint: string;
      readonly status: 401 | 403;
    })
  | AppErrorBase<'nonce_refresh'>
  | AppErrorBase<'abort'>
  | AppErrorBase<'timeout'>
  | AppErrorBase<'transport'>
  | AppErrorBase<'unknown'>;

const isAppErrorTag = (tag: unknown): tag is AppErrorTag =>
  typeof tag === 'string' && Object.hasOwn(APP_ERROR_TAG_INDEX, tag);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const hasCauseAndMessage = (value: Record<string, unknown>): boolean =>
  'cause' in value && typeof value.message === 'string';

export const isAppError = (value: unknown): value is AppError => {
  if (!isRecord(value) || !isAppErrorTag(value._tag) || !hasCauseAndMessage(value)) {
    return false;
  }
  switch (value._tag) {
    case 'http':
      return (
        typeof value.status === 'number' &&
        typeof value.endpoint === 'string' &&
        (value.retryAfterMs === undefined || typeof value.retryAfterMs === 'number')
      );
    case 'parse':
      return typeof value.endpoint === 'string';
    case 'auth_expired':
      return (value.status === 401 || value.status === 403) && typeof value.endpoint === 'string';
    case 'nonce_refresh':
    case 'abort':
    case 'timeout':
    case 'transport':
    case 'unknown':
      return true;
    default:
      return assertNever(value._tag);
  }
};

const ABORT_ERROR_NAME = 'AbortError';
const TIMEOUT_ERROR_NAME = 'TimeoutError';
const ABORT_OR_TIMEOUT_NAMES = new Set([ABORT_ERROR_NAME, TIMEOUT_ERROR_NAME]);

const duckTypeName = (value: unknown): string | undefined => {
  if (typeof value !== 'object' || value === null) {
    return undefined;
  }
  const name = (value as { name?: unknown }).name;
  return typeof name === 'string' ? name : undefined;
};

/** Duck-type: DOMException, Error, or any object whose name is AbortError or TimeoutError. */
export const isAbortOrTimeoutName = (value: unknown): boolean => {
  const name = duckTypeName(value);
  return name !== undefined && ABORT_OR_TIMEOUT_NAMES.has(name);
};

const unknownMessage = (value: unknown): string => {
  if (value instanceof Error) {
    return value.message;
  }
  if (typeof value === 'string') {
    return value === '' ? 'Unknown error' : value;
  }
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  return 'Unknown error';
};

const abortMessage = (error: unknown): string => {
  if (isRecord(error) && typeof error.message === 'string') {
    return error.message;
  }
  return unknownMessage(error);
};

const classifyHttpError = (error: HTTPError): AppError => {
  if (error.retryAfterSeconds === undefined) {
    return {
      _tag: 'http',
      status: error.status,
      endpoint: error.endpoint,
      message: error.message,
      cause: error,
    };
  }
  return {
    _tag: 'http',
    status: error.status,
    endpoint: error.endpoint,
    retryAfterMs: error.retryAfterSeconds * 1000,
    message: error.message,
    cause: error,
  };
};

export const classifyError = (error: unknown): AppError => {
  try {
    if (isAppError(error)) {
      return error;
    }
    if (error instanceof AuthExpiredError) {
      return {
        _tag: 'auth_expired',
        endpoint: error.endpoint,
        status: error.status,
        message: error.message,
        cause: error,
      };
    }
    if (error instanceof HTTPError) {
      return classifyHttpError(error);
    }
    if (error instanceof ResponseParseError) {
      return {
        _tag: 'parse',
        endpoint: error.endpoint,
        message: error.message,
        cause: error,
      };
    }
    if (error instanceof NonceRefreshFailedError) {
      return {
        _tag: 'nonce_refresh',
        message: error.message,
        cause: error,
      };
    }
    const name = duckTypeName(error);
    if (name === TIMEOUT_ERROR_NAME) {
      return {
        _tag: 'timeout',
        message: abortMessage(error),
        cause: error,
      };
    }
    if (name === ABORT_ERROR_NAME) {
      return {
        _tag: 'abort',
        message: abortMessage(error),
        cause: error,
      };
    }
    if (error instanceof TypeError) {
      return {
        _tag: 'transport',
        message: error.message,
        cause: error,
      };
    }
    if (error instanceof Error) {
      return {
        _tag: 'unknown',
        message: error.message,
        cause: error,
      };
    }
    return {
      _tag: 'unknown',
      message: unknownMessage(error),
      cause: error,
    };
  } catch {
    return {
      _tag: 'unknown',
      message: 'Unknown error',
      cause: error,
    };
  }
};

export const isHttpStatus = (error: unknown, status: number): boolean => {
  const classified = classifyError(error);
  return classified._tag === 'http' && classified.status === status;
};

export const isCooldown = (error: unknown): boolean => {
  const classified = classifyError(error);
  return (
    classified._tag === 'http' &&
    (classified.status === 429 || (classified.status === 503 && classified.retryAfterMs !== undefined))
  );
};

/** Overlay transport copy. nonce_refresh reuses this; do not invent a new string. */
const NETWORK_ERROR_COPY = 'Network error — check your connection';
const TIMEOUT_ERROR_COPY = 'The server took too long to respond — try again';

export const toUserMessage = (error: unknown, fallback: string): string => {
  const classified = classifyError(error);
  if (classified._tag === 'auth_expired') {
    return SPA_SESSION_EXPIRED_COPY.sessionExpired;
  }
  if (classified._tag === 'nonce_refresh') {
    return NETWORK_ERROR_COPY;
  }
  if (classified._tag === 'timeout') {
    return TIMEOUT_ERROR_COPY;
  }
  return fallback;
};
