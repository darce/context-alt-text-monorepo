export interface ApiConfig {
  nonce: string;
  endpoints: Record<string, string>;
  tenant_id?: string;
  tier?: string;
  max_media_per_batch?: number | string; // wp_localize_script may coerce to string
  devMode?: boolean | string | number; // wp_localize_script may convert to "1" or ""
}

export interface NormalizedConfig {
  nonce: string;
  endpoints: Record<string, string>;
  tenant_id?: string;
  tier?: string;
  maxMediaPerBatch: number;
  devMode: boolean;
}

const DEFAULT_MAX_MEDIA_PER_BATCH = 50;

export const normalizeConfig = (raw: ApiConfig): NormalizedConfig => {
  const rawMax = Number(raw.max_media_per_batch ?? DEFAULT_MAX_MEDIA_PER_BATCH);
  const maxMediaPerBatch = Number.isFinite(rawMax) && rawMax > 0 ? rawMax : DEFAULT_MAX_MEDIA_PER_BATCH;
  const devMode = raw.devMode === true || raw.devMode === 'true' || raw.devMode === '1' || raw.devMode === 1;

  return {
    nonce: raw.nonce,
    endpoints: raw.endpoints,
    tenant_id: raw.tenant_id,
    tier: raw.tier,
    maxMediaPerBatch,
    devMode,
  };
};

let cachedConfig: NormalizedConfig | null = null;

export const getConfig = (): NormalizedConfig => {
  if (cachedConfig) {
    return cachedConfig;
  }

  const config = window.AltContextAdmin;
  if (!config) {
    throw new Error('AltContextAdmin configuration is missing.');
  }

  cachedConfig = normalizeConfig(config);
  return cachedConfig;
};

export const resetConfigCache = (): void => {
  cachedConfig = null;
};

/**
 * Check if the application is in development mode.
 * When true, debug features like InsightFace metrics are enabled.
 * Note: wp_localize_script may convert booleans to "1"/"" strings.
 */
export const isDevMode = (): boolean => {
  try {
    return getConfig().devMode;
  } catch {
    return false;
  }
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
