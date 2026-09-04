/**
 * The error vocabulary: the closed tag set, the boundary error classes, and the
 * nonce-refresh error family. This module is a LEAF — it imports nothing, and it
 * must stay that way.
 *
 * Why it exists (FEBT2-LA-NEW-01 / FEBT2-LC-NEW-03): `api/config -> utils/logger
 * -> utils/appError -> utils/http -> api/config` was a load-time ESM cycle.
 * `class X extends Y` evaluates `Y` during module evaluation, so entering the
 * cycle from `api/config` left `NonceRefreshFailedError` in its temporal dead
 * zone and `class NonceRefreshError extends NonceRefreshFailedError` threw
 * `TypeError: Class extends value undefined`, killing every suite that
 * transitively imported `http.ts`. tsc passed throughout — a type checker cannot
 * see evaluation order.
 *
 * The cut follows ADP's second break technique: extract the module that both
 * sides of the back-edge depend on (agile-software-development-ppp ch-20;
 * distilled/engineering/agile-software-development-ppp.md:306), which turns the
 * back-edges `utils/appError -> api/config` and `utils/http -> utils/appError`
 * into forward edges into a leaf. GRPH-02 (lexicons/graph-theory.md:72): a cycle
 * is one indivisible unit — name the back-edge and cut it. ARCH-20
 * (lexicons/engineering.md:570): dependency arrows point toward the more stable
 * module, and an error vocabulary with ~20 dependents is far more stable than the
 * WordPress config adapter that used to own `NonceRefreshFailedError`.
 *
 * Co-locating a base class with its subclass is the same law at class scope: a
 * logical dependency cycle must either share one module or be broken before
 * packaging (designing-oo-cpp-booch ch-3;
 * distilled/engineering/designing-oo-cpp-booch.md:163). `NonceRefreshError` and
 * `NonceRefreshFailedError` therefore live here, together.
 *
 * Every symbol below is re-exported from its historical home (`utils/http`,
 * `utils/appError`, `api/config`) so no call site outside this module moved.
 */

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

/**
 * The two DOM error names that mean "this request did not finish", and the
 * `AppError` tag each one carries. Single owner (REF-19) for the mapping —
 * `appError.classifyError` imports it rather than re-deriving the name set,
 * which is how `'AbortError'` and `'TimeoutError'` came to collapse into one
 * tag in two places (FEBT1-W2A-05).
 */
export const ABORT_LIKE_ERROR_NAME_TAGS = {
  AbortError: 'abort',
  TimeoutError: 'timeout',
} as const satisfies Record<string, AppErrorTag>;

type AbortLikeErrorName = keyof typeof ABORT_LIKE_ERROR_NAME_TAGS;

const errorName = (value: unknown): string | undefined => {
  if (typeof value !== 'object' || value === null) {
    return undefined;
  }
  const name: unknown = (value as { name?: unknown }).name;
  return typeof name === 'string' ? name : undefined;
};

const isAbortLikeErrorName = (name: string | undefined): name is AbortLikeErrorName =>
  name !== undefined && Object.hasOwn(ABORT_LIKE_ERROR_NAME_TAGS, name);

/**
 * `'abort'` for a user/caller cancellation, `'timeout'` for a deadline that
 * elapsed, `undefined` for anything else. A cancel and a timeout are different
 * events: only one of them is worth retrying, and only one of them should tell
 * the user something took too long.
 */
export const abortLikeTag = (value: unknown): 'abort' | 'timeout' | undefined => {
  const name = errorName(value);
  return isAbortLikeErrorName(name) ? ABORT_LIKE_ERROR_NAME_TAGS[name] : undefined;
};

/** Duck-type: DOMException, Error, or any object whose name is AbortError|TimeoutError. */
export const isAbortLikeName = (value: unknown): boolean => abortLikeTag(value) !== undefined;

/**
 * Every error that escapes `fetchApi` extends this, so the boundary is closed:
 * `isAppError(thrown)` holds without the caller remembering to run
 * `classifyError` first (FEBT1-W2A-01, ARCH-13 — make the property structural
 * rather than a convention every call site must honour).
 *
 * It is an `Error` subclass, not a plain tagged object, so `instanceof
 * HTTPError` / `instanceof AuthExpiredError` and the stack trace both survive
 * the boundary closing (FEBT1-LB-03 (b) and (c)).
 */
export abstract class BoundaryError extends Error {
  abstract readonly _tag: AppErrorTag;
  readonly cause: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.cause = cause;
  }
}

export class HTTPError extends BoundaryError {
  readonly _tag = 'http' as const;
  readonly status: number;
  readonly retryAfterSeconds: number | undefined;
  /**
   * `retryAfterSeconds` in the unit the `AppError` contract speaks. Stored, not
   * derived by `classifyError`, so an `HTTPError` satisfies `isAppError` on its
   * own and `isCooldown`/`getRetryDelay` read the same field whether they were
   * handed the instance or a classified copy.
   */
  readonly retryAfterMs: number | undefined;
  readonly endpoint: string;
  readonly bodyPreview: string;

