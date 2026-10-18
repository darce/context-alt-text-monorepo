export type RetentionMode = 'retain_all' | 'dispose_after_ack' | 'purge_on_demand';

export interface RetentionPolicy {
  retention_mode: RetentionMode;
  last_export_at: string | null;
  last_purge_at: string | null;
  retention_updated_at: string | null;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  actor: string;
  scope: string;
  payload: Record<string, unknown>;
  result_status: string;
  created_at: string;
}

export interface RetentionStatusResponse {
  available: boolean;
  policy: RetentionPolicy | null;
  recent_audit_events: AuditEvent[];
}

export interface UpdateRetentionPolicyRequest {
  retention_mode: RetentionMode;
}

/**
 * Normalized result of `downloadExportJobData`.
 *
 * `schema_version` is required: the adapter rejects any snapshot without an
 * integer `schema_version` (`retentionApi.ts` `normalizeExportResponse`), so a
 * value of this type always carries one. Leaving it optional pushed a null-guard
 * onto every consumer for a case the boundary makes unrepresentable (ARCH-13).
 * `tenant_id` / `exported_at` stay optional — the snapshot genuinely may omit
 * them and the normalizer passes that absence through rather than inventing a
 * value (rg-015).
 */
export interface RetentionExportResponse {
  tenant_id?: string;
  exported_at?: string;
  schema_version: number;
  payload: Record<string, unknown>;
  summary: Record<string, number>;
}

export interface StartExportJobResponse {
  job_id: string;
  status: string;
}

export interface ExportJobStatusResponse {
  job_id: string;
  status: string;
  file_size?: number | null;
  error_message?: string | null;
}

export interface PurgeTenantDataRequest {
  scope: 'disposed' | 'all';
  confirm: true;
}

export interface PurgeTenantDataResponse {
  deleted_counts: Record<string, number>;
}

export interface ImportTenantDataRequest {
  data: Record<string, unknown>;
}

export interface ImportTenantDataResponse {
  tenant_id: string;
  schema_version: number;
  imported_at: string;
  counts: Record<string, number>;
}

export interface ApplyRetentionPresetRequest {
  preset: string;
}

export interface ApplyRetentionPresetResponse {
  tenant_id: string;
  retention_mode: RetentionMode;
  last_export_at: string | null;
  last_purge_at: string | null;
  retention_updated_at: string | null;
  preset: string;
}

export interface AuditEventListResponse {
  items: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
}
