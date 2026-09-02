import { describe, expect, it } from 'vitest';

import { NonceRefreshFailedError } from '../../api/config';
import { AuthExpiredError, HTTPError, ResponseParseError } from '../http';
import { SPA_SESSION_EXPIRED_COPY } from '../userFacingError';
import {
  classifyError,
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
