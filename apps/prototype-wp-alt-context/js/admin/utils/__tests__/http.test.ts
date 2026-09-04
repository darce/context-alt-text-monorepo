import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getNonce,
  NONCE_REFRESH_TIMEOUT_MS,
  NonceRefreshFailedError,
  registerConfig,
  resetConfigCache,
} from '../../api/config';
import * as configApi from '../../api/config';
import { classifyError, isAppError, isCooldown, toUserMessage } from '../appError';
import {
  AuthExpiredError,
  DEFAULT_FETCH_TIMEOUT_MS,
  fetchApi,
  fetchRequiredApi,
  HTTPError,
  parseRetryAfter,
  ResponseParseError,
} from '../http';
import { getRetryDelay, shouldRetryRequest } from '../retryPolicy';
import { SPA_SESSION_EXPIRED_COPY } from '../sessionExpiredCopy';

const REST_URL = 'http://example.test/wp-json/acx/v1/endpoint';
const AJAX_URL = 'https://example.test/wp-admin/admin-ajax.php';
const STALE_NONCE = 'stale0001ab';
const FRESH_NONCE = 'a1b2c3d4e5';

const nonce403Body = JSON.stringify({
  code: 'rest_cookie_invalid_nonce',
  message: 'Cookie check failed',
  data: { status: 403 },
});

const seedConfig = (nonce = STALE_NONCE): void => {
  registerConfig({
    nonce,
    ajaxUrl: AJAX_URL,
    endpoints: {},
  });
};

const isAjaxCall = (url: unknown): boolean =>
  typeof url === 'string' && url.includes('action=rest-nonce');

const isRestCall = (url: unknown): boolean =>
  typeof url === 'string' && !isAjaxCall(url);

describe('fetchApi', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetConfigCache();
  });

  it('returns undefined for 204 responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));

    const result = await fetchApi<void>('http://example.test/endpoint', { method: 'POST' });

    expect(result).toBeUndefined();
  });

  // Narrowing the guard to `status === 204` alone left the 204 test green
  // (FEBT1-W2C-14). A non-empty body proves the guard short-circuits before
  // the body is ever read, rather than the body merely happening to be empty.
  it('returns undefined for 205 responses even when a body is present', async () => {
    // `new Response(body, { status: 205 })` is rejected by the spec (null-body
    // status), so shadow `status` on an otherwise real 200 response.
    const response = new Response(JSON.stringify({ ignored: true }), { status: 200 });
    Object.defineProperty(response, 'status', { value: 205 });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);

    const result = await fetchApi<{ ignored: boolean }>('http://example.test/endpoint', {
      method: 'POST',
    });

    expect(result).toBeUndefined();
    expect(response.bodyUsed).toBe(false);
  });

  it('returns undefined for successful empty response bodies', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 200 }));

    const result = await fetchApi<void>('http://example.test/endpoint');

    expect(result).toBeUndefined();
  });

  it('surfaces endpoint and response preview for malformed JSON bodies', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"status":"ok"} trailing-debug-output', { status: 200 }),
    );

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected malformed JSON request to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(Error);
      expect((error as Error).message).toMatch(
        /Request to http:\/\/example\.test\/endpoint returned malformed JSON \(200\):/,
      );
      expect((error as Error).message).toMatch(/Response preview:/);
    }
  });

  it('truncates long malformed JSON previews to 240 characters', async () => {
    const longTail = `{"status":"ok"} ${'x'.repeat(260)}`;
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(longTail, { status: 200 }));

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected malformed JSON request to throw.');
    } catch (error) {
      expect((error as Error).message).toContain('Response preview:');
      expect((error as Error).message).toContain('...');
    }
  });

  it('includes parser syntax details in malformed JSON errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"status"', { status: 200 }));

    await expect(fetchApi('http://example.test/endpoint')).rejects.toThrow(/Expected ':' after property name/i);
  });

  it('falls back to a generic parse message when parsing throws a non-Error value', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"status":"ok"}', { status: 200 }));
    vi.spyOn(JSON, 'parse').mockImplementation(() => {
      // Exercise the non-Error fallback branch in fetchApi.
      // eslint-disable-next-line @typescript-eslint/only-throw-error
      throw 'boom';
    });

    await expect(fetchApi('http://example.test/endpoint')).rejects.toThrow('Unknown JSON parse error.');
  });

  it('throws the non-ok response body for fetchRequiredApi requests', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('backend unavailable', { status: 503 }));

    await expect(fetchRequiredApi('http://example.test/endpoint')).rejects.toThrow(
      'Request to http://example.test/endpoint failed (503): backend unavailable',
    );
  });
});

