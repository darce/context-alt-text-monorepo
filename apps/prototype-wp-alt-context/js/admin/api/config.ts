import { NonceRefreshFailedError } from '../utils/errorTaxonomy';
import { createLogger, type Logger } from '../utils/logger';

/**
 * `NonceRefreshFailedError` is declared in the leaf module
 * `utils/errorTaxonomy` and re-exported from its historical home here. It moved
 * because `utils/http` and `utils/appError` both need it, and importing it from
 * this module closed a load-time cycle that left the class binding undefined at
 * a subclass's `extends` site (FEBT2-LA-NEW-01 / FEBT2-LC-NEW-03). ARCH-20
 * (lexicons/engineering.md:570): the dependency arrow points at the stable error
 * vocabulary, not at this WordPress config adapter.
 */
export { isNonceRefreshAuthRejection, NonceRefreshFailedError } from '../utils/errorTaxonomy';

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
  guided_live_media_id?: unknown; // wp_localize_script stringifies numbers
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
  /** Attachment the guided prototype describes live; null when unconfigured. */
  guidedLiveMediaId: number | null;
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

/**
 * An attachment id is a positive integer. Anything else — an unset option, a
 * float, a stray string — means the guided live run has no subject, and saying
 * so is better than submitting a run for media 0 ([RLSE-05] silent failure is
 * the worst failure).
 *
 * This must agree with the PHP side that publishes the value
 * (`Admin::get_guided_live_media_id`, `FILTER_VALIDATE_INT`), or the two ends
 * disagree about whether the demo has a subject at all. `Number()` is the wrong
 * tool for that: it reads `'0x1a'` as 26 and `'1e10'` as ten billion, both of
 * which PHP rejects outright. A decimal-digits test with PHP's surrounding-
 * whitespace tolerance is the same predicate on both sides (rg-005).
 */
const DECIMAL_INT_PATTERN = /^[+-]?\d+$/;

const normalizeAttachmentId = (value: unknown): number | null => {
  if (typeof value === 'number') {
    return Number.isInteger(value) && value > 0 ? value : null;
  }
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  if (!DECIMAL_INT_PATTERN.test(trimmed)) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
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
    requestLog.warn(`AltContextAdmin configuration field "${field}" is missing or empty; dependent features degrade.`, {
      field,
    });
    return '';
  }
  return value;
};

export const normalizeConfig = (raw: ApiConfig): NormalizedConfig => {
  // One normalization pass is one unit of work: every soft warning it emits
  // shares this id, and a later pass gets a different one (OBS-03). A
  // module-scope logger has no unit of work and carries no requestId (rg-015).
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
      typeof raw.effectiveTargetUrl === 'string' && raw.effectiveTargetUrl.trim() !== '' ? raw.effectiveTargetUrl : '',
    guidedLiveMediaId: normalizeAttachmentId(raw.guided_live_media_id),
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
 * Attachment the guided prototype describes live, or null when there is none.
 *
 * The guided screen is the one admin surface that renders without the SPA
 * bootstrap (its entrance card, and component tests in isolation). No bootstrap
 * means no live run to offer, which is a disabled button and a sentence — not
 * an exception that takes the lesson down with it.
 */
export const getGuidedLiveMediaId = (): number | null => {
  if (!cachedConfig && !window.AltContextAdmin) {
    return null;
  }
  return getConfig().guidedLiveMediaId;
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

    if (ok && body !== '' && body !== '0' && body !== '-1' && NONCE_BODY_PATTERN.test(body)) {
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
