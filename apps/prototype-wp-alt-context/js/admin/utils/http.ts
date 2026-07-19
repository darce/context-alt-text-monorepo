export interface HTTPOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  restNonce?: string;
  signal?: AbortSignal;
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
    return Math.max(0, Math.ceil((t - Date.now()) / 1000));
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

const buildHeaders = (options: HTTPOptions): Record<string, string> => {
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };

  if (options.method && options.method !== 'GET') {
    headers['Content-Type'] = 'application/json';
  }

  if (options.restNonce) {
    headers['X-WP-Nonce'] = options.restNonce;
  }

  return headers;
};

export const fetchApi = async <T>(endpoint: string, options: HTTPOptions = {}): Promise<T | undefined> => {
  const response = await fetch(endpoint, {
    method: options.method ?? 'GET',
    headers: buildHeaders(options),
    body: options.body ? JSON.stringify(options.body) : null,
    signal: options.signal,
  });

  if (!response.ok) {
    const errorText = await response.text();
    const retryAfterSeconds = parseRetryAfter(response.headers.get('Retry-After'));
    throw new HTTPError({
      status: response.status,
      retryAfterSeconds,
      endpoint,
      bodyPreview: buildResponsePreview(errorText),
      message: `Request to ${endpoint} failed (${response.status}): ${errorText}`,
    });
  }

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