describe('fetchApi HTTPError', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetConfigCache();
  });

  it('throws a typed HTTPError carrying status and endpoint on a non-ok response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('not found', { status: 404 }));

    try {
      await fetchApi('http://example.test/media/40412');
      throw new Error('Expected a non-ok response to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect(error).toBeInstanceOf(Error);
      expect((error as HTTPError).status).toBe(404);
      expect((error as HTTPError).endpoint).toBe('http://example.test/media/40412');
    }
  });

  it('preserves the legacy message format so downstream (404)/(409) message sniffs keep working', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('missing', { status: 404 }));

    await expect(fetchApi('http://example.test/endpoint')).rejects.toThrow(
      'Request to http://example.test/endpoint failed (404): missing',
    );
  });

  it('parses Retry-After (delta-seconds) into retryAfterSeconds', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('slow down', { status: 429, headers: { 'Retry-After': '5' } }),
    );

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected a 429 to throw.');
    } catch (error) {
      expect((error as HTTPError).status).toBe(429);
      expect((error as HTTPError).retryAfterSeconds).toBe(5);
    }
  });

  it('leaves retryAfterSeconds undefined for a 503 without a Retry-After header', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('overloaded', { status: 503 }));

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected a 503 to throw.');
    } catch (error) {
      expect((error as HTTPError).status).toBe(503);
      expect((error as HTTPError).retryAfterSeconds).toBeUndefined();
    }
  });

  it('throws a ResponseParseError (not an HTTPError) for malformed JSON on a 2xx', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"status":"ok"} trailing-debug-output', { status: 200 }),
    );

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected malformed JSON to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(ResponseParseError);
      expect(error).toBeInstanceOf(Error);
      expect(error).not.toBeInstanceOf(HTTPError);
    }
  });
});

describe('parseRetryAfter', () => {
  it('parses non-negative delta-seconds', () => {
    expect(parseRetryAfter('5')).toBe(5);
    expect(parseRetryAfter('0')).toBe(0);
    expect(parseRetryAfter('120')).toBe(120);
  });

  it('returns undefined for missing or malformed values (never NaN)', () => {
    expect(parseRetryAfter(null)).toBeUndefined();
    expect(parseRetryAfter('')).toBeUndefined();
    expect(parseRetryAfter('  ')).toBeUndefined();
    expect(parseRetryAfter('soon')).toBeUndefined();
    expect(parseRetryAfter('-3')).toBeUndefined();
    expect(parseRetryAfter('5.5')).toBeUndefined();
  });

  it('returns undefined for a past HTTP-date (never 0)', () => {
    expect(parseRetryAfter('Thu, 01 Jan 1970 00:00:00 GMT')).toBeUndefined();
  });
});

