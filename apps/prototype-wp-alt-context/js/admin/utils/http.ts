export interface HTTPOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  restNonce?: string;
}

/**
 * Strip trailing slash from a URL path.
 */
export const stripTrailingSlash = (value: string): string => (value.endsWith('/') ? value.slice(0, -1) : value);

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

export const fetchApi = async <T>(endpoint: string, options: HTTPOptions = {}): Promise<T> => {
  const response = await fetch(endpoint, {
    method: options.method ?? 'GET',
    headers: buildHeaders(options),
    body: options.body ? JSON.stringify(options.body) : null,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Request to ${endpoint} failed (${response.status}): ${errorText}`);
  }

  const payload: unknown = await response.json();
  return payload as T;
};
