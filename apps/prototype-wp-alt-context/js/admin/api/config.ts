import { createLogger, type Logger } from '../utils/logger';

let log: Logger | undefined;
const configLog = (): Logger => {
  log ??= createLogger('api.config');
  return log;
};

export interface AdminUrlsConfig {
  mediaEditBase?: string;
  roster?: string;
  mediaLibrary?: string;
}

export interface ApiConfig {
  nonce: string;
  ajaxUrl: string;
  endpoints: Record<string, string>;
  tenant_id?: string;
  tier?: string;
  adminUrls?: AdminUrlsConfig;
  max_media_per_batch?: number | string; // wp_localize_script may coerce to string
  devMode?: boolean | string | number; // wp_localize_script may convert to "1" or ""
  recognitionSource?: 'service' | 'local';
  effectiveTargetUrl?: string;
}

export interface NormalizedConfig {
  nonce: string;
  ajaxUrl: string;
  endpoints: Record<string, string>;
  tenant_id?: string;
  tier?: string;
  adminUrls: AdminUrlsConfig;
  maxMediaPerBatch: number;
  devMode: boolean;
  recognitionSource: 'service' | 'local';
  effectiveTargetUrl: string;
}

// NOTE: Batch limits removed for MVP. Previously 50, now set high to disable chunking.
// See docs/tasks/4.0/4.11.0/progress-tracking-investigation-2026-01-20.md
const DEFAULT_MAX_MEDIA_PER_BATCH = 10000;

/** WP rest-nonce handler exits the raw nonce string; reject sentinels and HTML. */
const NONCE_BODY_PATTERN = /^[a-f0-9]{8,20}$/i;

/**
 * Bounds the refresh network round-trip so a hung admin-ajax request cannot pin
 * the single-flight slot forever — otherwise every subsequent nonce-403 caller
 * awaits a promise that never settles and the whole SPA stalls ([RES-02]).
 */
export const NONCE_REFRESH_TIMEOUT_MS = 10_000;

export class NonceRefreshFailedError extends Error {
  readonly _tag = 'nonce_refresh' as const;
  readonly causeStatus: number | undefined;
  readonly bodyPreview: string;
  readonly cause: unknown;

  constructor({
    message,
    causeStatus,
    bodyPreview,
  }: {
    message: string;
    causeStatus?: number;
    bodyPreview?: string;
  }) {
    super(message);
    this.name = 'NonceRefreshFailedError';
    this.causeStatus = causeStatus;
    this.bodyPreview = bodyPreview ?? '';
    this.cause = undefined;
  }
}

/** WP rest-nonce logged-out / cookie-fail sentinels — not a transport blip. */
export const isNonceRefreshAuthRejection = (error: NonceRefreshFailedError): boolean => {
  if (error.causeStatus === 401 || error.causeStatus === 403) {
    return true;
  }
  const body = error.bodyPreview.trim();
  return body === '0' || body === '-1';
};

const normalizeOptionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim() !== '' ? value : undefined;

/**
 * Boundary validation that fails SOFT: a payload missing this field (deploy
 * skew — cached HTML with an older localized payload) degrades the one
 * capability that needs it instead of hard-failing every getConfig() caller.
 */
const softNonEmptyString = (value: unknown, field: string, requestLog: Logger): string => {
  if (typeof value !== 'string' || value.trim() === '') {
    requestLog.warn(
      `AltContextAdmin configuration field "${field}" is missing or empty; dependent features degrade.`,
    );
    return '';
  }
  return value;
};

export const normalizeConfig = (raw: ApiConfig): NormalizedConfig => {
  const requestLog = configLog().withRequest();
  const rawMax = Number(raw.max_media_per_batch ?? DEFAULT_MAX_MEDIA_PER_BATCH);
  const maxMediaPerBatch = Number.isFinite(rawMax) && rawMax > 0 ? rawMax : DEFAULT_MAX_MEDIA_PER_BATCH;
  const devMode = raw.devMode === true || raw.devMode === 'true' || raw.devMode === '1' || raw.devMode === 1;
  const adminUrls = {
    mediaEditBase: normalizeOptionalString(raw.adminUrls?.mediaEditBase),
    roster: normalizeOptionalString(raw.adminUrls?.roster),
    mediaLibrary: normalizeOptionalString(raw.adminUrls?.mediaLibrary),
  };

  return {
    nonce: softNonEmptyString(raw.nonce, 'nonce', requestLog),
    ajaxUrl: softNonEmptyString(raw.ajaxUrl, 'ajaxUrl', requestLog),
    endpoints: raw.endpoints,
    tenant_id: raw.tenant_id,
    tier: raw.tier,
    adminUrls,
    maxMediaPerBatch,
    devMode,
    recognitionSource: raw.recognitionSource === 'local' ? 'local' : 'service',
    // RECOG-1: hosted service is the canonical target; do not fall back to a local
    // default. An unconfigured install reports an empty effective target.
    effectiveTargetUrl:
      typeof raw.effectiveTargetUrl === 'string' && raw.effectiveTargetUrl.trim() !== ''
        ? raw.effectiveTargetUrl
        : '',
  };
};

