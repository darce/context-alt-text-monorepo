export type MediaMeta = {
	url: string | null;
	width?: number;
	height?: number;
};

const getWpRestBase = (): string => {
	const root = window.wpApiSettings?.root;
	if (root) {
		return root.replace(/\/$/, '');
	}
	return `${window.location.origin}/wp-json`;
};

const getRestNonce = (): string | undefined => window.wpApiSettings?.nonce ?? window.AltContextAdmin?.nonce;

export const fetchMediaMeta = async (mediaId: number): Promise<MediaMeta> => {
	const base = getWpRestBase();
	const nonce = getRestNonce();
	try {
		const response = await fetch(`${base}/wp/v2/media/${mediaId}?context=edit`, {
			headers: {
				Accept: 'application/json',
				...(nonce ? { 'X-WP-Nonce': nonce } : {}),
			},
			credentials: 'same-origin',
		});

		if (!response.ok) {
			return null;
		}

		const payload = await response.json();
		return {
			url:
				payload.source_url ??
				payload.media_details?.sizes?.thumbnail?.source_url ??
				payload.media_details?.sizes?.medium?.source_url ??
				null,
			width: payload.media_details?.width ?? payload.media_details?.sizes?.full?.width,
			height: payload.media_details?.height ?? payload.media_details?.sizes?.full?.height,
		};
	} catch {
		return { url: null };
	}
};
