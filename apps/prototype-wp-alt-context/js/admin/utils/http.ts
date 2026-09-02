import { getNonce, isNonceRefreshAuthRejection, NonceRefreshFailedError, refreshRestNonce } from '../api/config';

/** Backstop deadline when a caller does not pass `timeoutMs` (RES-02). */
export const DEFAULT_FETCH_TIMEOUT_MS = 300_000;

export interface HTTPOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  restNonce?: string;
  signal?: AbortSignal;
  /** Override `DEFAULT_FETCH_TIMEOUT_MS`. Composed with `signal` when both are set. */
  timeoutMs?: number;
}

export class HTTPError extends Error {
  readonly status: number;
  readonly retryAfterSeconds: number | undefined;
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
    this.endpoint = endpoint;
    this.bodyPreview = bodyPreview;
  }
}

export class ResponseParseError extends Error {
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
export class AuthExpiredError extends Error {
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
 * Parse Retry-After header value to delay seconds.
 * Accepts delta-seconds or HTTP-date; never returns NaN.
 */
export const parseRetryAfter = (value: string | null): number | undefined => {
  if (value === null) {
    return undefined;
  }
  const trimmed = value.trim();
  if (trimmed === '') {
    return undefined;
  }
  if (/^\d+$/.test(trimmed)) {
    const seconds = Number(trimmed);
    if (Number.isFinite(seconds) && seconds >= 0) {
      return seconds;
    }
    return undefined;
  }
  // Negative / non-integer numerics are not delta-seconds and must not fall through
  // to Date.parse (e.g. Date.parse('-3') can yield a past timestamp → 0s).
  if (/^[+-]?\d+(\.\d+)?$/.test(trimmed)) {
    return undefined;
  }
  const t = Date.parse(trimmed);
  if (!Number.isNaN(t)) {
    const seconds = Math.ceil((t - Date.now()) / 1000);
    // Past or present HTTP-date is header-absent, not 0 — otherwise a 503
    // becomes an immediate retry loop and a 429 skips exponential backoff.
    return seconds > 0 ? seconds : undefined;
  }
  return undefined;
};

/**
 * Strip trailing slash from a URL path.
 */
export const stripTrailingSlash = (value: string): string => (value.endsWith('/') ? value.slice(0, -1) : value);

const buildResponsePreview = (rawBody: string): string => {
  const normalized = rawBody.replace(/\s+/g, ' ').trim();
  if (normalized.length <= 240) {
    return normalized;
  }
  return `${normalized.slice(0, 240)}...`;
};

const buildHeaders = (options: HTTPOptions, restNonce: string | undefined): Record<string, string> => {
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };

  if (options.method && options.method !== 'GET') {
    headers['Content-Type'] = 'application/json';
  }

  if (restNonce) {
    headers['X-WP-Nonce'] = restNonce;
  }

  return headers;
};

const parseErrorCode = (errorText: string): string | undefined => {
  try {
    const parsed: unknown = JSON.parse(errorText);
    if (parsed && typeof parsed === 'object' && 'code' in parsed) {
      const code = parsed.code;
      if (typeof code === 'string') {
        return code;
      }
    }
  } catch {
    // non-JSON body (WAF/proxy) → no code
  }
  return undefined;
};

const throwIfAborted = (signal: AbortSignal | undefined): void => {
  if (signal?.aborted) {
    const reason: unknown = signal.reason;
    if (reason instanceof DOMException) {
      throw reason;
    }
    throw new DOMException('The operation was aborted.', 'AbortError');
  }
};

const abortReason = (reason: unknown): DOMException =>
  reason instanceof DOMException ? reason : new DOMException('The operation was aborted.', 'AbortError');

const ABORT_LIKE_NAMES = new Set(['AbortError', 'TimeoutError']);

const isAbortLikeError = (error: unknown): boolean => {
  if (typeof error !== 'object' || error === null) {
    return false;
  }
  const name = (error as { name?: unknown }).name;
  return typeof name === 'string' && ABORT_LIKE_NAMES.has(name);
};

const resolveTimeoutMs = (timeoutMs: number | undefined): number => {
  if (timeoutMs === undefined || !Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return DEFAULT_FETCH_TIMEOUT_MS;
  }
  return timeoutMs;
};

const createTimeoutSignal = (timeoutMs: number): { signal: AbortSignal; cancel: () => void } => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    controller.abort(new DOMException('The operation timed out.', 'TimeoutError'));
  }, timeoutMs);
  return {
    signal: controller.signal,
    cancel: (): void => {
      clearTimeout(timeoutId);
    },
  };
};

const composeAbortSignals = (signals: AbortSignal[]): AbortSignal => {
  const anyFn = (AbortSignal as unknown as { any?: (values: AbortSignal[]) => AbortSignal }).any;
  if (typeof anyFn === 'function') {
    return anyFn(signals);
  }
  const controller = new AbortController();
  for (const signal of signals) {
    if (signal.aborted) {
      controller.abort(abortReason(signal.reason));
      return controller.signal;
    }
    signal.addEventListener(
      'abort',
      () => {
        if (!controller.signal.aborted) {
          controller.abort(abortReason(signal.reason));
        }
      },
      { once: true },
    );
  }
  return controller.signal;
};

