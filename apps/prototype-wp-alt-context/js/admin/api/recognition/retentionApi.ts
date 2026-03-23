import { fetchRequiredApi } from '../../utils/http';
import { getConfig } from '../config';
import type {
  ApplyRetentionPresetRequest,
  ApplyRetentionPresetResponse,
  AuditEventListResponse,
  ExportJobStatusResponse,
  ImportTenantDataRequest,
  ImportTenantDataResponse,
  PurgeTenantDataRequest,
  PurgeTenantDataResponse,
  RetentionExportResponse,
  RetentionPolicy,
  RetentionStatusResponse,
  StartExportJobResponse,
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

export const updateRetentionPolicy = async (request: UpdateRetentionPolicyRequest): Promise<RetentionPolicy> => {
  const endpoint = requireRetentionEndpoint('retentionPolicy');
  return fetchRequiredApi<RetentionPolicy>(endpoint, {
    method: 'PATCH',
    body: request,
    restNonce: getConfig().nonce,
  });
};

export const exportTenantData = async (): Promise<StartExportJobResponse> => {
  const endpoint = requireRetentionEndpoint('retentionExport');
  return fetchRequiredApi<StartExportJobResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

export const getExportJobStatus = async (jobId: string): Promise<ExportJobStatusResponse> => {
  const base = requireRetentionEndpoint('retentionExport');
  return fetchRequiredApi<ExportJobStatusResponse>(`${base}/${jobId}/status`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const downloadExportJobData = async (jobId: string): Promise<RetentionExportResponse> => {
  const base = requireRetentionEndpoint('retentionExport');
  const response = await fetchRequiredApi<unknown>(`${base}/${jobId}/data`, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });

  return normalizeExportResponse(response);
};

export const purgeTenantData = async (request: PurgeTenantDataRequest): Promise<PurgeTenantDataResponse> => {
  const endpoint = requireRetentionEndpoint('retentionPurge');
  return fetchRequiredApi<PurgeTenantDataResponse>(endpoint, {
    method: 'POST',
    body: request,
    restNonce: getConfig().nonce,
  });
};

export const importTenantData = async (request: ImportTenantDataRequest): Promise<ImportTenantDataResponse> => {
  const endpoint = requireRetentionEndpoint('retentionImport');
  return fetchRequiredApi<ImportTenantDataResponse>(endpoint, {
    method: 'POST',
    body: request,
    restNonce: getConfig().nonce,
  });
};

export const fetchAuditEvents = async (params: {
  limit?: number;
  offset?: number;
  event_type?: string;
}): Promise<AuditEventListResponse> => {
  const endpoint = requireRetentionEndpoint('retentionAudit');
  const url = new URL(endpoint);
  if (params.limit !== undefined) {
    url.searchParams.set('limit', String(params.limit));
  }
  if (params.offset !== undefined) {
    url.searchParams.set('offset', String(params.offset));
  }
  if (params.event_type) {
    url.searchParams.set('event_type', params.event_type);
  }
  return fetchRequiredApi<AuditEventListResponse>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

export const applyRetentionPreset = async (
  request: ApplyRetentionPresetRequest,
): Promise<ApplyRetentionPresetResponse> => {
  const endpoint = requireRetentionEndpoint('retentionPolicy');
  return fetchRequiredApi<ApplyRetentionPresetResponse>(`${endpoint}/preset`, {
    method: 'POST',
    body: request,
    restNonce: getConfig().nonce,
  });
};
