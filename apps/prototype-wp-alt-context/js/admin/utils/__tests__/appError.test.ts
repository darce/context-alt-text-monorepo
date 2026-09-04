import { describe, expect, it } from 'vitest';

import { NonceRefreshFailedError } from '../../api/config';
import { AuthExpiredError, HTTPError, ResponseParseError } from '../http';
import { SPA_SESSION_EXPIRED_COPY } from '../userFacingError';
import {
  APP_ERROR_TAGS,
  classifyError,
  isAbortLikeName,
  isAppError,
  isCooldown,
  isHttpStatus,
  toUserMessage,
} from '../appError';

const ENDPOINT = 'http://example.test/e';

const httpError = (status: number, retryAfterSeconds?: number): HTTPError =>
  new HTTPError({
    status,
    retryAfterSeconds,
    endpoint: ENDPOINT,
    bodyPreview: 'body',
    message: `Request to ${ENDPOINT} failed (${status}): body`,
  });

describe('classifyError', () => {
  it('classifies HTTPError as http and preserves message/cause', () => {
    const error = httpError(500);
    const classified = classifyError(error);
    expect(classified).toEqual({
      _tag: 'http',
      status: 500,
      endpoint: ENDPOINT,
      message: error.message,
      cause: error,
    });
  });

  it('classifies ResponseParseError as parse', () => {
    const error = new ResponseParseError({
      status: 200,
      endpoint: ENDPOINT,
      bodyPreview: 'oops',
      message: `Request to ${ENDPOINT} returned malformed JSON (200): x`,
    });
    expect(classifyError(error)).toEqual({
      _tag: 'parse',
      endpoint: ENDPOINT,
      message: error.message,
      cause: error,
    });
  });

  it('classifies AuthExpiredError 401 and 403 as auth_expired', () => {
    const expired401 = new AuthExpiredError({ endpoint: ENDPOINT, status: 401 });
    const expired403 = new AuthExpiredError({ endpoint: ENDPOINT, status: 403 });
    expect(classifyError(expired401)).toEqual({
      _tag: 'auth_expired',
      endpoint: ENDPOINT,
      status: 401,
      message: expired401.message,
      cause: expired401,
    });
    expect(classifyError(expired403)).toEqual({
      _tag: 'auth_expired',
      endpoint: ENDPOINT,
      status: 403,
      message: expired403.message,
      cause: expired403,
    });
  });

  it('classifies NonceRefreshFailedError as nonce_refresh', () => {
    const error = new NonceRefreshFailedError({ message: 'nonce refresh failed' });
    expect(classifyError(error)).toEqual({
      _tag: 'nonce_refresh',
      message: error.message,
      cause: error,
    });
  });

  it('classifies DOMException AbortError as abort', () => {
    const error = new DOMException('The operation was aborted.', 'AbortError');
    expect(classifyError(error)).toEqual({
      _tag: 'abort',
      message: error.message,
      cause: error,
    });
  });

  it("classifies TypeError('Failed to fetch') as transport", () => {
    const failed = new TypeError('Failed to fetch');
    expect(classifyError(failed)).toEqual({
      _tag: 'transport',
      message: failed.message,
      cause: failed,
    });
    const loadFailed = new TypeError('Load failed');
    expect(classifyError(loadFailed)._tag).toBe('transport');
    const networkError = new TypeError('NetworkError when attempting to fetch resource');
    expect(classifyError(networkError)._tag).toBe('transport');
  });

  it('classifies a generic Error as unknown with its message', () => {
    const error = new Error('plain failure');
    expect(classifyError(error)).toEqual({
      _tag: 'unknown',
      message: 'plain failure',
      cause: error,
    });
  });

  it('classifies HTTPError 429 with Retry-After as http carrying retryAfterMs', () => {
    const error = httpError(429, 5);
    expect(classifyError(error)).toEqual({
      _tag: 'http',
      status: 429,
      endpoint: ENDPOINT,
      retryAfterMs: 5_000,
      message: error.message,
      cause: error,
    });
  });

  it('is idempotent: classifyError(classifyError(e)) deep-equals classifyError(e)', () => {
    const samples: unknown[] = [
      httpError(404),
      httpError(429, 5),
      new AuthExpiredError({ endpoint: ENDPOINT, status: 401 }),
      new ResponseParseError({
        status: 200,
        endpoint: ENDPOINT,
        bodyPreview: 'x',
        message: 'malformed',
      }),
      new NonceRefreshFailedError({ message: 'nonce' }),
      new DOMException('The operation was aborted.', 'AbortError'),
      new TypeError('Failed to fetch'),
      new Error('plain'),
      'string-error',
      null,
      undefined,
      { foo: 1 },
    ];
    for (const sample of samples) {
      const once = classifyError(sample);
      expect(classifyError(once)).toEqual(once);
      expect(isAppError(once)).toBe(true);
    }
  });

  it('classifies non-Error inputs as unknown', () => {
    expect(classifyError('string-error')).toEqual({
      _tag: 'unknown',
      message: 'string-error',
      cause: 'string-error',
    });
    expect(classifyError(null)).toEqual({
      _tag: 'unknown',
      message: 'Unknown error',
      cause: null,
    });
    expect(classifyError(undefined)).toEqual({
      _tag: 'unknown',
      message: 'Unknown error',
      cause: undefined,
    });
    const obj = { foo: 1 };
    expect(classifyError(obj)).toEqual({
      _tag: 'unknown',
      message: 'Unknown error',
      cause: obj,
    });
    const sym = Symbol('x');
    expect(classifyError(sym)).toEqual({
      _tag: 'unknown',
      message: 'Unknown error',
      cause: sym,
    });
    const fn = (): void => undefined;
    expect(classifyError(fn)).toEqual({
      _tag: 'unknown',
      message: 'Unknown error',
      cause: fn,
    });
  });
});

