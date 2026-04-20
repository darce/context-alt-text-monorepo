import { fetchRequiredApi } from '../utils/http';
import { getEndpoint, getConfig } from './config';

export interface SettingsResponse {
  url: string;
  url_source: 'constant' | 'option' | 'filter' | 'default';
  api_key_set: boolean;
  api_key_last4: string;
  key_source: 'constant' | 'option' | 'filter' | 'default';
}

export interface SaveSettingsPayload {
  url?: string;
  api_key?: string;
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
  RATE_LIMITED: 'rate_limited',
  SERVER_ERROR: 'server_error',
  NETWORK_ERROR: 'network_error',
  TLS_ERROR: 'tls_error',
} as const;

export type TestConnectionOutcomeValue =
  (typeof TestConnectionOutcome)[keyof typeof TestConnectionOutcome];

const KNOWN_TEST_CONNECTION_OUTCOMES: ReadonlySet<string> = new Set(
  Object.values(TestConnectionOutcome)
);

export const isTestConnectionOutcome = (value: unknown): value is TestConnectionOutcomeValue =>
  typeof value === 'string' && KNOWN_TEST_CONNECTION_OUTCOMES.has(value);

export interface TestConnectionResponse {
  outcome: TestConnectionOutcomeValue;
  status_code?: number;
  retry_after_seconds?: number;
  detail?: string;
  body?: unknown;
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

export const testConnection = async (): Promise<TestConnectionResponse> => {
  const endpoint = getEndpoint('settingsTest');
  return fetchRequiredApi<TestConnectionResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};
