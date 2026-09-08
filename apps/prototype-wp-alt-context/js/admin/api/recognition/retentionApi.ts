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

/**
 * Top-level collection keys carried by a recognition tenant-export snapshot.
 *
 * rg-005 (schema/contract parity): this list is the single canonical copy for
 * the frontend. It mirrors `IMPORT_COLLECTION_KEYS` in
 * `recognition/application/services/import_service.py`, which mirrors the keys
 * emitted by `TenantExportService.export_tenant_data`.
 */
export const EXPORT_COLLECTION_KEYS = [
  'clusters',
  'media_identities',
  'identity_suggestions',
  'name_suggestions',
  'cluster_merge_suggestions',
  'scan_jobs',
] as const;

/** Locally authored, safe-to-display boundary rejection (never carries remote text). */
export class RetentionExportResponseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RetentionExportResponseError';
  }
}

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * Parse the export-download response into the shape the UI writes to disk.
 *
 * rg-015: `GET /retention/export/{job_id}/data` returns `ExportJob.data_json`
 * verbatim — the bare snapshot produced by `TenantExportService.export_tenant_data`
 * (`recognition/interface_adapters/http/routers/retention.py:208-211`), proxied
 * through unchanged by `RetentionController::get_export_job_data`. There is no
 * `data`/`payload` wrapper and no `counts`/`summary` field on the wire, so
 * accepting either wrapper shape or defaulting to `{}` invents contract
 * metadata. Exactly the documented shape is supported; anything else is an
 * explicit error (RLSE-05: a malformed response that yields an empty-looking
 * successful download is a silent data loss the user discovers on a later
 * import).
 *
 * `summary` is derived from the snapshot's own collection lengths — the same
 * derivation the backend performs in `_validate_collections` — not fabricated
 * from an absent upstream field.
 */
const normalizeExportResponse = (payload: unknown): RetentionExportResponse => {
  if (!isPlainObject(payload)) {
    throw new RetentionExportResponseError('Export data response was malformed.');
  }

  const schemaVersion = payload.schema_version;
  if (typeof schemaVersion !== 'number' || !Number.isInteger(schemaVersion)) {
    throw new RetentionExportResponseError('Export data response was malformed: missing schema_version.');
  }

  const presentKeys = EXPORT_COLLECTION_KEYS.filter((key) => key in payload);
  if (presentKeys.length === 0) {
    throw new RetentionExportResponseError('Export data response was malformed: no exported collections.');
  }

  const summary: Record<string, number> = {};
  for (const key of presentKeys) {
    const collection = payload[key];
    if (!Array.isArray(collection)) {
      throw new RetentionExportResponseError('Export data response was malformed: collections must be arrays.');
    }
    summary[key] = collection.length;
  }

  return {
    tenant_id: typeof payload.tenant_id === 'string' ? payload.tenant_id : undefined,
    exported_at: typeof payload.exported_at === 'string' ? payload.exported_at : undefined,
    schema_version: schemaVersion,
    payload,
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