describe('isHttpStatus / isCooldown / toUserMessage', () => {
  it('isHttpStatus is true for HTTPError 404', () => {
    const error = httpError(404);
    expect(isHttpStatus(error, 404)).toBe(true);
    expect(isHttpStatus(error, 500)).toBe(false);
  });

  it('isCooldown is true for HTTPError 429 with Retry-After', () => {
    const error = httpError(429, 5);
    expect(classifyError(error)._tag).toBe('http');
    expect(isCooldown(error)).toBe(true);
    expect(isCooldown(httpError(429))).toBe(true);
    expect(isCooldown(httpError(503, 10))).toBe(true);
    expect(isCooldown(httpError(503))).toBe(false);
    expect(isCooldown(httpError(404))).toBe(false);
  });

  it('toUserMessage maps auth_expired to session copy and everything else to fallback', () => {
    const fallback = 'safe fallback';
    expect(toUserMessage(new AuthExpiredError({ endpoint: ENDPOINT, status: 401 }), fallback)).toBe(
      SPA_SESSION_EXPIRED_COPY.sessionExpired,
    );
    expect(toUserMessage(new AuthExpiredError({ endpoint: ENDPOINT, status: 403 }), fallback)).toBe(
      SPA_SESSION_EXPIRED_COPY.sessionExpired,
    );
    expect(toUserMessage(httpError(404), fallback)).toBe(fallback);
    expect(toUserMessage(new TypeError('Failed to fetch'), fallback)).toBe(fallback);
    expect(toUserMessage(new Error('Request to /secret failed (500): body'), fallback)).toBe(fallback);
    expect(toUserMessage('raw string', fallback)).toBe(fallback);
    expect(toUserMessage(null, fallback)).toBe(fallback);
  });
});

