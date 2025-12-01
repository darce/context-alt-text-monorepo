export interface MediaMeta {
  url: string | null;
  width?: number;
  height?: number;
}

interface WPMediaSize {
  source_url?: string | null;
  width?: number;
  height?: number;
}

interface WPMediaDetails {
  sizes?: Record<string, WPMediaSize>;
  width?: number;
  height?: number;
}

interface WPMediaResponse {
  media_details?: WPMediaDetails;
  source_url?: string | null;
}

const getWpRestBase = (): string => {
  const root = window.wpApiSettings?.root;
  if (root) {
    return root.replace(/\/$/, '');
  }
  return `${window.location.origin}/wp-json`;
};

const getRestNonce = (): string | undefined => window.wpApiSettings?.nonce ?? window.AltContextAdmin?.nonce;

const isWPMediaResponse = (payload: unknown): payload is WPMediaResponse =>
  Boolean(payload) && typeof payload === 'object';

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
      return { url: null };
    }

    const payload: unknown = await response.json();
    if (!isWPMediaResponse(payload)) {
      return { url: null };
    }

    const sizes = payload.media_details?.sizes ?? {};
    const preferredUrl =
      sizes?.thumbnail?.source_url ??
      sizes?.medium?.source_url ??
      sizes?.medium_large?.source_url ??
      sizes?.large?.source_url ??
      payload.source_url ??
      sizes?.full?.source_url ??
      null;

    return {
      url: preferredUrl,
      width: payload.media_details?.width ?? payload.media_details?.sizes?.full?.width,
      height: payload.media_details?.height ?? payload.media_details?.sizes?.full?.height,
    };
  } catch {
    return { url: null };
  }
};
