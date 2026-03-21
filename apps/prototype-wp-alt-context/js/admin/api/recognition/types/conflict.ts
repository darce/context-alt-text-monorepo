export type ConflictResolutionStatus = 'open' | 'accepted' | 'dismissed' | 'merged';
export type ConflictResolutionChoice = 'accepted' | 'dismissed' | 'accept_backend' | 'merge';
export type ProjectionConflictCode =
  | 'curated_cluster_deleted'
  | 'curated_member_deleted'
  | 'member_cluster_reassignment'
  | 'person_name_conflict'
  | 'version_conflict'
  | 'drift_conflict';

export interface ConflictRecord {
  id: number;
  tenant_id: string;
  entity_type: string;
  entity_key: string;
  outbox_id: number;
  expected_base_version: number;
  backend_version: number;
  local_revision: number;
  conflict_code: string;
  machine_payload: Record<string, unknown>;
  local_payload: Record<string, unknown>;
  resolution_status: ConflictResolutionStatus;
  resolved_at: string | null;
  created_at: string | null;
  allowed_resolutions: ConflictResolutionChoice[];
}

export interface ConflictListResponse {
  items: ConflictRecord[];
  total: number;
  limit: number;
  offset: number;
}

export interface ConflictDetailResponse {
  conflict: ConflictRecord;
}

export interface ResolveConflictRequest {
  resolution_status: ConflictResolutionChoice;
}

export interface ResolveConflictResponse {
  conflict: ConflictRecord | null;
}

export interface OutboxOperation {
  id: number;
  tenant_id: string;
  operation_type: string;
  entity_type: string;
  entity_key: string;
  status: string;
  attempts: number;
  expected_base_version?: number;
  local_revision?: number;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string | null;
  last_attempted_at?: string | null;
  acknowledged_at?: string | null;
  payload?: Record<string, unknown>;
}

export interface OutboxListResponse {
  items: OutboxOperation[];
  total: number;
  limit: number;
  offset: number;
}

export interface OutboxMutationResponse {
  operation: OutboxOperation | null;
}

export type WorkbenchOverlay = 'conflicts' | 'dead-letter' | null;
