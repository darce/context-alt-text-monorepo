interface ApiConfig {
  nonce: string;
  endpoints: Record<string, string>;
  tenant_id?: string;
  tier?: string;
  max_media_per_batch?: number | string; // wp_localize_script may coerce to string
  devMode?: boolean | string | number; // wp_localize_script may convert to "1" or ""
}

export const getConfig = (): ApiConfig => {
  const config = window.AltContextAdmin;
  if (!config) {
    throw new Error('AltContextAdmin configuration is missing.');
  }
  return config;
};

/**
 * Check if the application is in development mode.
 * When true, debug features like InsightFace metrics are enabled.
 * Note: wp_localize_script may convert booleans to "1"/"" strings.
 */
export const isDevMode = (): boolean => {
  try {
    const devMode = getConfig().devMode;
    // Handle both boolean true and string "1" (from wp_localize_script)
    return devMode === true || devMode === '1' || devMode === 1;
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