describe('fetchApi HTTP-date Retry-After [FEBT1-W2C-08]', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-02T12:00:00.000Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    resetConfigCache();
  });

  it('parses a future HTTP-date Retry-After into retryAfterSeconds on a 503', async () => {
    const retryAfter = new Date(Date.now() + 30_000).toUTCString();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('overloaded', { status: 503, headers: { 'Retry-After': retryAfter } }),
    );

    try {
      await fetchApi(REST_URL);
      throw new Error('Expected a 503 to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect((error as HTTPError).status).toBe(503);
      expect((error as HTTPError).retryAfterSeconds).toBe(30);
    }
  });

  it('past HTTP-date Retry-After yields undefined, not 0 (FEBT1-W2A-03 — flips when F2 lands)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('overloaded', {
        status: 503,
        headers: { 'Retry-After': 'Thu, 01 Jan 1970 00:00:00 GMT' },
      }),
    );

    try {
      await fetchApi(REST_URL);
      throw new Error('Expected a 503 to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect((error as HTTPError).retryAfterSeconds).toBeUndefined();
    }
  });

  it('429 with a past HTTP-date Retry-After falls back to exponential backoff, not 0', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('slow down', {
        status: 429,
        headers: { 'Retry-After': 'Thu, 01 Jan 1970 00:00:00 GMT' },
      }),
    );

    try {
      await fetchApi(REST_URL);
      throw new Error('Expected a 429 to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect((error as HTTPError).status).toBe(429);
      expect((error as HTTPError).retryAfterSeconds).toBeUndefined();
      const delay = getRetryDelay(0, error, () => 1);
      expect(delay).not.toBe(0);
      expect(delay).toBe(1_000);
    }
  });
});

// The HTTP-date branch had no coverage at all (FEBT1-W2C-08): deleting
// http.ts's `Date.parse` arm left every test above green, which is exactly how
// the past-date → 0s hot-retry bug (FEBT1-W2A-03) survived review.
describe('parseRetryAfter HTTP-date branch', () => {
  const FROZEN_NOW = Date.UTC(2026, 0, 1, 0, 0, 0); // Thu, 01 Jan 2026 00:00:00 GMT

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(FROZEN_NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('converts a future RFC 7231 HTTP-date to delta-seconds', () => {
    expect(parseRetryAfter('Thu, 01 Jan 2026 00:02:00 GMT')).toBe(120);
  });

  it('rounds a sub-second remainder UP so the client never retries early', () => {
    vi.setSystemTime(FROZEN_NOW + 500); // 119.5s of wait left
    expect(parseRetryAfter('Thu, 01 Jan 2026 00:02:00 GMT')).toBe(120);
  });

  it('treats a past HTTP-date as absent, never as 0 (retry-storm pin)', () => {
    // 0 would mark the error a cooldown AND collapse backoff to an immediate
    // hot loop; absent falls back to exponential backoff.
    expect(parseRetryAfter('Thu, 01 Jan 1970 00:00:00 GMT')).toBeUndefined();
    expect(parseRetryAfter('Wed, 21 Oct 2015 07:28:00 GMT')).toBeUndefined();
  });

  it('treats an HTTP-date equal to now as absent', () => {
    expect(parseRetryAfter('Thu, 01 Jan 2026 00:00:00 GMT')).toBeUndefined();
  });
});

describe('Retry-After HTTP-date reaches the classified error', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
    vi.useFakeTimers();
    vi.setSystemTime(Date.UTC(2026, 0, 1, 0, 0, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    resetConfigCache();
  });

  it('503 + future HTTP-date → retryAfterSeconds set and classified as a cooldown', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('overloaded', {
        status: 503,
        headers: { 'Retry-After': 'Thu, 01 Jan 2026 00:00:30 GMT' },
      }),
    );

    await expect(fetchApi(REST_URL)).rejects.toMatchObject({ retryAfterSeconds: 30 });
  });

  it('503 + past HTTP-date → no retryAfterSeconds, so it is NOT a cooldown', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('overloaded', {
        status: 503,
        headers: { 'Retry-After': 'Wed, 21 Oct 2015 07:28:00 GMT' },
      }),
    );

    const error = await fetchApi(REST_URL).then(
      () => {
        throw new Error('expected 503 to reject');
      },
      (err: unknown) => err,
    );

    expect(error).toBeInstanceOf(HTTPError);
    expect((error as HTTPError).retryAfterSeconds).toBeUndefined();
    expect(isCooldown(error)).toBe(false);
  });
});

