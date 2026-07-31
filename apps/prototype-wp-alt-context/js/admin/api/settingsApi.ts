import { fetchRequiredApi } from '../utils/http';
import { getEndpoint, getConfig } from './config';

/**
 * BR-138: why a present service-URL value was discarded by is_valid_base_url.
 * Mirrors RecognitionEndpointResolver::URL_REJECTION_* (sr-007).
 */
export const UrlRejectionReason = {
  REJECTED_SCHEME: 'rejected_scheme',
  NON_LOOPBACK_HTTP: 'non_loopback_http',
  INVALID_URL: 'invalid_url',
} as const;

export type UrlRejectionReasonValue = (typeof UrlRejectionReason)[keyof typeof UrlRejectionReason];

export type UrlRejectionSource = 'constant' | 'option' | 'filter';

export interface SettingsResponse {
  url: string;
  url_source: 'constant' | 'option' | 'filter' | 'default';
  // BR-138: present when a tier held a value that failed is_valid_base_url.
  // Null when genuinely unconfigured or when a valid URL resolved.
  // REST rename of service_url_rejection_* (same convention as url/url_source).
  url_rejection_reason: UrlRejectionReasonValue | null;
  url_rejection_source: UrlRejectionSource | null;
  url_rejection_value: string | null;
  effective_target_url: string;
  effective_target_mode: 'service' | 'local';
  // RECOG-1: read-only dev-hatch diagnostics. The product no longer exposes a
  // target toggle; `recognition_source` reports 'local' only when the
  // ACX_RECOGNITION_SOURCE constant/filter dev hatch is active.
  recognition_source: 'service' | 'local';
  recognition_source_source: 'constant' | 'option' | 'filter' | 'default';
  api_key_set: boolean;
  api_key_last4: string;
  key_source: 'constant' | 'option' | 'filter' | 'default';
  // Tenant identity (settings GET, class-settings-controller.php get_settings).
  // tenant_id_source mirrors TenantIdentity::resolve()['source'].
  tenant_id: string;
  tenant_id_source: 'constant' | 'option' | 'filter' | 'default' | 'derived';
  tenant_paired: boolean;
  // ALTQ-1: where describe writes land — mirrors the PHP AltStyle constants
  // (class-alt-style.php) bit-for-bit; invalid stored values are normalized
  // to 'alt_only' server-side before reaching this payload.
  alt_style: AltStyleValue;
  description_budget: DescriptionBudget;
}

export const AltStyle = {
  ALT_ONLY: 'alt_only',
  ALT_PLUS_DESCRIPTION: 'alt_plus_description',
} as const;

export type AltStyleValue = (typeof AltStyle)[keyof typeof AltStyle];

export interface DescriptionBudgetUsage {
  attempts: number;
  successes: number;
  failures: number;
  cost_total: number;
}

export interface DescriptionBudgetError {
  media_id: number;
  error_code: string | null;
  error_message: string | null;
  retryable: boolean | null;
  occurred_at: string;
}

export interface DescriptionBudget {
  max_attempts: number;
  usage: DescriptionBudgetUsage;
  recent_errors: DescriptionBudgetError[];
}

export const RecognitionSource = {
  SERVICE: 'service',
  LOCAL: 'local',
} as const;

export type RecognitionSourceValue = (typeof RecognitionSource)[keyof typeof RecognitionSource];

export interface SaveSettingsPayload {
  url?: string;
  api_key?: string;
  alt_style?: AltStyleValue;
  description_budget?: {
    max_attempts: number;
  };
}

/**
 * Wire vocabulary for POST /settings `result` [sr-007].
 * Mirrors SettingsController::SAVE_RESULT_* bit-for-bit.
 */
export const SettingsSaveResult = {
  OK: 'ok',
  PARTIAL: 'partial',
  ERROR: 'error',
} as const;

export type SettingsSaveResultValue =
  (typeof SettingsSaveResult)[keyof typeof SettingsSaveResult];

export interface SaveSettingsResponse {
  saved: string[];
  result: SettingsSaveResultValue | string;
  /** Present when result is partial/error — fields that did not persist. */
  failed?: string[];
}

export const TestConnectionOutcome = {
  CONNECTED: 'connected',
  NOT_CONFIGURED: 'not_configured',
  INVALID_KEY: 'invalid_key',
  EXPIRED: 'expired',
  REVOKED: 'revoked',
  TENANT_MISMATCH: 'tenant_mismatch',
  TENANT_PAIRING_CONFLICT: 'tenant_pairing_conflict',
  RATE_LIMITED: 'rate_limited',
  SERVER_ERROR: 'server_error',
  NETWORK_ERROR: 'network_error',
  TLS_ERROR: 'tls_error',
} as const;

export type TestConnectionOutcomeValue = (typeof TestConnectionOutcome)[keyof typeof TestConnectionOutcome];

const KNOWN_TEST_CONNECTION_OUTCOMES: ReadonlySet<string> = new Set(Object.values(TestConnectionOutcome));

export const isTestConnectionOutcome = (value: unknown): value is TestConnectionOutcomeValue =>
  typeof value === 'string' && KNOWN_TEST_CONNECTION_OUTCOMES.has(value);

// RECOG-1: the keyless local liveness probe is retired; test always runs the
// authenticated service probe.
export type TestConnectionProbeMode = 'service_auth';

export interface TestConnectionResponse {
  outcome: TestConnectionOutcomeValue;
  status_code?: number;
  retry_after_seconds?: number;
  detail?: string;
  body?: unknown;
  probe_mode?: TestConnectionProbeMode;
  probed_url?: string;
  // Tenant-pairing fields merged by class-settings-controller.php attempt_tenant_pairing.
  // All optional: present only on the relevant pairing path (error / conflict / success).
  pairing_error?: string | null;
  persisted_tenant_id?: string;
  key_tenant_id?: string;
  tenant_paired?: boolean;
  tenant_id?: string;
  tenant_id_source?: string;
  rekey_strategy?: string;
  rekey_updated_rows?: number;
}

export const fetchSettings = async (): Promise<SettingsResponse> => {
  const endpoint = getEndpoint('settings');
  return fetchRequiredApi<SettingsResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const saveSettings = async (payload: SaveSettingsPayload): Promise<SaveSettingsResponse> => {
  const endpoint = getEndpoint('settings');
  return fetchRequiredApi<SaveSettingsResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    body: payload,
  });
};

export interface TestConnectionPayload {
  // Set when the operator adopts the API key's tenant from the pairing-conflict banner;
  // read by class-settings-controller.php request_confirms_tenant_pairing.
  confirm_tenant_pairing?: boolean;
}

export const testConnection = async (
  payload: TestConnectionPayload = {},
): Promise<TestConnectionResponse> => {
  const endpoint = getEndpoint('settingsTest');
  return fetchRequiredApi<TestConnectionResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    body: payload,
  });
};
