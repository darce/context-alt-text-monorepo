/**
 * HTTP utility functions for API requests.
 *
 * Provides consistent URL building, header management, and fetch wrappers.
 */

export const handleJsonResponse = async (response: Response): Promise<unknown> => {
    if (response.status === 204) {
        return {};
    }

    const contentType = response.headers.get("Content-Type");

    if (contentType?.includes("application/json")) {
        return response.json();
    }

    const text = await response.text();

    try {
        return JSON.parse(text);
    } catch {
        return {};
    }
};

export const ensureOk = async (response: Response): Promise<Response> => {
    if (!response.ok) {
        const data = await handleJsonResponse(response);
        const message =
            typeof data === "object" && data !== null && "message" in data &&
            typeof (data as { message: unknown }).message === "string"
                ? String((data as { message: string }).message)
                : `Request failed with status ${response.status}`;

        const errorWithData = Object.assign(new Error(message), { data });
        throw errorWithData;
    }

    return response;
};

/**
 * Build API URL with query parameters.
 *
 * @param endpoint - API endpoint path (e.g., '/wp-json/cat/v1/recognition/jobs')
 * @param params - Optional query parameters
 * @returns Complete URL with encoded query string
 */
export const buildApiUrl = (
    endpoint: string,
    params?: Record<string, string | number | boolean | null | undefined>,
): string => {
    const url = new URL(endpoint, window.location.origin);

    if (params) {
        Object.entries(params).forEach(([key, value]) => {
            if (value !== null && value !== undefined) {
                url.searchParams.append(key, String(value));
            }
        });
    }

    return url.toString();
};

/**
 * Build headers for API requests.
 *
 * @param restNonce - WordPress REST API nonce
 * @param includeJson - Whether to include 'Content-Type: application/json'
 * @returns Headers object
 */
export const buildHeaders = (
    restNonce?: string,
    includeJson = false,
): HeadersInit => {
    const headers: HeadersInit = {};

    if (restNonce) {
        headers["X-WP-Nonce"] = restNonce;
    }

    if (includeJson) {
        headers["Content-Type"] = "application/json";
    }

    return headers;
};

/**
 * Options for fetchApi function.
 */
export interface FetchApiOptions {
    /** HTTP method (default: 'GET') */
    method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
    /** Query parameters to append to URL */
    params?: Record<string, string | number | boolean | null | undefined>;
    /** Request body (will be JSON-encoded if object) */
    body?: unknown;
    /** WordPress REST nonce for authentication */
    restNonce?: string;
}

/**
 * Unified fetch wrapper with consistent error handling.
 *
 * @param endpoint - API endpoint path
 * @param options - Request options
 * @returns Parsed JSON response
 * @throws Error with response data if request fails
 */
export const fetchApi = async <T = unknown>(
    endpoint: string,
    options: FetchApiOptions = {},
): Promise<T> => {
    const {
        method = "GET",
        params,
        body,
        restNonce,
    } = options;

    const url = buildApiUrl(endpoint, params);
    const hasBody = body !== undefined && method !== "GET";
    const headers = buildHeaders(restNonce, hasBody);

    const fetchOptions: RequestInit = {
        method,
        headers,
    };

    if (hasBody) {
        fetchOptions.body = typeof body === "string" ? body : JSON.stringify(body);
    }

    const response = await fetch(url, fetchOptions);
    await ensureOk(response);

    return handleJsonResponse(response) as Promise<T>;
};