describe('AppError tags / mutant-killing pins [TEST-15]', () => {
  it('APP_ERROR_TAGS is the closed tag set [F1]', () => {
    expect(APP_ERROR_TAGS).toEqual([
      'http',
      'parse',
      'auth_expired',
      'nonce_refresh',
      'abort',
      'timeout',
      'transport',
      'unknown',
    ]);
  });

  it('isAppError requires own cause (M1)', () => {
    expect(isAppError({ _tag: 'unknown', message: 'x' })).toBe(false);
    expect(isAppError({ _tag: 'unknown', message: 'x', cause: undefined })).toBe(true);
  });

  it('auth_expired status 500 is not an AppError (M2)', () => {
    expect(
      isAppError({
        _tag: 'auth_expired',
        status: 500,
        endpoint: ENDPOINT,
        message: 'expired',
        cause: null,
      }),
    ).toBe(false);
    expect(
      isAppError({
        _tag: 'auth_expired',
        status: 401,
        endpoint: ENDPOINT,
        message: 'expired',
        cause: null,
      }),
    ).toBe(true);
  });

  it('http retryAfterMs must be a number when present (M3)', () => {
    expect(
      isAppError({
        _tag: 'http',
        status: 429,
        endpoint: ENDPOINT,
        message: 'slow',
        cause: null,
        retryAfterMs: 'soon',
      }),
    ).toBe(false);
    expect(
      isAppError({
        _tag: 'http',
        status: 429,
        endpoint: ENDPOINT,
        message: 'slow',
        cause: null,
        retryAfterMs: 1000,
      }),
    ).toBe(true);
  });

  it('AuthExpiredError 401 and 403 round-trip exact status (M4)', () => {
    const expired401 = new AuthExpiredError({ endpoint: ENDPOINT, status: 401 });
    const expired403 = new AuthExpiredError({ endpoint: ENDPOINT, status: 403 });
    expect(expired401.status).toBe(401);
    expect(expired403.status).toBe(403);
    const classified401 = classifyError(expired401);
    const classified403 = classifyError(expired403);
    expect(classified401._tag).toBe('auth_expired');
    expect(classified403._tag).toBe('auth_expired');
    if (classified401._tag === 'auth_expired') {
      expect(classified401.status).toBe(401);
    }
    if (classified403._tag === 'auth_expired') {
      expect(classified403.status).toBe(403);
    }
  });

  // FEBT1-W2A-05: strengthened, not relaxed. This used to assert TimeoutError
  // === 'abort', collapsing "the caller withdrew" with "the deadline elapsed".
  // It now pins the *distinction*, which is a strictly stronger claim: the two
  // inputs must land on two different tags, and the old assertion cannot pass.
  it('TimeoutError classifies as timeout, AbortError as abort — never collapsed (M5)', () => {
    const timedOut = new DOMException('The operation timed out.', 'TimeoutError');
    expect(isAbortLikeName(timedOut)).toBe(true);
    expect(classifyError(timedOut)._tag).toBe('timeout');
    const named = Object.assign(new Error('timed out'), { name: 'TimeoutError' });
    expect(classifyError(named)._tag).toBe('timeout');
    expect(classifyError(named).message).toBe('timed out');

    const cancelled = new DOMException('The user aborted a request.', 'AbortError');
    expect(classifyError(cancelled)._tag).toBe('abort');
    expect(classifyError(timedOut)._tag).not.toBe(classifyError(cancelled)._tag);
  });

  it('Error-instance AbortError classifies as abort (M6)', () => {
    const aborted = Object.assign(new Error('x'), { name: 'AbortError' });
    expect(isAbortLikeName(aborted)).toBe(true);
    expect(classifyError(aborted)._tag).toBe('abort');
    expect(classifyError(aborted).message).toBe('x');
  });

  it("TypeError message containing 'Failed to fetch' is transport (M7)", () => {
    const error = new TypeError('boom: Failed to fetch');
    expect(classifyError(error)._tag).toBe('transport');
    expect(classifyError(error).message).toBe('boom: Failed to fetch');
  });

  // FEBT-1-W1-E-05: strengthened, not relaxed. The old pin ("any TypeError is
  // transport") made every programming bug retryable, so `x is not a function`
  // was re-issued three times. The replacement keeps every genuine fetch
  // network-failure message on 'transport' (each browser's wording is pinned
  // explicitly, so narrowing the list cannot pass) and additionally requires a
  // non-network TypeError to be 'unknown'.
  it('fetch network-failure TypeErrors are transport; a bug TypeError is not (M8 / F5)', () => {
    for (const message of [
      'Failed to fetch',
      'Load failed',
      'NetworkError when attempting to fetch resource',
      'Network request failed',
      'fetch failed',
    ]) {
      expect(classifyError(new TypeError(message))._tag).toBe('transport');
    }

    const bug = new TypeError('x is not a function');
    expect(classifyError(bug)._tag).toBe('unknown');
    expect(classifyError(bug).message).toBe('x is not a function');
  });

  it("empty string classifies as unknown with 'Unknown error' (M9)", () => {
    expect(classifyError('')).toEqual({
      _tag: 'unknown',
      message: 'Unknown error',
      cause: '',
    });
  });

  it('number/boolean/bigint stringify into unknown message (M10)', () => {
    expect(classifyError(42).message).toBe('42');
    expect(classifyError(42)._tag).toBe('unknown');
    expect(classifyError(true).message).toBe('true');
    expect(classifyError(1n).message).toBe('1');
  });

  it('throwing message getter is unknown and does not throw (M11)', () => {
    const poison: { message: string } = {} as { message: string };
    Object.defineProperty(poison, 'message', {
      get(): string {
        throw new Error('accessor boom');
      },
    });
    expect(() => classifyError(poison)).not.toThrow();
    const classified = classifyError(poison);
    expect(classified._tag).toBe('unknown');
    expect(classified.message).toBe('Unknown error');
    expect(classified.cause).toBe(poison);
  });

  it('isHttpStatus uses strict equality both directions (M12)', () => {
    expect(isHttpStatus(httpError(500), 404)).toBe(false);
    expect(isHttpStatus(httpError(404), 500)).toBe(false);
    expect(isHttpStatus(httpError(404), 404)).toBe(true);
  });

  it('classifyError is reference-idempotent for AppError inputs (M13)', () => {
    const once = classifyError(httpError(404));
    expect(classifyError(once)).toBe(once);
    expect(isAppError(null)).toBe(false);
    expect(isAppError({})).toBe(false);
    expect(isAppError({ _tag: 'nope' })).toBe(false);
    expect(isAppError({ _tag: 'http' })).toBe(false);
    expect(isAppError({ _tag: 'http', message: 'x', cause: null })).toBe(false);
  });

  it('plain-object AbortError classifies as abort (F3)', () => {
    const abortLike = { name: 'AbortError', message: 'aborted' };
    expect(isAbortLikeName(abortLike)).toBe(true);
    expect(classifyError(abortLike)._tag).toBe('abort');
    expect(classifyError({ name: 'TimeoutError', message: 'timed out' })._tag).toBe('timeout');
  });
});
