import { fetchRequiredApi } from '../../utils/http';
import { getConfig } from '../config';
import type {
  PurgeTenantDataRequest,
  PurgeTenantDataResponse,
  RetentionExportResponse,
  RetentionPolicy,
  RetentionStatusResponse,
  UpdateRetentionPolicyRequest,
} from './types';

const getRetentionEndpoint = (...keys: string[]): string | null => {
  const { endpoints } = getConfig();

  for (const key of keys) {
    const endpoint = endpoints[key];
    if (endpoint) {
      return endpoint;
    }
  }

  return null;
};

const requireRetentionEndpoint = (...keys: string[]): string => {
  const endpoint = getRetentionEndpoint(...keys);
  if (!endpoint) {
    throw new Error('Retention endpoints are not configured yet.');
  }

  return endpoint;
};

const normalizeExportResponse = (payload: unknown): RetentionExportResponse => {
  if (!payload || typeof payload !== 'object') {
    return { payload: {}, summary: {} };
  }

  const response = payload as Record<string, unknown>;
  const rawPayload =
    response.data && typeof response.data === 'object'
      ? (response.data as Record<string, unknown>)
      : response.payload && typeof response.payload === 'object'
        ? (response.payload as Record<string, unknown>)
        : response;
  const summary =
    response.counts && typeof response.counts === 'object'
      ? (response.counts as Record<string, number>)
      : response.summary && typeof response.summary === 'object'
        ? (response.summary as Record<string, number>)
        : {};

  return {
    tenant_id: typeof response.tenant_id === 'string' ? response.tenant_id : undefined,
    exported_at: typeof response.exported_at === 'string' ? response.exported_at : undefined,
    schema_version: typeof response.schema_version === 'number' ? response.schema_version : undefined,
    payload: rawPayload,
    summary,
  };
};

export const fetchRetentionStatus = async (): Promise<RetentionStatusResponse> => {
  const endpoint = getRetentionEndpoint('retentionStatus');
  if (!endpoint) {
    return {
      available: false,
      policy: null,
      recent_audit_events: [],
    };
  }

  return fetchRequiredApi<RetentionStatusResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const updateRetentionPolicy = async (
  request: UpdateRetentionPolicyRequest,
): Promise<RetentionPolicy> => {
  const endpoint = requireRetentionEndpoint('retentionPolicy');
  return fetchRequiredApi<RetentionPolicy>(endpoint, {
    method: 'PATCH',
    body: request,
    restNonce: getConfig().nonce,
  });
};

export const exportTenantData = async (): Promise<RetentionExportResponse> => {
  const endpoint = requireRetentionEndpoint('retentionExport');
  const response = await fetchRequiredApi<unknown>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
  });

  return normalizeExportResponse(response);
};

export const purgeTenantData = async (
  request: PurgeTenantDataRequest,
): Promise<PurgeTenantDataResponse> => {
  const endpoint = requireRetentionEndpoint('retentionPurge');
  return fetchRequiredApi<PurgeTenantDataResponse>(endpoint, {
    method: 'POST',
    body: request,
    restNonce: getConfig().nonce,
  });
};