describe('fetchApi auth expiry seam (UXP-NET-2 slice 2)', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetConfigCache();
  });

  it('nonce-403 → refresh → retry succeeds: 2 REST + 1 ajax; retry carries NEW header [RES-01][API-08]', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (isAjaxCall(input)) {
        return Promise.resolve(new Response(FRESH_NONCE, { status: 200 }));
      }
      const headers = (init?.headers ?? {}) as Record<string, string>;
      if (headers['X-WP-Nonce'] === FRESH_NONCE) {
        return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
      }
      return Promise.resolve(new Response(nonce403Body, { status: 403 }));
    });

    const result = await fetchApi<{ ok: boolean }>(REST_URL, { restNonce: STALE_NONCE });

    expect(result).toEqual({ ok: true });
    const restCalls = fetchMock.mock.calls.filter(([url]) => isRestCall(url));
    const ajaxCalls = fetchMock.mock.calls.filter(([url]) => isAjaxCall(url));
    expect(restCalls).toHaveLength(2);
    expect(ajaxCalls).toHaveLength(1);
    const retryHeaders = (restCalls[1]?.[1]?.headers ?? {}) as Record<string, string>;
    expect(retryHeaders['X-WP-Nonce']).toBe(FRESH_NONCE);
    expect(getNonce()).toBe(FRESH_NONCE);
  });

  it('non-nonce 403 → ordinary HTTPError, 1 fetch, 0 ajax [API-08]', async () => {
    const body = JSON.stringify({ code: 'rest_forbidden', message: 'nope' });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { status: 403 }));

    await expect(fetchApi(REST_URL)).rejects.toBeInstanceOf(HTTPError);
    expect(fetchMock.mock.calls.filter(([url]) => isRestCall(url))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(0);
  });

  it('non-JSON 403 body → ordinary HTTPError, no refresh', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('<html>WAF</html>', { status: 403 }));

    try {
      await fetchApi(REST_URL);
      throw new Error('expected throw');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect(error).not.toBeInstanceOf(AuthExpiredError);
    }
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(0);
  });

  it('401 rest_not_logged_in → AuthExpiredError, 0 ajax calls', async () => {
    const body = JSON.stringify({ code: 'rest_not_logged_in', message: 'logged out' });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { status: 401 }));

    try {
      await fetchApi(REST_URL);
      throw new Error('expected throw');
    } catch (error) {
      expect(error).toBeInstanceOf(AuthExpiredError);
      expect(error).not.toBeInstanceOf(HTTPError);
      expect((error as AuthExpiredError).status).toBe(401);
      expect((error as AuthExpiredError).endpoint).toBe(REST_URL);
      expect((error as AuthExpiredError).name).toBe('AuthExpiredError');
    }
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(0);
  });

  it('second nonce-403 → AuthExpiredError, exactly 2 REST fetches', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (isAjaxCall(input)) {
        return Promise.resolve(new Response(FRESH_NONCE, { status: 200 }));
      }
      return Promise.resolve(new Response(nonce403Body, { status: 403 }));
    });

    await expect(fetchApi(REST_URL)).rejects.toBeInstanceOf(AuthExpiredError);
    expect(fetchMock.mock.calls.filter(([url]) => isRestCall(url))).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(1);
  });

  it('refresh rejection → AuthExpiredError', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (isAjaxCall(input)) {
        return Promise.resolve(new Response('0', { status: 400 }));
      }
      return Promise.resolve(new Response(nonce403Body, { status: 403 }));
    });

    await expect(fetchApi(REST_URL)).rejects.toBeInstanceOf(AuthExpiredError);
    expect(fetchMock.mock.calls.filter(([url]) => isRestCall(url))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(1);
  });

  it('concurrent 403s → 1 refresh [RES-06]', async () => {
    let ajaxCount = 0;
    let restHits = 0;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (isAjaxCall(input)) {
        ajaxCount += 1;
        await new Promise((r) => setTimeout(r, 20));
        return new Response(FRESH_NONCE, { status: 200 });
      }
      restHits += 1;
      const headers = (init?.headers ?? {}) as Record<string, string>;
      if (headers['X-WP-Nonce'] === FRESH_NONCE) {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response(nonce403Body, { status: 403 });
    });

    const results = await Promise.all([fetchApi(REST_URL), fetchApi(REST_URL), fetchApi(REST_URL)]);
    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(ajaxCount).toBe(1);
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(1);
    // 3 first attempts + 3 retries
    expect(restHits).toBe(6);
  });

  it('aborted signal mid-refresh → abort surfaced, no retry', async () => {
    const controller = new AbortController();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      if (isAjaxCall(input)) {
        controller.abort();
        await new Promise((r) => setTimeout(r, 5));
        return new Response(FRESH_NONCE, { status: 200 });
      }
      return new Response(nonce403Body, { status: 403 });
    });

    await expect(fetchApi(REST_URL, { signal: controller.signal })).rejects.toMatchObject({
      name: 'AbortError',
    });
    expect(fetchMock.mock.calls.filter(([url]) => isRestCall(url))).toHaveLength(1);
  });

  it('UXP-NET-1 pin: 429 → fetch once, zero ajax, HTTPError status/retryAfterSeconds/message unchanged', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('slow down', { status: 429, headers: { 'Retry-After': '5' } }),
    );

    try {
      await fetchApi(REST_URL);
      throw new Error('expected throw');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect((error as HTTPError).status).toBe(429);
      expect((error as HTTPError).retryAfterSeconds).toBe(5);
      expect((error as HTTPError).message).toBe(
        `Request to ${REST_URL} failed (429): slow down`,
      );
    }
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(0);
  });

  it('UXP-NET-1 pin: 503+Retry-After → fetch once, zero ajax, HTTPError fields unchanged', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('overloaded', { status: 503, headers: { 'Retry-After': '12' } }),
    );

    try {
      await fetchApi(REST_URL);
      throw new Error('expected throw');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect((error as HTTPError).status).toBe(503);
      expect((error as HTTPError).retryAfterSeconds).toBe(12);
      expect((error as HTTPError).message).toBe(
        `Request to ${REST_URL} failed (503): overloaded`,
      );
    }
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(0);
  });
});

