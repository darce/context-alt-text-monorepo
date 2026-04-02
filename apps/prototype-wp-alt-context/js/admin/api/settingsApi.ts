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

export interface TestConnectionResponse {
  connected: boolean;
  status_code?: number;
  body?: unknown;
  error?: string;
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
    body: JSON.stringify(payload),
  });
};

export const testConnection = async (): Promise<TestConnectionResponse> => {
  const endpoint = getEndpoint('settingsTest');
  return fetchRequiredApi<TestConnectionResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};