  constructor({
    status,
    retryAfterSeconds,
    endpoint,
    bodyPreview,
    message,
  }: {
    status: number;
    retryAfterSeconds: number | undefined;
    endpoint: string;
    bodyPreview: string;
    message: string;
  }) {
    super(message);
    this.name = 'HTTPError';
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
    this.retryAfterMs = retryAfterSeconds === undefined ? undefined : retryAfterSeconds * 1000;
    this.endpoint = endpoint;
    this.bodyPreview = bodyPreview;
  }
}

export class ResponseParseError extends BoundaryError {
  readonly _tag = 'parse' as const;
  readonly status: number;
  readonly endpoint: string;
  readonly bodyPreview: string;

  constructor({
    status,
    endpoint,
    bodyPreview,
    message,
  }: {
    status: number;
    endpoint: string;
    bodyPreview: string;
    message: string;
  }) {
    super(message);
    this.name = 'ResponseParseError';
    this.status = status;
    this.endpoint = endpoint;
    this.bodyPreview = bodyPreview;
  }
}

/**
 * Session/auth expiry (nonce-403 after refresh failure, or rest_not_logged_in).
 * Not an HTTPError subclass — surfaces distinct recovery UI (Slice 3).
 */
export class AuthExpiredError extends BoundaryError {
  readonly _tag = 'auth_expired' as const;
  readonly endpoint: string;
  readonly status: 401 | 403;

  constructor({ endpoint, status, message }: { endpoint: string; status: 401 | 403; message?: string }) {
    super(message ?? `Authentication expired for ${endpoint} (${status}).`);
    this.name = 'AuthExpiredError';
    this.endpoint = endpoint;
    this.status = status;
  }
}

/**
 * The caller (or an unmounting component) cancelled the request. Keeps
 * `name === 'AbortError'` so every existing duck-typed `.name` check still
 * matches; the `_tag` is what distinguishes it from a timeout.
 */
export class AbortedRequestError extends BoundaryError {
  readonly _tag = 'abort' as const;

  constructor(cause: unknown, message = 'The operation was aborted.') {
    super(message, cause);
    this.name = 'AbortError';
  }
}

/**
 * A deadline elapsed with no answer. Distinct from a cancel (FEBT1-W2A-05): the
 * outcome is UNKNOWN rather than "the user changed their mind", so it is worth
 * one bounded retry and it is the only one of the two that should tell the user
 * something took too long.
 */
export class RequestTimeoutError extends BoundaryError {
  readonly _tag = 'timeout' as const;

  constructor(cause: unknown, message = 'The operation timed out.') {
    super(message, cause);
    this.name = 'TimeoutError';
  }
}

/** The request never reached a server (fetch rejected with a network TypeError). */
export class TransportError extends BoundaryError {
  readonly _tag = 'transport' as const;

  constructor(cause: unknown, message: string) {
    super(message, cause);
    this.name = 'TransportError';
  }
}

/** Anything else escaping the boundary: still tagged, never retried. */
export class UnknownBoundaryError extends BoundaryError {
  readonly _tag = 'unknown' as const;

  constructor(cause: unknown, message: string) {
    super(message, cause);
    this.name = 'UnknownBoundaryError';
  }
}

/**
 * A nonce refresh that did not produce a fresh nonce. Raised by
 * `api/config.refreshRestNonce`, which re-exports this class from its historical
 * home so existing `import { NonceRefreshFailedError } from '../api/config'`
 * call sites are unchanged.
 */
export class NonceRefreshFailedError extends Error {
  readonly causeStatus: number | undefined;
  readonly bodyPreview: string;

  constructor({
    message,
    causeStatus,
    bodyPreview,
  }: {
    message: string;
    causeStatus?: number;
    bodyPreview?: string;
  }) {
    super(message);
    this.name = 'NonceRefreshFailedError';
    this.causeStatus = causeStatus;
    this.bodyPreview = bodyPreview ?? '';
  }
}

/**
 * A nonce refresh failure carrying the tag that closes the boundary. Subclasses
 * `NonceRefreshFailedError` so `instanceof NonceRefreshFailedError`,
 * `causeStatus` and `bodyPreview` keep working for every existing caller.
 *
 * Declared in the same module as its base — deliberately, and permanently. A
 * base/subclass pair split across modules is only safe while the graph happens
 * to evaluate in a convenient order, which is exactly the accidental context
 * REF-27 (lexicons/engineering.md:347) forbids depending on.
 */
export class NonceRefreshError extends NonceRefreshFailedError {
  readonly _tag = 'nonce_refresh' as const;
  readonly cause: unknown;

  constructor(source: NonceRefreshFailedError) {
    super({
      message: source.message,
      causeStatus: source.causeStatus,
      bodyPreview: source.bodyPreview,
    });
    this.name = source.name;
    this.cause = source;
  }
}

/** True for an already-tagged nonce-refresh failure (idempotent re-wrap guard). */
export const isTaggedNonceRefreshError = (error: unknown): error is NonceRefreshError =>
  error instanceof NonceRefreshFailedError && '_tag' in error;

export const toNonceRefreshError = (source: NonceRefreshFailedError): NonceRefreshError =>
  isTaggedNonceRefreshError(source) ? source : new NonceRefreshError(source);