let cachedConfig: NormalizedConfig | null = null;
let refreshInFlight: Promise<string> | null = null;

/**
 * Inject config for non-SPA surfaces (post.php attachment-edit).
 * SPA path is unchanged: getConfig falls back to window.AltContextAdmin.
 */
export const registerConfig = (raw: ApiConfig): NormalizedConfig => {
  cachedConfig = normalizeConfig(raw);
  return cachedConfig;
};

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

/**
 * Live nonce from the cached config. After setNonce / refreshRestNonce, existing
 * getConfig().nonce call sites stay correct because the cached object is mutated.
 */
export const getNonce = (): string => getConfig().nonce;

/**
 * Mutate the cached config nonce in place so all live readers see the refresh.
 * window.wpApiSettings is mirrored because mediaApi prefers it as its nonce
 * source (matching WP core's apiFetch middleware, which rotates it the same way).
 */
export const setNonce = (nonce: string): void => {
  const config = getConfig();
  config.nonce = nonce;
  if (window.wpApiSettings) {
    window.wpApiSettings.nonce = nonce;
  }
};

/**
 * Refresh the WP REST nonce via core admin-ajax rest-nonce action.
 * GET-only, raw-string body (not JSON). Single-flight; slot cleared in finally
 * so a rejection does not poison later attempts ([RES-06]).
 */
export const refreshRestNonce = (): Promise<string> => {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  refreshInFlight = (async (): Promise<string> => {
    const { ajaxUrl } = getConfig();
    if (ajaxUrl === '') {
      throw new NonceRefreshFailedError({
        message: 'REST nonce refresh unavailable: ajaxUrl missing from localized config (deploy skew).',
      });
    }
    const url = `${ajaxUrl}${ajaxUrl.includes('?') ? '&' : '?'}action=rest-nonce`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), NONCE_REFRESH_TIMEOUT_MS);
    let ok: boolean;
    let status: number;
    let body: string;
    try {
      const response = await fetch(url, {
        method: 'GET',
        credentials: 'same-origin',
        signal: controller.signal,
      });
      ok = response.ok;
      status = response.status;
      body = (await response.text()).trim();
    } catch (error) {
      // Timeout-abort or transport failure: a typed refresh failure, never a
      // hung promise. The single-flight slot is released by the finally below.
      throw new NonceRefreshFailedError({
        message: controller.signal.aborted
          ? `REST nonce refresh timed out after ${NONCE_REFRESH_TIMEOUT_MS}ms.`
          : `REST nonce refresh network error: ${error instanceof Error ? error.message : String(error)}.`,
      });
    } finally {
      clearTimeout(timer);
    }

    if (
      ok &&
      body !== '' &&
      body !== '0' &&
      body !== '-1' &&
      NONCE_BODY_PATTERN.test(body)
    ) {
      setNonce(body);
      return body;
    }

    throw new NonceRefreshFailedError({
      message: `REST nonce refresh failed (${status}): unexpected body.`,
      causeStatus: status,
      bodyPreview: body.slice(0, 240),
    });
  })().finally(() => {
    refreshInFlight = null;
  });

  return refreshInFlight;
};

export const resetConfigCache = (): void => {
  cachedConfig = null;
  refreshInFlight = null;
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

/** Minimal localized payload for the attachment-edit entry (not AltContextAdmin). */
export interface AttachmentEditLocalizedConfig {
  nonce: string;
  ajaxUrl: string;
  attachmentId: number | string;
  imageUrl: string;
  imageWidth: number | string;
  imageHeight: number | string;
  workbenchUrl: string;
  endpoints: Record<string, string>;
}

declare global {
  interface Window {
    AltContextAdmin?: ApiConfig;
    AltContextAttachmentEdit?: AttachmentEditLocalizedConfig;
    wpApiSettings?: {
      root: string;
      nonce: string;
    };
  }
}