const throwHttpError = (
  endpoint: string,
  status: number,
  errorText: string,
  retryAfterHeader: string | null,
): never => {
  const retryAfterSeconds = parseRetryAfter(retryAfterHeader);
  throw new HTTPError({
    status,
    retryAfterSeconds,
    endpoint,
    bodyPreview: buildResponsePreview(errorText),
    message: `Request to ${endpoint} failed (${status}): ${errorText}`,
  });
};

const parseSuccessBody = async <T>(response: Response, endpoint: string): Promise<T | undefined> => {
  // 204/205 intentionally return no body.
  if (response.status === 204 || response.status === 205) {
    return undefined;
  }

  const rawBody = await response.text();
  if (rawBody.trim() === '') {
    return undefined;
  }

  try {
    const payload: unknown = JSON.parse(rawBody);
    return payload as T;
  } catch (error) {
    const preview = buildResponsePreview(rawBody);
    const syntaxDetail = error instanceof Error ? error.message : 'Unknown JSON parse error.';
    throw new ResponseParseError({
      status: response.status,
      endpoint,
      bodyPreview: preview,
      message: `Request to ${endpoint} returned malformed JSON (${response.status}): ${syntaxDetail}. Response preview: ${preview}`,
    });
  }
};

export const fetchApi = async <T>(endpoint: string, options: HTTPOptions = {}): Promise<T | undefined> => {
  const method = options.method ?? 'GET';
  const body = options.body ? JSON.stringify(options.body) : null;
  const timeout = createTimeoutSignal(resolveTimeoutMs(options.timeoutMs));
  const signal = options.signal ? composeAbortSignals([options.signal, timeout.signal]) : timeout.signal;

  const send = async (restNonce: string | undefined): Promise<Response> =>
    fetch(endpoint, {
      method,
      headers: buildHeaders(options, restNonce),
      body,
      signal,
    });

  try {
    throwIfAborted(signal);

    // First attempt: caller-supplied nonce or live cached nonce ([WP-02]/[SECD-03]).
    const firstNonce = options.restNonce ?? getNonce();
    const response = await send(firstNonce);

    if (response.ok) {
      return parseSuccessBody<T>(response, endpoint);
    }

    const errorText = await response.text();
    const retryAfterHeader = response.headers.get('Retry-After');

    if (response.status === 401) {
      const code = parseErrorCode(errorText);
      if (code === 'rest_not_logged_in') {
        throw new AuthExpiredError({ endpoint, status: 401 });
      }
      throwHttpError(endpoint, response.status, errorText, retryAfterHeader);
    }

    if (response.status === 403) {
      const code = parseErrorCode(errorText);
      if (code !== 'rest_cookie_invalid_nonce') {
        // Non-nonce 403 or non-JSON body → ordinary HTTPError, no refresh ([API-08]).
        throwHttpError(endpoint, response.status, errorText, retryAfterHeader);
      }

      // Nonce-403: auth phase rejected before route execution — one safe retry ([RES-01][API-02]).
      throwIfAborted(signal);

      try {
        await refreshRestNonce();
      } catch (error) {
        // An abort that landed while the refresh was failing is an abort, not
        // session expiry — never surface recovery UI for an unmounted caller.
        throwIfAborted(signal);
        if (isAbortLikeError(error)) {
          throw error;
        }
        // Transport / timeout refresh failures are nonce_refresh (retryable
        // network copy), not session expiry. Only WP logged-out sentinels
        // become AuthExpiredError.
        if (error instanceof NonceRefreshFailedError && !isNonceRefreshAuthRejection(error)) {
          throw error;
        }
        throw new AuthExpiredError({ endpoint, status: 403 });
      }

      throwIfAborted(signal);

      // Retry always uses the live refreshed nonce — never the stale option ([API-08]).
      const retryResponse = await send(getNonce());

      if (retryResponse.ok) {
        return parseSuccessBody<T>(retryResponse, endpoint);
      }

      const retryText = await retryResponse.text();
      const retryCode = parseErrorCode(retryText);
      if (retryResponse.status === 403 && retryCode === 'rest_cookie_invalid_nonce') {
        throw new AuthExpiredError({ endpoint, status: 403 });
      }
      if (retryResponse.status === 401 && retryCode === 'rest_not_logged_in') {
        throw new AuthExpiredError({ endpoint, status: 401 });
      }

      throwHttpError(endpoint, retryResponse.status, retryText, retryResponse.headers.get('Retry-After'));
    }

    // All other statuses: byte-identical to pre-UXP-NET-2 behaviour.
    throwHttpError(endpoint, response.status, errorText, retryAfterHeader);
  } finally {
    timeout.cancel();
  }
};

/**
 * Fetch API payload and fail loudly when a body was expected but missing.
 */
export const fetchRequiredApi = async <T>(endpoint: string, options: HTTPOptions = {}): Promise<T> => {
  const payload = await fetchApi<T>(endpoint, options);
  if (payload === undefined) {
    throw new Error(`Request to ${endpoint} succeeded but returned an empty response body.`);
  }
  return payload;
};
