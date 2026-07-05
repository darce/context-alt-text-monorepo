import { fetchRequiredApi } from '../utils/http';
import { getEndpoint, getConfig } from './config';

export interface SettingsResponse {
  url: string;
  url_source: 'constant' | 'option' | 'filter' | 'default';
  local_url: string;
  local_url_source: 'constant' | 'option' | 'filter' | 'default';
  effective_target_url: string;
  effective_target_mode: 'service' | 'local';
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
  description_budget: DescriptionBudget;
}

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
  local_url?: string;
  recognition_source?: RecognitionSourceValue;
  api_key?: string;
  description_budget?: {
    max_attempts: number;
  };
}

export interface SaveSettingsResponse {
  saved: string[];
  result: string;
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

export type TestConnectionProbeMode = 'local_liveness' | 'service_auth';

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
  probe_target?: RecognitionSourceValue;
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
