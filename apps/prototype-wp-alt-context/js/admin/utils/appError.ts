import { NonceRefreshFailedError } from '../api/config';
import { AuthExpiredError, HTTPError, ResponseParseError } from './http';
import { SPA_SESSION_EXPIRED_COPY } from './userFacingError';

export type AppError =
  | { _tag: 'http'; status: number; endpoint: string; retryAfterMs?: number; message: string; cause: unknown }
  | { _tag: 'parse'; endpoint: string; message: string; cause: unknown }
  | { _tag: 'auth_expired'; endpoint: string; status: 401 | 403; message: string; cause: unknown }
  | { _tag: 'nonce_refresh'; message: string; cause: unknown }
  | { _tag: 'abort'; message: string; cause: unknown }
  | { _tag: 'transport'; message: string; cause: unknown }
  | { _tag: 'unknown'; message: string; cause: unknown };

export type AppErrorTag = AppError['_tag'];

const isAppErrorTag = (tag: unknown): tag is AppErrorTag =>
  tag === 'http' ||
  tag === 'parse' ||
  tag === 'auth_expired' ||
  tag === 'nonce_refresh' ||
  tag === 'abort' ||
  tag === 'transport' ||
  tag === 'unknown';

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
    case 'transport':
    case 'unknown':
      return true;
  }
};

const ABORT_LIKE_NAMES = new Set(['AbortError', 'TimeoutError']);
const TRANSPORT_MESSAGE_MARKERS = ['Failed to fetch', 'Load failed', 'NetworkError'] as const;

const objectName = (value: object): string | undefined => {
  const name = (value as { name?: unknown }).name;
  return typeof name === 'string' ? name : undefined;
};

const isAbortLikeValue = (error: unknown): error is Error | DOMException => {
  if (error instanceof DOMException || error instanceof Error) {
    const name = objectName(error);
    return name !== undefined && ABORT_LIKE_NAMES.has(name);
  }
  return false;
};

const isTransportTypeError = (error: TypeError): boolean =>
  TRANSPORT_MESSAGE_MARKERS.some((marker) => error.message.includes(marker));

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

const authExpiredStatus = (status: number): 401 | 403 => (status === 403 ? 403 : 401);

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
        status: authExpiredStatus(error.status),
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
    if (isAbortLikeValue(error)) {
      return {
        _tag: 'abort',
        message: error.message,
        cause: error,
      };
    }
    if (error instanceof TypeError && isTransportTypeError(error)) {
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

export const toUserMessage = (error: unknown, fallback: string): string => {
  if (classifyError(error)._tag === 'auth_expired') {
    return SPA_SESSION_EXPIRED_COPY.sessionExpired;
  }
  return fallback;
};