describe('fetchApi review-fix discrimination pins (UXPNET2-BR-04/05)', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
  });

  afterEach(() => {
    resetConfigCache();
  });

  it('first attempt uses options.restNonce over a fresher cached nonce (BR-05) [TEST-15]', async () => {
    resetConfigCache();
    seedConfig(FRESH_NONCE); // cached getNonce() is FRESH…
    const restHeaders: Record<string, string>[] = [];
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      if (isAjaxCall(url)) {
        return Promise.resolve(new Response(FRESH_NONCE, { status: 200 }));
      }
      restHeaders.push((init?.headers ?? {}) as Record<string, string>);
      return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    });

    // …but the caller explicitly passes STALE — the first wire header must be STALE.
    await fetchApi<{ ok: boolean }>(REST_URL, { restNonce: STALE_NONCE });
    expect(restHeaders[0]['X-WP-Nonce']).toBe(STALE_NONCE);
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(0);
  });

  it('omitted restNonce resolves the live cached nonce at send time (BR-05) [TEST-15]', async () => {
    resetConfigCache();
    seedConfig(FRESH_NONCE);
    const restHeaders: Record<string, string>[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
      restHeaders.push((init?.headers ?? {}) as Record<string, string>);
      return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    });

    await fetchApi<{ ok: boolean }>(REST_URL);
    expect(restHeaders[0]['X-WP-Nonce']).toBe(FRESH_NONCE);
  });

  it('abort landing during a FAILING refresh surfaces AbortError, never session expiry (BR-04) [TEST-15]', async () => {
    const controller = new AbortController();
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      if (isAjaxCall(url)) {
        controller.abort();
        return Promise.resolve(new Response('0', { status: 400 })); // refresh fails while abort lands
      }
      return Promise.resolve(new Response(nonce403Body, { status: 403 }));
    });

    await expect(
      fetchApi<{ ok: boolean }>(REST_URL, { restNonce: STALE_NONCE, signal: controller.signal }),
    ).rejects.toSatisfy(
      (err: unknown) => err instanceof Error && isAppError(err) && err.name === 'AbortError' && err._tag === 'abort',
    );
  });
});

