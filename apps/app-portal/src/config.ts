export type PortalRuntimeConfig = {
  publishableKey: string | null;
  fapiOrigin: string | null;
  portalEnabled: boolean;
};

function trimEnv(value: string | undefined): string {
  return typeof value === 'string' ? value.trim() : '';
}

function parseEnabledFlag(value: string | undefined): boolean {
  const normalized = trimEnv(value).toLowerCase();
  if (normalized === '' || normalized === '1' || normalized === 'true' || normalized === 'on' || normalized === 'yes') {
    return true;
  }
  if (normalized === '0' || normalized === 'false' || normalized === 'off' || normalized === 'no') {
    return false;
  }
  return true;
}

export function parseFapiOrigin(value: string | undefined): string | null {
  const raw = trimEnv(value);
  if (!raw) {
    return null;
  }
  const withProtocol = raw.includes('://') ? raw : `https://${raw}`;
  try {
    const url = new URL(withProtocol);
    if (url.protocol !== 'https:' && url.protocol !== 'http:') {
      return null;
    }
    return `${url.protocol}//${url.host}`;
  } catch {
    return null;
  }
}

export function parsePortalConfig(env: Record<string, string | undefined>): PortalRuntimeConfig {
  const publishableKey = trimEnv(env.VITE_CLERK_PUBLISHABLE_KEY);
  return {
    publishableKey: publishableKey.length > 0 ? publishableKey : null,
    fapiOrigin: parseFapiOrigin(env.VITE_CLERK_FAPI),
    portalEnabled: parseEnabledFlag(env.VITE_PORTAL_ENABLED),
  };
}

export function readPortalConfig(): PortalRuntimeConfig {
  return parsePortalConfig({
    VITE_CLERK_PUBLISHABLE_KEY: import.meta.env.VITE_CLERK_PUBLISHABLE_KEY,
    VITE_CLERK_FAPI: import.meta.env.VITE_CLERK_FAPI,
    VITE_PORTAL_ENABLED: import.meta.env.VITE_PORTAL_ENABLED,
  });
}
