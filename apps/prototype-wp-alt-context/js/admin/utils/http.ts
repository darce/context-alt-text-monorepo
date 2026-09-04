import { getNonce, refreshRestNonce } from '../api/config';
import {
  AbortedRequestError,
  abortLikeTag,
  AuthExpiredError,
  BoundaryError,
  HTTPError,
  isAbortLikeName,
  isTaggedNonceRefreshError,
  NonceRefreshFailedError,
  RequestTimeoutError,
  ResponseParseError,
  toNonceRefreshError,
  TransportError,
  UnknownBoundaryError,
} from './errorTaxonomy';

/**
 * The error vocabulary lives in the leaf module `./errorTaxonomy` so this
 * module's import graph is a DAG (FEBT2-LA-NEW-01; GRPH-02
 * lexicons/graph-theory.md:72). It is re-exported from here unchanged:
 * `utils/http` stays the published home of the boundary-error surface, so no
 * call site outside these two files moved.
 */
export {
  ABORT_LIKE_ERROR_NAME_TAGS,
  AbortedRequestError,
  abortLikeTag,
  AuthExpiredError,
  BoundaryError,
  HTTPError,
  isAbortLikeName,
  NonceRefreshError,
  NonceRefreshFailedError,
  RequestTimeoutError,
  ResponseParseError,
  toNonceRefreshError,
  TransportError,
  UnknownBoundaryError,
} from './errorTaxonomy';

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

/**
 * Parse Retry-After header value to delay seconds.
 * Accepts delta-seconds or HTTP-date; never returns NaN.
 *
 * A value that carries no wait instruction is reported as absent, not as `0` —
 * for the HTTP-date route that means a date at or before now, and for the
 * delta-seconds route it means a literal `Retry-After: 0` (FEBT1-LB-01: only
 * the date route was closed, so a load-shedding server sending `Retry-After: 0`
 * was still hammered immediately by every client at once, in lockstep).
 * Returning `0` would both mark the error as a cooldown and collapse retry
 * backoff to an immediate hot loop against a server that is already struggling
 * (Release It! ch-5: "immediate retry will usually fail again"; retry storm /
 * thundering herd). The date comparison is wall-clock on both sides, so a client
 * whose clock runs ahead of the server's degrades to plain exponential backoff
 * rather than to a zero-delay loop (DDIA ch-8: never derive a duration from
 * wall clocks).
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
    if (Number.isFinite(seconds) && seconds > 0) {
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
    const deltaSeconds = Math.ceil((t - Date.now()) / 1000);
    return deltaSeconds > 0 ? deltaSeconds : undefined;
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

/**
 * Normalise anything thrown inside `fetchApi` into a tagged boundary error.
 *
 * This is the single place that closes the boundary (FEBT1-W2A-01): after it,
 * `isAppError(thrown)` holds for every rejection `fetchApi` can produce, so a
 * caller that forgets `classifyError` still sees a tagged error rather than a
 * raw wire error. Deliberately *not* `classifyError` itself — `appError`
 * imports this module, and calling into it here would resolve the cycle at
 * module-init time (FEBT1-LB-03 (a)).
 */
const toBoundaryError = (error: unknown): unknown => {
  if (error instanceof BoundaryError || isTaggedNonceRefreshError(error)) {
    return error;
  }
  if (error instanceof NonceRefreshFailedError) {
    return toNonceRefreshError(error);
  }
  const abortTag = abortLikeTag(error);
  if (abortTag !== undefined) {
    const message = errorMessage(error);
    return abortTag === 'timeout'
      ? new RequestTimeoutError(error, message)
      : new AbortedRequestError(error, message);
  }
  // Per the Fetch spec a network failure rejects with a TypeError. Inside
  // fetchApi the only call that can reject that way is `fetch` itself, so the
  // tag is earned by provenance rather than by sniffing the browser's message
  // (FEBT-1-W1-E-05).
  if (error instanceof TypeError) {
    return new TransportError(error, error.message);
  }
  return new UnknownBoundaryError(error, errorMessage(error));
};

const errorMessage = (error: unknown): string => {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === 'object' && error !== null) {
    const message: unknown = (error as { message?: unknown }).message;
    if (typeof message === 'string') {
      return message;
    }
  }
  return 'Request failed.';
};

/**
 * True when a nonce refresh never reached a verdict about the session.
 *
 * A timeout or transport failure tells us only that we did not hear back — the
 * session may be perfectly healthy (DDIA ch-8: treat a timed-out call as
 * UNKNOWN, never as a definite negative). Converting it to `AuthExpiredError`
 * shows "your session expired" to a logged-in user and pins the request
 * non-retryable. A refresh that *did* get a response and was rejected
 * (`causeStatus` present — WP admin-ajax answers `-1`/`0` for a dead cookie)
 * is a real verdict and stays session expiry.
 */
const isIndeterminateRefreshFailure = (error: unknown): boolean => {
  if (isAbortLikeName(error)) {
    return true;
  }
  return error instanceof NonceRefreshFailedError && error.causeStatus === undefined;
};

const abortReason = (reason: unknown): DOMException =>
  reason instanceof DOMException ? reason : new DOMException('The operation was aborted.', 'AbortError');

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
      } catch (refreshError) {
        // An abort that landed while the refresh was failing is an abort, not
        // session expiry — never surface recovery UI for an unmounted caller.
        throwIfAborted(signal);
        // A refresh that never got an answer is not proof of session expiry.
        if (isIndeterminateRefreshFailure(refreshError)) {
          throw refreshError;
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
  } catch (error) {
    // The one exit through which every fetchApi rejection passes.
    throw toBoundaryError(error);
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
    const message = `Request to ${endpoint} succeeded but returned an empty response body.`;
    throw new UnknownBoundaryError(undefined, message);
  }
  return payload;
};
