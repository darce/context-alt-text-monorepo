import {
  abortLikeTag,
  AuthExpiredError,
  HTTPError,
  NonceRefreshFailedError,
  ResponseParseError,
  type AppErrorTag,
} from './errorTaxonomy';
import { hasRetryAfterWait } from './retryAfter';
import { SPA_SESSION_EXPIRED_COPY } from './sessionExpiredCopy';

/**
 * The closed tag set and the boundary error classes live in the leaf module
 * `./errorTaxonomy`; this module owns the *classification* of an unknown thrown
 * value into that vocabulary. Splitting the two is what removes the back-edge
 * `utils/appError -> api/config` (FEBT2-LA-NEW-01; GRPH-02
 * lexicons/graph-theory.md:72). Both names are re-exported unchanged, so
 * `import { APP_ERROR_TAGS } from './appError'` still resolves for every caller.
 */
export { APP_ERROR_TAGS, isAbortOrTimeoutName } from './errorTaxonomy';
export type { AppErrorTag } from './errorTaxonomy';


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
  if (error.retryAfterMs === undefined) {
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
    retryAfterMs: error.retryAfterMs,
    message: error.message,
    cause: error,
  };
};

/**
 * Messages a `fetch` network failure rejects with, per browser. Every other
 * `TypeError` is a programming bug (`x is not a function`) and must not be
 * retried as if the network dropped (FEBT-1-W1-E-05). A network failure raised
 * inside `fetchApi` never reaches this list — the boundary already tagged it
 * `TransportError` by provenance.
 */
const FETCH_NETWORK_FAILURE_MESSAGES = [
  'Failed to fetch',
  'Load failed',
  'NetworkError when attempting to fetch resource',
  'Network request failed',
  'fetch failed',
] as const;

const isFetchNetworkFailureMessage = (message: string): boolean =>
  FETCH_NETWORK_FAILURE_MESSAGES.some((known) => message.includes(known));

export const classifyError = (error: unknown): AppError => {
  try {
    // FEBT1G-M-07 / FEBT1-W2A-01: since the boundary classes carry `_tag`,
    // an already-tagged value IS its own classification. Returning the instance
    // preserves the stack and `instanceof`, and it is what the logger's
    // name-shaped safe projection keys on. Re-projecting it into a plain object
    // here would discard the capture site for no gain — one concept, one
    // representation (NAME-02, lexicons/engineering.md:649).
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
    const abortTag = abortLikeTag(error);
    if (abortTag !== undefined) {
      return {
        _tag: abortTag,
        message: abortMessage(error),
        cause: error,
      };
    }
    if (error instanceof TypeError && isFetchNetworkFailureMessage(error.message)) {
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
    (classified.status === 429 || (classified.status === 503 && hasRetryAfterWait(classified.retryAfterMs)))
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
