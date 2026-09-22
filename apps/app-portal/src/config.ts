export type PortalRuntimeConfig = {
  publishableKey: string | null;
  fapiOrigin: string | null;
  portalEnabled: boolean;
  paymentsEnabled?: boolean;
  publicPlanCode?: string | null;
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

function parsePaymentsEnabled(value: string | undefined): boolean {
  const normalized = trimEnv(value).toLowerCase();
  return normalized === '1' || normalized === 'true' || normalized === 'on' || normalized === 'yes';
}

function parsePublicPlanCode(value: string | undefined): string | null {
  const raw = trimEnv(value);
  return raw.length > 0 ? raw : null;
}

export function parsePortalConfig(env: Record<string, string | undefined>): PortalRuntimeConfig {
  const publishableKey = trimEnv(env.VITE_CLERK_PUBLISHABLE_KEY);
  const config: PortalRuntimeConfig = {
    publishableKey: publishableKey.length > 0 ? publishableKey : null,
    fapiOrigin: parseFapiOrigin(env.VITE_CLERK_FAPI),
    portalEnabled: parseEnabledFlag(env.VITE_PORTAL_ENABLED),
  };
  if (Object.prototype.hasOwnProperty.call(env, 'VITE_PAYMENTS_ENABLED')) {
    config.paymentsEnabled = parsePaymentsEnabled(env.VITE_PAYMENTS_ENABLED);
  }
  if (Object.prototype.hasOwnProperty.call(env, 'VITE_PUBLIC_PLAN_CODE')) {
    config.publicPlanCode = parsePublicPlanCode(env.VITE_PUBLIC_PLAN_CODE);
  }
  return config;
}

export function readPortalConfig(): PortalRuntimeConfig {
  const env = import.meta.env as Record<string, string | undefined>;
  return parsePortalConfig({
    VITE_CLERK_PUBLISHABLE_KEY: env.VITE_CLERK_PUBLISHABLE_KEY,
    VITE_CLERK_FAPI: env.VITE_CLERK_FAPI,
    VITE_PORTAL_ENABLED: env.VITE_PORTAL_ENABLED,
    VITE_PAYMENTS_ENABLED: env.VITE_PAYMENTS_ENABLED,
    VITE_PUBLIC_PLAN_CODE: env.VITE_PUBLIC_PLAN_CODE,
  });
}