// FEBT1-W2A-02: a nonce refresh that never got an answer says nothing about the
// session. Collapsing it into AuthExpiredError showed a logged-in user "your
// session expired" and pinned the request non-retryable.
describe('fetchApi nonce-refresh failure discrimination', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetConfigCache();
  });

  const nonce403ThenRefresh = (refresh: () => Promise<Response>): void => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      if (isAjaxCall(url)) {
        return refresh();
      }
      return Promise.resolve(new Response(nonce403Body, { status: 403 }));
    });
  };

  it('refresh transport failure → NonceRefreshFailedError, not session expiry', async () => {
    nonce403ThenRefresh(() => Promise.reject(new TypeError('Failed to fetch')));

    const error = await fetchApi(REST_URL).then(
      () => {
        throw new Error('expected nonce-403 flow to reject');
      },
      (err: unknown) => err,
    );

    expect(error).toBeInstanceOf(NonceRefreshFailedError);
    expect(error).not.toBeInstanceOf(AuthExpiredError);
    expect((error as NonceRefreshFailedError).causeStatus).toBeUndefined();
    expect(classifyError(error)._tag).toBe('nonce_refresh');
  });

  it('refresh timeout → NonceRefreshFailedError, not session expiry', async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) => {
        if (isAjaxCall(url)) {
          return new Promise<Response>((_resolve, reject) => {
            (init?.signal as AbortSignal | undefined)?.addEventListener('abort', () => {
              reject(new DOMException('The operation was aborted.', 'AbortError'));
            });
          });
        }
        return Promise.resolve(new Response(nonce403Body, { status: 403 }));
      });

      let settled: unknown;
      void fetchApi(REST_URL).then(
        () => {
          throw new Error('expected nonce-403 flow to reject');
        },
        (err: unknown) => {
          settled = err;
        },
      );

      await vi.advanceTimersByTimeAsync(NONCE_REFRESH_TIMEOUT_MS + 1);

      expect(settled).toBeInstanceOf(NonceRefreshFailedError);
      expect(settled).not.toBeInstanceOf(AuthExpiredError);
      expect(classifyError(settled)._tag).toBe('nonce_refresh');
    } finally {
      vi.useRealTimers();
    }
  });

  it('refresh that DID get a verdict (WP answers 0/-1) stays AuthExpiredError', async () => {
    nonce403ThenRefresh(() => Promise.resolve(new Response('-1', { status: 403 })));

    const error = await fetchApi(REST_URL).then(
      () => {
        throw new Error('expected nonce-403 flow to reject');
      },
      (err: unknown) => err,
    );

    expect(error).toBeInstanceOf(AuthExpiredError);
    expect((error as AuthExpiredError).status).toBe(403);
    expect(classifyError(error)._tag).toBe('auth_expired');
  });

  it('missing ajaxUrl (deploy skew) → NonceRefreshFailedError, not session expiry', async () => {
    resetConfigCache();
    vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    registerConfig({ nonce: STALE_NONCE, ajaxUrl: '', endpoints: {} });
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(nonce403Body, { status: 403 }));

    await expect(fetchApi(REST_URL)).rejects.toBeInstanceOf(NonceRefreshFailedError);
    // No ajax round-trip was even attempted.
    expect(fetchMock.mock.calls.filter(([url]) => isAjaxCall(url))).toHaveLength(0);
  });
});

describe('AuthExpiredError', () => {
  it('preserves exact 401 and 403 constructor status (M4 / F2)', () => {
    expect(new AuthExpiredError({ endpoint: REST_URL, status: 401 }).status).toBe(401);
    expect(new AuthExpiredError({ endpoint: REST_URL, status: 403 }).status).toBe(403);
  });
});

