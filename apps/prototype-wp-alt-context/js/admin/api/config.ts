import { fetchApi } from '../utils/http';

type ApiConfig = {
	nonce: string;
	endpoints: Record<string, string>;
};

export const getConfig = (): ApiConfig => {
	const config = window.AltContextAdmin;
	if (!config) {
		throw new Error('AltContextAdmin configuration is missing.');
	}
	return config;
};

export const getEndpoint = (primary: string, ...fallbacks: string[]): string => {
	const config = getConfig();
	const candidates = [primary, ...fallbacks];
	for (const key of candidates) {
		const endpoint = config.endpoints[key];
		if (endpoint) {
			return endpoint;
		}
	}

	throw new Error(`Endpoint ${primary} is not configured.`);
};
