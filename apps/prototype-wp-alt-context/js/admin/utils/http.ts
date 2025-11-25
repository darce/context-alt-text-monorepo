export type HTTPOptions = {
	method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
	body?: unknown;
	restNonce?: string;
};

const buildHeaders = (options: HTTPOptions) => {
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

export async function fetchApi<T>(endpoint: string, options: HTTPOptions = {}): Promise<T> {
	const response = await fetch(endpoint, {
		method: options.method ?? 'GET',
		headers: buildHeaders(options),
		body: options.body ? JSON.stringify(options.body) : null,
	});

	if (!response.ok) {
		const errorText = await response.text();
		throw new Error(`Request to ${endpoint} failed (${response.status}): ${errorText}`);
	}

	return response.json();
}