describe('fetchApi nonce-refresh failure is not session expiry [FEBT1-W2A-02]', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    resetConfigCache();
  });

  it('transport failure during nonce refresh is nonce_refresh, not auth_expired', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (isAjaxCall(input)) {
        return Promise.reject(new TypeError('Failed to fetch'));
      }
      return Promise.resolve(new Response(nonce403Body, { status: 403 }));
    });

    try {
      await fetchApi(REST_URL);
      throw new Error('expected throw');
    } catch (error) {
      expect(error).toBeInstanceOf(NonceRefreshFailedError);
      expect(error).not.toBeInstanceOf(AuthExpiredError);
      expect(classifyError(error)._tag).toBe('nonce_refresh');
      expect(classifyError(error)._tag).not.toBe('auth_expired');
      expect(shouldRetryRequest(0, error)).toBe(true);
      expect(toUserMessage(error, 'safe fallback')).toBe('Network error — check your connection');
      expect(toUserMessage(error, 'safe fallback')).not.toBe(SPA_SESSION_EXPIRED_COPY.sessionExpired);
    }
  });

  it('abort during nonce refresh is abort, not auth_expired', async () => {
    const abort = new DOMException('The operation was aborted.', 'AbortError');
    vi.spyOn(configApi, 'refreshRestNonce').mockRejectedValue(abort);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(nonce403Body, { status: 403 }));

    try {
      await fetchApi(REST_URL);
      throw new Error('expected throw');
    } catch (error) {
      expect(error).not.toBeInstanceOf(AuthExpiredError);
      expect(classifyError(error)._tag).toBe('abort');
      expect(classifyError(error)._tag).not.toBe('auth_expired');
      expect(shouldRetryRequest(0, error)).toBe(false);
    }
  });
});

const hungFetch = (): void => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => {
    return new Promise((_resolve, reject) => {
      const signal = init?.signal;
      if (!signal) {
        return;
      }
      if (signal.aborted) {
        reject(signal.reason ?? new DOMException('The operation was aborted.', 'AbortError'));
        return;
      }
      signal.addEventListener(
        'abort',
        () => {
          const reason: unknown = signal.reason;
          if (reason instanceof DOMException) {
            reject(reason);
            return;
          }
          reject(new DOMException('The operation was aborted.', 'AbortError'));
        },
        { once: true },
      );
    });
  });
};

describe('fetchApi default timeout [E-04]', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    resetConfigCache();
  });

  // Every deadline assertion below is relative to DEFAULT_FETCH_TIMEOUT_MS, so
  // shrinking the constant kept them all green (FEBT1-W2C-09). Pin the value.
  it('pins the default deadline at 5 minutes', () => {
    expect(DEFAULT_FETCH_TIMEOUT_MS).toBe(300_000);
  });

  it('rejects a hung fetch within the default deadline as a classified timeout', async () => {
    hungFetch();

    let rejected: unknown;
    void fetchApi(REST_URL).then(
      () => {
        throw new Error('expected hung fetch to reject');
      },
      (error: unknown) => {
        rejected = error;
      },
    );

    // TEST-15 / FEBT1-W2C-09: pin the RES-02 backstop with a literal so a
    // DEFAULT_FETCH_TIMEOUT_MS self-comparison cannot absorb a 300_000→60_000 mutant.
    expect(DEFAULT_FETCH_TIMEOUT_MS).toBe(300_000);
    await vi.advanceTimersByTimeAsync(300_000 - 1);
    expect(rejected).toBeUndefined();

    await vi.advanceTimersByTimeAsync(1);

    expect(rejected).toBeInstanceOf(Error);
    expect(isAppError(rejected)).toBe(true);
    expect((rejected as Error).name).toBe('TimeoutError');
    expect(isAppError(rejected) && rejected._tag).toBe('timeout');
  });

  it('lets an explicit timeoutMs override the default', async () => {
    hungFetch();

    let rejected: unknown;
    void fetchApi(REST_URL, { timeoutMs: 50 }).then(
      () => {
        throw new Error('expected timeoutMs override to reject');
      },
      (error: unknown) => {
        rejected = error;
      },
    );

    await vi.advanceTimersByTimeAsync(49);
    expect(rejected).toBeUndefined();

    await vi.advanceTimersByTimeAsync(1);

    expect(classifyError(rejected)._tag).toBe('timeout');
    expect((rejected as DOMException).name).toBe('TimeoutError');
  });

  it('still aborts when a caller-supplied signal aborts early', async () => {
    hungFetch();
    const controller = new AbortController();

    const pending = fetchApi(REST_URL, { signal: controller.signal, timeoutMs: 60_000 });
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('does not abort a fast successful response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );

    const result = await fetchApi<{ ok: boolean }>(REST_URL);
    expect(result).toEqual({ ok: true });
  });
});

