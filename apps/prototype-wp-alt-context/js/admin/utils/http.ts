export interface HTTPOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  restNonce?: string;
  signal?: AbortSignal;
}

/**
 * Typed non-ok HTTP failure. Message format matches the legacy bare Error so
 * catch sites that sniff `.message` keep working.
 * AbortError / timeout rejections are never wrapped — they pass through fetch.
 */
export class HTTPError extends Error {
  readonly status: number;
  readonly retryAfterSeconds: number | null;

  constructor(message: string, status: number, retryAfterSeconds: number | null) {
    super(message);
    this.name = 'HTTPError';
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/**
 * Parse Retry-After as integer delta-seconds only. Absent or unparseable → null.
 * HTTP-date form is intentionally ignored (MVP uses the service's integer seconds).
 */
export const parseRetryAfterSeconds = (value: string | null): number | null => {
  if (value === null) {
    return null;
  }
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) {
    return null;
  }
  const seconds = Number(trimmed);
  if (!Number.isFinite(seconds)) {
    return null;
  }
  return seconds;
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
    const status = response.status;
    const retryAfterSeconds = parseRetryAfterSeconds(response.headers.get('Retry-After'));
    throw new HTTPError(
      `Request to ${endpoint} failed (${status}): ${errorText}`,
      status,
      retryAfterSeconds,
    );
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
    throw new Error(
      `Request to ${endpoint} returned malformed JSON (${response.status}): ${syntaxDetail}. Response preview: ${preview}`,
    );
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