describe('fetchApi throw boundary emits tagged Errors [FEBT1-W2A-01]', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    resetConfigCache();
  });

  const expectThrownAppError = async (
    run: () => Promise<unknown>,
    tag: 'http' | 'parse' | 'auth_expired' | 'transport' | 'timeout' | 'abort',
  ): Promise<Error> => {
    try {
      await run();
      throw new Error('expected fetchApi to throw');
    } catch (error) {
      expect(error).toBeInstanceOf(Error);
      expect(isAppError(error)).toBe(true);
      if (!(error instanceof Error)) {
        throw new Error('expected thrown value to be an Error instance');
      }
      if (!isAppError(error)) {
        throw new Error('expected thrown value to already be an AppError');
      }
      expect(error._tag).toBe(tag);
      expect(error.stack).toEqual(expect.any(String));
      expect(error.stack?.length).toBeGreaterThan(0);
      return error;
    }
  };

  it.each([
    {
      name: '4xx → http',
      tag: 'http' as const,
      setup: (): (() => Promise<unknown>) => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('missing', { status: 404 }));
        return () => fetchApi(REST_URL);
      },
    },
    {
      name: 'non-JSON body → parse',
      tag: 'parse' as const,
      setup: (): (() => Promise<unknown>) => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{', { status: 200 }));
        return () => fetchApi(REST_URL);
      },
    },
    {
      name: 'WP logged-out sentinel → auth_expired',
      tag: 'auth_expired' as const,
      setup: (): (() => Promise<unknown>) => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
          new Response(JSON.stringify({ code: 'rest_not_logged_in', message: 'logged out' }), {
            status: 401,
          }),
        );
        return () => fetchApi(REST_URL);
      },
    },
    {
      name: 'transport failure → transport',
      tag: 'transport' as const,
      setup: (): (() => Promise<unknown>) => {
        vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
        return () => fetchApi(REST_URL);
      },
    },
    {
      name: 'hung fetch → timeout',
      tag: 'timeout' as const,
      setup: (): (() => Promise<unknown>) => {
        vi.useFakeTimers();
        hungFetch();
        return async () => {
          let rejected: unknown;
          void fetchApi(REST_URL).then(
            () => {
              throw new Error('expected hung fetch to reject');
            },
            (error: unknown) => {
              rejected = error;
            },
          );
          await vi.advanceTimersByTimeAsync(300_000);
          if (rejected !== undefined) {
            if (!(rejected instanceof Error)) {
              throw new TypeError(`hung fetch rejected with a non-Error of type ${typeof rejected}`);
            }
            // Rethrow the original instance: the caller asserts on its AppError tag.
            throw rejected;
          }
          throw new Error('hung fetch did not reject');
        };
      },
    },
    {
      name: 'user cancel → abort',
      tag: 'abort' as const,
      setup: (): (() => Promise<unknown>) => {
        hungFetch();
        const controller = new AbortController();
        return () => {
          const pending = fetchApi(REST_URL, { signal: controller.signal, timeoutMs: 60_000 });
          controller.abort();
          return pending;
        };
      },
    },
  ])('$name is instanceof Error, isAppError, and keeps a stack', async ({ tag, setup }) => {
    const run = setup();
    await expectThrownAppError(run, tag);
  });
});
